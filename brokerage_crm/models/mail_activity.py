import logging

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import format_datetime


_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def _notify_get_recipients(self, message, msg_vals=False, **kwargs):
        recipients = super()._notify_get_recipients(
            message,
            msg_vals,
            **kwargs,
        )
        if self.env.context.get("brokerage_odoo_only_notification"):
            for recipient in recipients:
                if recipient.get("uid") and not recipient.get("ushare"):
                    recipient["notif"] = "inbox"
        return recipients


class MailActivity(models.Model):
    _inherit = "mail.activity"

    brokerage_reminder_datetime = fields.Datetime(
        string="Reminder Date & Time",
        index=True,
        copy=False,
        help=(
            "Optional exact time for an Odoo reminder. The standard Due Date "
            "continues to control the normal activity status and reporting."
        ),
    )
    brokerage_reminder_sent_at = fields.Datetime(
        string="Timed Reminder Sent At",
        readonly=True,
        copy=False,
        index=True,
    )
    brokerage_reminder_message_id = fields.Many2one(
        comodel_name="mail.message",
        string="Timed Reminder Notification",
        readonly=True,
        copy=False,
        ondelete="set null",
        help="The single Odoo notification created for this timed reminder.",
    )

    @api.onchange("brokerage_reminder_datetime")
    def _onchange_brokerage_reminder_datetime(self):
        for activity in self:
            if activity.brokerage_reminder_datetime:
                local_datetime = fields.Datetime.context_timestamp(
                    activity,
                    activity.brokerage_reminder_datetime,
                )
                activity.date_deadline = local_datetime.date()

    @api.constrains(
        "brokerage_reminder_datetime",
        "date_deadline",
        "user_id",
    )
    def _check_brokerage_reminder_matches_due_date(self):
        for activity in self:
            if not activity.brokerage_reminder_datetime:
                continue
            local_datetime = fields.Datetime.context_timestamp(
                activity.with_context(tz=activity.user_id.tz),
                activity.brokerage_reminder_datetime,
            )
            if local_datetime.date() != activity.date_deadline:
                raise ValidationError(_(
                    "The Reminder Date & Time must be on the activity Due Date."
                ))

    @api.model_create_multi
    def create(self, vals_list):
        prepared_values = []
        for values in vals_list:
            values = dict(values)
            reminder_datetime = values.get("brokerage_reminder_datetime")
            if reminder_datetime:
                reminder_datetime = fields.Datetime.to_datetime(
                    reminder_datetime
                )
                user = self.env["res.users"].browse(
                    values.get("user_id") or self.env.uid
                )
                local_datetime = fields.Datetime.context_timestamp(
                    self.with_context(tz=user.tz),
                    reminder_datetime,
                )
                values["date_deadline"] = local_datetime.date()
            prepared_values.append(values)
        return super().create(prepared_values)

    def write(self, values):
        values = dict(values)
        timezone_sensitive_update = (
            "brokerage_reminder_datetime" in values
            or (
                "user_id" in values
                and any(self.mapped("brokerage_reminder_datetime"))
            )
        )
        if timezone_sensitive_update and len(self) > 1:
            for activity in self:
                activity.write(values)
            return True
        if "brokerage_reminder_datetime" in values:
            new_datetime = fields.Datetime.to_datetime(
                values.get("brokerage_reminder_datetime")
            )
            if any(
                activity.brokerage_reminder_datetime != new_datetime
                for activity in self
            ):
                values.update({
                    "brokerage_reminder_sent_at": False,
                    "brokerage_reminder_message_id": False,
                })
            if new_datetime and len(self) == 1:
                user = self.env["res.users"].browse(
                    values.get("user_id") or self.user_id.id
                )
                local_datetime = fields.Datetime.context_timestamp(
                    self.with_context(tz=user.tz),
                    new_datetime,
                )
                values["date_deadline"] = local_datetime.date()
        elif "user_id" in values and self.brokerage_reminder_datetime:
            user = self.env["res.users"].browse(values["user_id"])
            local_datetime = fields.Datetime.context_timestamp(
                self.with_context(tz=user.tz),
                self.brokerage_reminder_datetime,
            )
            values["date_deadline"] = local_datetime.date()
        return super().write(values)

    def _send_brokerage_timed_reminder(self):
        """Send one persistent Odoo-only reminder for each due activity."""
        for activity in self.sudo():
            if (
                not activity.active
                or not activity.brokerage_reminder_datetime
                or activity.brokerage_reminder_sent_at
                or activity.brokerage_reminder_datetime > fields.Datetime.now()
            ):
                continue

            user = activity.user_id.sudo()
            if not user or not user.active or user.share:
                continue

            reminder_label = format_datetime(
                self.env,
                activity.brokerage_reminder_datetime,
                tz=user.tz or self.env.company.partner_id.tz or "UTC",
                lang_code=user.lang,
            )
            record_name = activity.res_name or _("Related Record")
            subject = _("Activity Reminder: %s") % (
                activity.summary or activity.activity_type_id.display_name
            )
            body = Markup(
                "<p><b>%(heading)s</b></p>"
                "<p>%(activity_label)s: %(activity)s<br/>"
                "%(record_label)s: %(record)s<br/>"
                "%(due_label)s: %(due)s</p>"
                "<p>%(instruction)s</p>"
            ) % {
                "heading": _("CRM Activity Reminder"),
                "activity_label": _("Activity"),
                "activity": (
                    activity.summary or activity.activity_type_id.display_name
                ),
                "record_label": _("Record"),
                "record": record_name,
                "due_label": _("Reminder time"),
                "due": reminder_label,
                "instruction": _(
                    "Open the record and complete or reschedule the activity."
                ),
            }
            message = self.env["mail.thread"].sudo().with_context(
                brokerage_odoo_only_notification=True,
            ).message_notify(
                partner_ids=user.partner_id.ids,
                author_id=self.env.user.partner_id.id,
                body=body,
                subject=subject,
                model=activity.res_model,
                res_id=activity.res_id,
                model_description=activity.res_model_id.name,
                force_record_name=record_name,
                notify_author=True,
                notify_skip_followers=True,
                skip_existing=True,
            )
            if message:
                activity.write({
                    "brokerage_reminder_message_id": message.id,
                    "brokerage_reminder_sent_at": fields.Datetime.now(),
                })
        return True

    @api.model
    def _cron_send_brokerage_timed_reminders(self, limit=200):
        """Claim due rows safely so parallel cron workers cannot duplicate them."""
        self.env.cr.execute(
            """
                SELECT id
                  FROM mail_activity
                 WHERE active IS TRUE
                   AND brokerage_reminder_datetime IS NOT NULL
                   AND brokerage_reminder_datetime <= %s
                   AND brokerage_reminder_sent_at IS NULL
                 ORDER BY brokerage_reminder_datetime, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT %s
            """,
            [fields.Datetime.now(), limit],
        )
        activity_ids = [row[0] for row in self.env.cr.fetchall()]
        for activity in self.sudo().browse(activity_ids):
            try:
                with self.env.cr.savepoint():
                    activity._send_brokerage_timed_reminder()
            except Exception:
                _logger.exception(
                    "Could not send timed Odoo reminder for activity %s",
                    activity.id,
                )
        return len(activity_ids)


