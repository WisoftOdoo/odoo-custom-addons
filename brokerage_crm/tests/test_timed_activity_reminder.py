from datetime import datetime, timedelta

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestTimedActivityReminder(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create({
            "name": "Timed Reminder Agent",
            "login": "timed.reminder.agent@test.invalid",
            "tz": "Asia/Dubai",
            "group_ids": [Command.set([
                cls.env.ref("base.group_user").id,
                cls.env.ref(
                    "brokerage_crm.group_brokerage_crm_user"
                ).id,
            ])],
        })
        cls.lead = cls.env["crm.lead"].create({
            "name": "Timed Reminder Lead",
            "assignment_type": "manual",
            "user_id": cls.user.id,
        })
        cls.activity_type = cls.env.ref("mail.mail_activity_data_todo")
        cls.model_id = cls.env["ir.model"]._get_id("crm.lead")

    def _create_activity(self, reminder_datetime, summary="Call customer"):
        return self.env["mail.activity"].create({
            "activity_type_id": self.activity_type.id,
            "brokerage_reminder_datetime": reminder_datetime,
            "res_id": self.lead.id,
            "res_model_id": self.model_id,
            "summary": summary,
            "user_id": self.user.id,
        })

    def test_due_reminder_sends_one_odoo_notification_only(self):
        activity = self._create_activity(
            fields.Datetime.now() - timedelta(minutes=1)
        )
        email_count = self.env["mail.mail"].sudo().search_count([])
        queued_email_count = self.env[
            "brokerage.crm.email.notification"
        ].sudo().search_count([])
        whatsapp_count = self.env[
            "brokerage.whatsapp.notification"
        ].sudo().search_count([])

        self.env["mail.activity"]._cron_send_brokerage_timed_reminders()
        activity.invalidate_recordset()

        self.assertTrue(activity.brokerage_reminder_sent_at)
        self.assertTrue(activity.brokerage_reminder_message_id)
        self.assertEqual(
            activity.brokerage_reminder_message_id.message_type,
            "user_notification",
        )
        self.assertIn(
            self.user.partner_id,
            activity.brokerage_reminder_message_id.partner_ids,
        )
        inbox_notification = self.env["mail.notification"].sudo().search([
            (
                "mail_message_id",
                "=",
                activity.brokerage_reminder_message_id.id,
            ),
            ("res_partner_id", "=", self.user.partner_id.id),
            ("notification_type", "=", "inbox"),
        ])
        self.assertEqual(len(inbox_notification), 1)
        self.assertEqual(
            self.env["mail.mail"].sudo().search_count([]),
            email_count,
        )
        self.assertEqual(
            self.env[
                "brokerage.crm.email.notification"
            ].sudo().search_count([]),
            queued_email_count,
        )
        self.assertEqual(
            self.env[
                "brokerage.whatsapp.notification"
            ].sudo().search_count([]),
            whatsapp_count,
        )

        original_message = activity.brokerage_reminder_message_id
        self.env["mail.activity"]._cron_send_brokerage_timed_reminders()
        activity.invalidate_recordset()
        self.assertEqual(
            activity.brokerage_reminder_message_id,
            original_message,
        )
        self.assertEqual(
            self.env["mail.message"].sudo().search_count([
                ("id", "=", original_message.id),
            ]),
            1,
        )

    def test_future_and_completed_activities_are_not_notified(self):
        future_activity = self._create_activity(
            fields.Datetime.now() + timedelta(hours=1),
            summary="Future call",
        )
        completed_activity = self._create_activity(
            fields.Datetime.now() - timedelta(minutes=1),
            summary="Completed call",
        )
        completed_activity.active = False

        self.env["mail.activity"]._cron_send_brokerage_timed_reminders()
        (future_activity | completed_activity).invalidate_recordset()

        self.assertFalse(future_activity.brokerage_reminder_sent_at)
        self.assertFalse(completed_activity.brokerage_reminder_sent_at)

    def test_reminder_datetime_uses_assigned_user_timezone(self):
        # 20:30 UTC is 00:30 the next day in Asia/Dubai.
        reminder_datetime = datetime(2026, 8, 7, 20, 30)
        activity = self._create_activity(reminder_datetime)

        self.assertEqual(
            activity.date_deadline,
            fields.Date.to_date("2026-08-08"),
        )
        with self.assertRaises(ValidationError):
            activity.date_deadline = fields.Date.to_date("2026-08-07")

    def test_rescheduling_resets_delivery_marker(self):
        activity = self._create_activity(
            fields.Datetime.now() - timedelta(minutes=1)
        )
        activity._send_brokerage_timed_reminder()
        self.assertTrue(activity.brokerage_reminder_sent_at)

        new_datetime = fields.Datetime.now() + timedelta(days=1)
        activity.brokerage_reminder_datetime = new_datetime

        self.assertFalse(activity.brokerage_reminder_sent_at)
        self.assertFalse(activity.brokerage_reminder_message_id)
        expected_local_date = fields.Datetime.context_timestamp(
            activity.with_context(tz=self.user.tz),
            new_datetime,
        ).date()
        self.assertEqual(activity.date_deadline, expected_local_date)

    def test_reassignment_recalculates_due_date_for_new_timezone(self):
        other_user = self.env["res.users"].create({
            "name": "UTC Reminder Agent",
            "login": "utc.reminder.agent@test.invalid",
            "tz": "UTC",
            "group_ids": [Command.set([
                self.env.ref("base.group_user").id,
                self.env.ref(
                    "brokerage_crm.group_brokerage_crm_user"
                ).id,
            ])],
        })
        activity = self._create_activity(datetime(2026, 8, 7, 20, 30))
        self.assertEqual(
            activity.date_deadline,
            fields.Date.to_date("2026-08-08"),
        )

        activity.user_id = other_user

        self.assertEqual(
            activity.date_deadline,
            fields.Date.to_date("2026-08-07"),
        )

    def test_create_wizard_propagates_due_datetime(self):
        reminder_datetime = datetime(2026, 8, 7, 12, 0)
        scheduler = self.env["mail.activity.schedule"].with_context(
            active_model="crm.lead",
            active_ids=[self.lead.id],
            active_id=self.lead.id,
        ).create({
            "activity_type_id": self.activity_type.id,
            "activity_user_id": self.user.id,
            "brokerage_reminder_datetime": reminder_datetime,
            "summary": "Wizard timed call",
        })

        activity = scheduler._action_schedule_activities()

        self.assertEqual(
            activity.brokerage_reminder_datetime,
            reminder_datetime,
        )
        self.assertEqual(
            activity.date_deadline,
            fields.Date.to_date("2026-08-07"),
        )

    def test_create_and_edit_forms_show_one_labelled_datetime(self):
        views = [
            self.env["mail.activity"].get_view(view_type="form"),
            self.env["mail.activity.schedule"].get_view(view_type="form"),
        ]
        for view in views:
            root = etree.fromstring(view["arch"])
            due_date = root.xpath("//field[@name='date_deadline']")
            reminder = root.xpath(
                "//field[@name='brokerage_reminder_datetime']"
            )
            reminder_label = root.xpath(
                "//label[@for='brokerage_reminder_datetime']"
            )
            self.assertEqual(len(due_date), 1)
            self.assertEqual(due_date[0].get("invisible"), "1")
            self.assertEqual(len(reminder), 1)
            self.assertEqual(len(reminder_label), 1)
            self.assertEqual(
                reminder_label[0].get("string"),
                "Due Date & Time",
            )
