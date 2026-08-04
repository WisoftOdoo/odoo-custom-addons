from datetime import timedelta
from unittest.mock import Mock, patch

from odoo import fields
from odoo.tests.common import TransactionCase


class TestBrokerageWhatsApp(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["brokerage.crm.round.robin"].search([]).write({
            "active": False,
        })
        cls.env["brokerage.crm.sla.rule"].search([]).write({
            "active": False,
        })
        parameters = cls.env["ir.config_parameter"].sudo()
        parameters.set_param("brokerage_crm.ultramsg_enabled", "True")
        parameters.set_param(
            "brokerage_crm.ultramsg_instance_id", "instance123456"
        )
        parameters.set_param("brokerage_crm.ultramsg_token", "test-token")
        parameters.set_param(
            "brokerage_crm.ultramsg_default_country_code", "971"
        )
        parameters.set_param("brokerage_crm.ultramsg_max_attempts", "3")
        parameters.set_param(
            "brokerage_crm.ultramsg_retry_base_minutes", "5"
        )
        parameters.set_param(
            "brokerage_crm.ultramsg_retry_max_minutes", "60"
        )
        always_open = cls.env["resource.calendar"].create({
            "name": "WhatsApp Tests 24/7",
            "tz": "UTC",
            "attendance_ids": [
                (0, 0, {
                    "name": "Open",
                    "dayofweek": str(day),
                    "hour_from": 0,
                    "hour_to": 24,
                })
                for day in range(7)
            ],
        })
        cls.env.company.resource_calendar_id = always_open

        manager_group = cls.env.ref(
            "brokerage_crm.group_brokerage_sales_manager"
        )
        cls.agent = cls.env["res.users"].create({
            "name": "WhatsApp Agent",
            "login": "whatsapp.agent@test.invalid",
        })
        cls.agent.partner_id.phone = "050 123 4567"
        cls.manager = cls.env["res.users"].create({
            "name": "WhatsApp Manager",
            "login": "whatsapp.manager@test.invalid",
            "group_ids": [(6, 0, [manager_group.id])],
        })
        cls.manager.partner_id.phone = "+971 55 987 6543"
        cls.team = cls.env["crm.team"].create({
            "name": "WhatsApp Team",
            "user_id": cls.manager.id,
        })
        cls.assigned_stage = cls.env["crm.stage"].create({
            "name": "Assigned WhatsApp Test",
            "brokerage_code": "assigned",
            "team_ids": [(6, 0, [cls.team.id])],
        })
        cls.round_robin = cls.env[
            "brokerage.crm.round.robin"
        ].create({
            "name": "WhatsApp Queue",
            "team_id": cls.team.id,
            "member_ids": [(6, 0, [cls.agent.id])],
        })

    def test_round_robin_assignment_is_queued_and_sent(self):
        lead = self.env["crm.lead"].create({
            "name": "WhatsApp Assignment Lead",
            "type": "opportunity",
        })

        self.round_robin.assign_lead(lead)

        notification = self.env[
            "brokerage.whatsapp.notification"
        ].search([
            ("lead_id", "=", lead.id),
            ("notification_type", "=", "assignment"),
        ])
        self.assertEqual(len(notification), 1)
        self.assertEqual(notification.state, "pending")
        self.assertEqual(notification.recipient_user_id, self.agent)
        self.assertEqual(notification.recipient_phone, "+971501234567")

        response = Mock(
            ok=True,
            status_code=200,
            text='{"sent":"true","message":"ok","id":42}',
        )
        response.json.return_value = {
            "sent": "true",
            "message": "ok",
            "id": 42,
        }
        with patch(
            "odoo.addons.brokerage_crm.models.whatsapp_notification."
            "requests.post",
            return_value=response,
        ) as request_post:
            self.env[
                "brokerage.whatsapp.notification"
            ].with_context(
                allow_ultramsg_request=True
            )._cron_process_pending()

        notification.invalidate_recordset()
        self.assertEqual(notification.state, "sent")
        self.assertEqual(notification.external_message_id, "42")
        self.assertEqual(notification.retry_cycle_attempt_count, 1)
        payload = request_post.call_args.kwargs["data"]
        self.assertEqual(payload["to"], "+971501234567")
        self.assertIn("WhatsApp Assignment Lead", payload["body"])

    def test_missing_user_phone_is_skipped(self):
        user_without_phone = self.env["res.users"].create({
            "name": "Agent Without Phone",
            "login": "agent.without.phone@test.invalid",
        })
        user_without_phone.partner_id.write({
            "phone": False,
        })
        lead = self.env["crm.lead"].create({
            "name": "No Phone Lead",
            "type": "opportunity",
        })

        notification = self.env[
            "brokerage.whatsapp.notification"
        ].queue_assignment(lead, user_without_phone)

        self.assertEqual(notification.state, "skipped")
        self.assertFalse(notification.recipient_phone)
        self.assertEqual(notification.attempt_count, 0)

    def test_exponential_retry_terminal_alert_and_manual_retry(self):
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param(
            "brokerage_crm.ultramsg_failure_alert_user_id",
            str(self.manager.id),
        )
        lead = self.env["crm.lead"].create({
            "name": "WhatsApp Retry Lead",
            "type": "opportunity",
            "team_id": self.team.id,
            "user_id": self.agent.id,
        })
        notification = self.env[
            "brokerage.whatsapp.notification"
        ].queue_assignment(lead, self.agent)

        before_first_failure = fields.Datetime.now()
        notification._mark_failed("Network timeout 1", 3)
        first_retry_at = notification.next_attempt_at
        self.assertEqual(notification.retry_cycle_attempt_count, 1)
        self.assertGreaterEqual(
            first_retry_at,
            before_first_failure + timedelta(minutes=5),
        )

        notification._mark_failed("Network timeout 2", 3)
        second_retry_at = notification.next_attempt_at
        self.assertEqual(notification.retry_cycle_attempt_count, 2)
        self.assertGreaterEqual(
            second_retry_at,
            fields.Datetime.now() + timedelta(minutes=10),
        )

        notification._mark_failed("Network timeout 3", 3)
        self.assertEqual(notification.state, "failed")
        self.assertEqual(notification.attempt_count, 3)
        self.assertEqual(notification.retry_cycle_attempt_count, 3)
        self.assertFalse(notification.next_attempt_at)
        self.assertTrue(notification.failure_alerted_at)
        self.assertEqual(notification.failure_alert_user_id, self.manager)
        self.assertEqual(
            self.env["mail.activity"].search_count([
                ("res_model", "=", "crm.lead"),
                ("res_id", "=", lead.id),
                ("summary", "=", "WhatsApp delivery failed"),
                ("user_id", "=", self.manager.id),
            ]),
            1,
        )

        notification.with_user(self.manager).action_retry_now()
        notification.invalidate_recordset()
        self.assertEqual(notification.state, "pending")
        self.assertEqual(notification.attempt_count, 3)
        self.assertEqual(notification.retry_cycle_attempt_count, 0)
        self.assertEqual(notification.manual_retry_count, 1)
        self.assertFalse(notification.failure_alerted_at)

    def test_sla_escalation_is_queued_for_team_manager(self):
        rule = self.env["brokerage.crm.sla.rule"].create({
            "name": "WhatsApp Manager Escalation",
            "rule_type": "first_contact",
            "team_id": self.team.id,
            "duration_minutes": 60,
            "reminder_1_minutes": 0,
            "reminder_2_minutes": 0,
            "reminder_3_minutes": 0,
            "escalation_minutes": 15,
            "reassignment_minutes": 0,
            "activity_type_id": self.env.ref(
                "brokerage_crm.mail_activity_type_call_customer"
            ).id,
        })
        lead = self.env["crm.lead"].create({
            "name": "WhatsApp Escalation Lead",
            "type": "opportunity",
            "team_id": self.team.id,
            "user_id": self.agent.id,
            "stage_id": self.assigned_stage.id,
        })
        assignment_datetime = (
            fields.Datetime.now() - timedelta(minutes=16)
        )
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
        ).write({
            "assignment_type": "round_robin",
            "assigned_datetime": assignment_datetime,
            "sla_cycle_active": True,
        })

        self.env["crm.lead"]._cron_check_brokerage_sla()

        notification = self.env[
            "brokerage.whatsapp.notification"
        ].search([
            ("lead_id", "=", lead.id),
            (
                "notification_type",
                "=",
                "team_leader_escalation",
            ),
        ])
        self.assertEqual(len(notification), 1)
        self.assertEqual(notification.recipient_user_id, self.manager)
        self.assertEqual(notification.recipient_phone, "+971559876543")
        self.assertIn("15 minutes", notification.body)
        self.assertEqual(
            self.env["brokerage.crm.sla.log"].search_count([
                ("lead_id", "=", lead.id),
                ("rule_id", "=", rule.id),
                ("event_type", "=", "team_leader_escalation"),
            ]),
            1,
        )
        # The SLA activity itself is the single Odoo app notification. A
        # second custom notification would create duplicate alerts.
        self.assertEqual(
            self.env["mail.message"].sudo().search_count([
                ("model", "=", "crm.lead"),
                ("res_id", "=", lead.id),
                ("message_type", "=", "user_notification"),
                ("partner_ids", "in", self.manager.partner_id.id),
            ]),
            1,
        )