class MailActivitySchedule(models.TransientModel):
    _inherit = "mail.activity.schedule"

    brokerage_reminder_datetime = fields.Datetime(
        string="Due Date & Time",
        help=(
            "Select the activity deadline and the exact time for its Odoo "
            "reminder."
        ),
    )

    @api.onchange("brokerage_reminder_datetime", "activity_user_id")
    def _onchange_brokerage_reminder_datetime(self):
        for scheduler in self:
            if scheduler.brokerage_reminder_datetime:
                local_datetime = fields.Datetime.context_timestamp(
                    scheduler.with_context(
                        tz=scheduler.activity_user_id.tz,
                    ),
                    scheduler.brokerage_reminder_datetime,
                )
                scheduler.date_deadline = local_datetime.date()

    def _action_schedule_activities(self):
        self.ensure_one()
        if not self.res_model:
            return self._action_schedule_activities_personal()
        return self._get_applied_on_records().activity_schedule(
            activity_type_id=self.activity_type_id.id,
            automated=False,
            summary=self.summary,
            note=self.note,
            user_id=self.activity_user_id.id,
            date_deadline=self.date_deadline,
            brokerage_reminder_datetime=(
                self.brokerage_reminder_datetime
            ),
        )

    def _action_schedule_activities_personal(self):
        self.ensure_one()
        if not self.activity_user_id:
            raise ValidationError(_(
                "Scheduling personal activities requires an assigned user."
            ))
        return self.env["mail.activity"].create({
            "activity_type_id": self.activity_type_id.id,
            "automated": False,
            "brokerage_reminder_datetime": (
                self.brokerage_reminder_datetime
            ),
            "date_deadline": self.date_deadline,
            "note": self.note,
            "res_id": False,
            "res_model_id": False,
            "summary": self.summary,
            "user_id": self.activity_user_id.id,
        })
