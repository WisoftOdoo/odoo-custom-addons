import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import email_normalize


_logger = logging.getLogger(__name__)


class BrokerageCrmEmailNotification(models.Model):
    _name = "brokerage.crm.email.notification"
    _description = "Brokerage CRM Email Notification"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, readonly=True)
    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        required=True,
        readonly=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="lead_id.company_id",
        store=True,
        readonly=True,
    )
    recipient_user_id = fields.Many2one(
        comodel_name="res.users",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
    )
    recipient_email = fields.Char(readonly=True)
    notification_type = fields.Selection(
        selection=[
            ("assignment", "New Lead Assignment"),
            ("reassignment", "Lead Reassignment"),
            ("repeat_enquiry", "Repeat Enquiry"),
            ("reminder_1", "SLA Reminder 1"),
            ("reminder_2", "SLA Reminder 2"),
            ("reminder_3", "SLA Reminder 3"),
            ("escalation", "SLA Escalation"),
            (
                "team_leader_escalation",
                "SLA Team Leader Escalation",
            ),
            (
                "manager_escalation",
                "Legacy SLA Manager Escalation",
            ),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    event_label = fields.Char(required=True, readonly=True)
    subject = fields.Char(required=True, readonly=True)
    reason = fields.Text(readonly=True)
    elapsed_minutes = fields.Integer(readonly=True)
    lead_url = fields.Char(readonly=True)
    deduplication_key = fields.Char(
        required=True,
        readonly=True,
        copy=False,
        index=True,
    )
    assignment_history_id = fields.Many2one(
        comodel_name="brokerage.crm.assignment.history",
        readonly=True,
        ondelete="cascade",
        index=True,
    )
    sla_log_id = fields.Many2one(
        comodel_name="brokerage.crm.sla.log",
        readonly=True,
        ondelete="cascade",
        index=True,
    )
    mail_id = fields.Many2one(
        comodel_name="mail.mail",
        string="Queued Email",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("queued", "Queued"),
            ("sent", "Sent"),
            ("failed", "Failed"),
            ("skipped", "Skipped"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="pending",
        readonly=True,
        index=True,
    )
    manual_retry_count = fields.Integer(readonly=True, default=0)
    queued_at = fields.Datetime(readonly=True)
    sent_at = fields.Datetime(readonly=True)
    failure_reason = fields.Text(readonly=True)

    _deduplication_key_unique = models.Constraint(
        "UNIQUE(deduplication_key)",
        "This email notification has already been queued.",
    )

    @api.model
    def _lead_url(self, lead):
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url", ""
        ).rstrip("/")
        return (
            "%s/web#id=%s&model=crm.lead&view_type=form"
            % (base_url, lead.id)
        )

    @api.model
    def queue_assignment(self, history):
        history.ensure_one()
        is_reassignment = history.assignment_type in (
            "reassignment",
            "not_interested_reassignment",
            "recovery",
        )
        notification_type = (
            "reassignment" if is_reassignment else "assignment"
        )
        label = (
            _("CRM Lead Reassigned")
            if is_reassignment
            else _("New CRM Lead Assigned")
        )
        return self._queue_notification(
            lead=history.lead_id,
            user=history.new_user_id,
            notification_type=notification_type,
            event_label=label,
            subject="%s: %s" % (label, history.lead_id.display_name),
            reason=history.reason,
            deduplication_key="assignment-history:%s:%s" % (
                history.id,
                history.new_user_id.id,
            ),
            assignment_history=history,
        )

    @api.model
    def queue_repeat_enquiry(self, lead, user, event_key, action_text):
        lead.ensure_one()
        user.ensure_one()
        label = _("Repeat CRM Enquiry")
        return self._queue_notification(
            lead=lead,
            user=user,
            notification_type="repeat_enquiry",
            event_label=label,
            subject="%s: %s" % (label, lead.display_name),
            reason=str(action_text),
            deduplication_key=event_key,
        )

    @api.model
    def queue_sla(self, sla_log, user, minutes):
        sla_log.ensure_one()
        user.ensure_one()
        labels = {
            "reminder_1": _("CRM SLA Reminder 1"),
            "reminder_2": _("CRM SLA Reminder 2"),
            "reminder_3": _("CRM SLA Reminder 3"),
            "escalation": _("CRM SLA Escalation"),
            "team_leader_escalation": _(
                "CRM SLA Team Leader Escalation"
            ),
            "manager_escalation": _(
                "Legacy CRM SLA Manager Escalation"
            ),
        }
        label = labels.get(sla_log.event_type)
        if not label:
            return self.browse()
        assignment_key = fields.Datetime.to_string(
            sla_log.assignment_datetime
        )
        return self._queue_notification(
            lead=sla_log.lead_id,
            user=user,
            notification_type=sla_log.event_type,
            event_label=label,
            subject="%s: %s" % (label, sla_log.lead_id.display_name),
            reason=_(
                "No qualifying action was recorded within %s minutes."
            ) % minutes,
            minutes=minutes,
            deduplication_key="sla:%s:%s:%s:%s:%s" % (
                sla_log.lead_id.id,
                sla_log.rule_id.id,
                assignment_key,
                sla_log.event_type,
                user.id,
            ),
            sla_log=sla_log,
        )

    @api.model
    def _queue_notification(
        self,
        lead,
        user,
        notification_type,
        event_label,
        subject,
        deduplication_key,
        reason=None,
        minutes=0,
        assignment_history=None,
        sla_log=None,
    ):
        lead.ensure_one()
        user.ensure_one()
        existing = self.sudo().search([
            ("deduplication_key", "=", deduplication_key),
        ], limit=1)
        if existing:
            return existing

        raw_email = user.sudo().partner_id.email or ""
        recipient_email = email_normalize(raw_email, strict=False)
        values = {
            "name": "%s - %s" % (event_label, lead.display_name),
            "lead_id": lead.id,
            "recipient_user_id": user.id,
            "recipient_email": recipient_email or False,
            "notification_type": notification_type,
            "event_label": event_label,
            "subject": subject,
            "reason": reason or False,
            "elapsed_minutes": int(minutes or 0),
            "lead_url": self._lead_url(lead),
            "deduplication_key": deduplication_key,
            "assignment_history_id": (
                assignment_history.id if assignment_history else False
            ),
            "sla_log_id": sla_log.id if sla_log else False,
            "state": "pending" if recipient_email else "skipped",
            "failure_reason": (
                False
                if recipient_email
                else _("The recipient has no valid email address.")
            ),
        }
        notification = self.sudo().create(values)
        if recipient_email:
            notification._queue_mail()
        return notification

    def _queue_mail(self):
        self.ensure_one()
        template = self.env.ref(
            "brokerage_crm.email_template_crm_notification",
            raise_if_not_found=False,
        )
        if not template:
            self.sudo().write({
                "state": "failed",
                "failure_reason": _(
                    "The Brokerage CRM email template is missing."
                ),
            })
            return False
        try:
            with self.env.cr.savepoint():
                mail_id = template.sudo().send_mail(
                    self.id,
                    force_send=False,
                    raise_exception=True,
                    email_values={
                        "email_to": self.recipient_email,
                        "recipient_ids": [(6, 0, [])],
                    },
                )
        except Exception as error:
            _logger.exception(
                "Could not queue Brokerage CRM email notification %s",
                self.id,
            )
            self.sudo().write({
                "state": "failed",
                "failure_reason": str(error)[:2000],
            })
            return False

        self.sudo().write({
            "mail_id": mail_id,
            "state": "queued",
            "queued_at": fields.Datetime.now(),
            "sent_at": False,
            "failure_reason": False,
        })
        cron = self.env.ref(
            "mail.ir_cron_mail_scheduler_action",
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()
        return True

    @api.model
    def _cron_sync_states(self):
        notifications = self.sudo().search([
            ("state", "in", ("queued", "failed")),
            ("mail_id", "!=", False),
        ])
        state_map = {
            "outgoing": "queued",
            "sent": "sent",
            "exception": "failed",
            "cancel": "cancelled",
        }
        for notification in notifications:
            mail_state = notification.mail_id.state
            new_state = state_map.get(mail_state, notification.state)
            values = {}
            if new_state != notification.state:
                values["state"] = new_state
            if new_state == "sent" and not notification.sent_at:
                values["sent_at"] = fields.Datetime.now()
            if new_state == "failed":
                values["failure_reason"] = (
                    notification.mail_id.failure_reason
                    or _("The outgoing mail server rejected the email.")
                )
            if values:
                notification.write(values)
        return True

    def action_retry_now(self):
        if not self.env.user.has_group(
            "brokerage_crm.group_brokerage_sales_manager"
        ):
            raise AccessError(_(
                "Only a Brokerage Configuration Manager can retry email "
                "delivery."
            ))
        for notification in self:
            if notification.state not in (
                "failed", "skipped", "cancelled"
            ):
                raise ValidationError(_(
                    "Only failed, skipped, or cancelled emails can be "
                    "retried."
                ))
            recipient_email = email_normalize(
                notification.recipient_user_id.sudo().partner_id.email or "",
                strict=False,
            )
            if not recipient_email:
                raise ValidationError(_(
                    "The recipient still has no valid email address."
                ))
            notification.sudo().write({
                "recipient_email": recipient_email,
                "state": "pending",
                "mail_id": False,
                "manual_retry_count": notification.manual_retry_count + 1,
                "failure_reason": False,
                "sent_at": False,
            })
            notification._queue_mail()
        return True
