import json
import logging
import re
from datetime import timedelta

import requests

from odoo import api, fields, models, modules, _
from odoo.exceptions import AccessError, ValidationError


_logger = logging.getLogger(__name__)


class BrokerageWhatsAppNotification(models.Model):
    _name = "brokerage.whatsapp.notification"
    _description = "Brokerage WhatsApp Notification"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, readonly=True)
    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        required=True,
        readonly=True,
        ondelete="cascade",
        index=True,
    )
    recipient_user_id = fields.Many2one(
        comodel_name="res.users",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
    )
    recipient_phone = fields.Char(readonly=True)
    notification_type = fields.Selection(
        selection=[
            ("assignment", "Lead Assignment"),
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
    body = fields.Text(required=True, readonly=True)
    deduplication_key = fields.Char(
        required=True,
        readonly=True,
        copy=False,
        index=True,
    )
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("sent", "Sent"),
            ("failed", "Failed"),
            ("skipped", "Skipped"),
        ],
        required=True,
        default="pending",
        readonly=True,
        index=True,
    )
    attempt_count = fields.Integer(default=0, readonly=True)
    retry_cycle_attempt_count = fields.Integer(
        string="Attempts in Current Retry Cycle",
        default=0,
        readonly=True,
    )
    manual_retry_count = fields.Integer(
        string="Manual Retries",
        default=0,
        readonly=True,
    )
    next_attempt_at = fields.Datetime(readonly=True, index=True)
    last_attempt_at = fields.Datetime(readonly=True)
    sent_at = fields.Datetime(readonly=True)
    http_status = fields.Integer(readonly=True)
    external_message_id = fields.Char(readonly=True)
    response_message = fields.Text(readonly=True)
    failure_alerted_at = fields.Datetime(readonly=True, copy=False)
    failure_alert_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Failure Alerted To",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    _deduplication_key_unique = models.Constraint(
        "UNIQUE(deduplication_key)",
        "This WhatsApp notification has already been queued.",
    )

    @api.model
    def _get_parameter(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(
            "brokerage_crm.%s" % key,
            default,
        )

    @api.model
    def _is_enabled(self):
        return str(self._get_parameter(
            "ultramsg_enabled", "False"
        )).lower() in ("true", "1", "yes")

    @api.model
    def _normalize_phone(self, phone):
        if not phone:
            return False
        raw = str(phone).strip()
        digits = re.sub(r"\D", "", raw)
        if raw.startswith("00"):
            digits = digits[2:]
        elif raw.startswith("0"):
            country_code = re.sub(
                r"\D",
                "",
                self._get_parameter(
                    "ultramsg_default_country_code", "971"
                ),
            )
            digits = country_code + digits.lstrip("0")
        if not 8 <= len(digits) <= 15:
            return False
        return "+%s" % digits

    @api.model
    def _phone_for_user(self, user):
        user.ensure_one()
        partner = user.sudo().partner_id
        mobile = partner["mobile"] if "mobile" in partner._fields else False
        return self._normalize_phone(mobile or partner.phone)

    @api.model
    def _lead_lines(self, lead):
        lead = lead.sudo()
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url", ""
        ).rstrip("/")
        customer = lead.contact_name or lead.partner_id.display_name or "-"
        source = lead.source_id.display_name or "-"
        return [
            _("Lead: %s") % lead.display_name,
            _("Customer: %s") % customer,
            _("Customer phone: %s") % (lead.phone or "-"),
            _("Customer email: %s") % (lead.email_from or "-"),
            _("Source: %s") % source,
            _("Sales team: %s") % (lead.team_id.display_name or "-"),
            _("Salesperson: %s") % (lead.user_id.display_name or "-"),
            _("Open in Odoo: %s/web#id=%s&model=crm.lead&view_type=form")
            % (base_url, lead.id),
        ]

    @api.model
    def queue_assignment(self, lead, user, reason=None):
        lead.ensure_one()
        user.ensure_one()
        if not self._is_enabled():
            return self.browse()
        body = "\n".join([
            _("*New CRM Lead Assigned*"),
            *(self._lead_lines(lead)),
            _("Assignment reason: %s") % (reason or _("Automatic assignment")),
            _("Please contact the customer and update the CRM stage."),
        ])
        assignment_key = fields.Datetime.to_string(
            lead.assigned_datetime or fields.Datetime.now()
        )
        return self._queue_notification(
            lead=lead,
            user=user,
            notification_type="assignment",
            body=body,
            deduplication_key=(
                "assignment:%s:%s:%s"
                % (lead.id, assignment_key, user.id)
            ),
        )

    @api.model
    def queue_repeat_enquiry(self, lead, user, event_key, action_text):
        lead.ensure_one()
        user.ensure_one()
        if not self._is_enabled():
            return self.browse()
        body = "\n".join([
            _("*Repeat CRM Enquiry*"),
            *(self._lead_lines(lead)),
            str(action_text),
            _("Please open the existing lead and review the new enquiry."),
        ])
        return self._queue_notification(
            lead=lead,
            user=user,
            notification_type="repeat_enquiry",
            body=body,
            deduplication_key=event_key,
        )

    @api.model
    def queue_sla(
        self,
        lead,
        user,
        event_type,
        minutes,
        rule,
        assignment_datetime,
    ):
        lead.ensure_one()
        user.ensure_one()
        rule.ensure_one()
        if not self._is_enabled():
            return self.browse()
        title = {
            "reminder_1": _("CRM SLA Reminder 1"),
            "reminder_2": _("CRM SLA Reminder 2"),
            "reminder_3": _("CRM SLA Reminder 3"),
            "escalation": _("CRM SLA Manager Escalation"),
            "team_leader_escalation": _(
                "CRM SLA Team Leader Escalation"
            ),
            "manager_escalation": _(
                "Legacy CRM SLA Manager Escalation"
            ),
        }[event_type]
        body = "\n".join([
            "*%s*" % title,
            *(self._lead_lines(lead)),
            _("No qualifying action was recorded within %s minutes.")
            % minutes,
            _("Please open the lead and update its progress immediately."),
        ])
        assignment_key = fields.Datetime.to_string(assignment_datetime)
        return self._queue_notification(
            lead=lead,
            user=user,
            notification_type=event_type,
            body=body,
            deduplication_key=(
                "sla:%s:%s:%s:%s:%s"
                % (
                    lead.id,
                    rule.id,
                    assignment_key,
                    event_type,
                    user.id,
                )
            ),
        )

    @api.model
    def _queue_notification(
        self, lead, user, notification_type, body, deduplication_key
    ):
        existing = self.sudo().search([
            ("deduplication_key", "=", deduplication_key),
        ], limit=1)
        if existing:
            return existing

        phone = self._phone_for_user(user)
        values = {
            "name": "%s - %s" % (
                dict(self._fields["notification_type"].selection).get(
                    notification_type
                ),
                lead.display_name,
            ),
            "lead_id": lead.id,
            "recipient_user_id": user.id,
            "recipient_phone": phone or False,
            "notification_type": notification_type,
            "body": body,
            "deduplication_key": deduplication_key,
            "state": "pending" if phone else "skipped",
            "response_message": (
                False
                if phone
                else _("The recipient has no valid Mobile or Phone number.")
            ),
        }
        notification = self.sudo().create(values)
        if phone:
            cron = self.env.ref(
                "brokerage_crm.ir_cron_brokerage_whatsapp",
                raise_if_not_found=False,
            )
            if cron:
                cron.sudo()._trigger()
        return notification

    @api.model
    def _cron_process_pending(self, limit=50):
        now = fields.Datetime.now()
        max_attempts = max(
            1,
            int(self._get_parameter("ultramsg_max_attempts", 3) or 3),
        )
        self.env.cr.execute(
            """
            SELECT id
             FROM brokerage_whatsapp_notification
             WHERE state IN ('pending', 'failed')
               AND retry_cycle_attempt_count < %s
               AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
             ORDER BY create_date, id
             FOR UPDATE SKIP LOCKED
             LIMIT %s
            """,
            [max_attempts, now, limit],
        )
        notification_ids = [row[0] for row in self.env.cr.fetchall()]
        for notification in self.sudo().browse(notification_ids):
            try:
                with self.env.cr.savepoint():
                    notification._send_ultramsg(max_attempts=max_attempts)
            except Exception as error:  # Never stop processing the queue.
                _logger.exception(
                    "Unexpected UltraMsg error for notification %s",
                    notification.id,
                )
                notification._mark_failed(
                    _("Unexpected delivery error: %s") % error,
                    max_attempts,
                )
        return True

    def _send_ultramsg(self, max_attempts):
        self.ensure_one()
        if modules.module.current_test and not self.env.context.get(
            "allow_ultramsg_request"
        ):
            self._mark_failed(
                _("External UltraMsg requests are disabled during tests."),
                max_attempts,
            )
            return False

        instance_id = str(self._get_parameter(
            "ultramsg_instance_id", ""
        )).strip()
        token = str(self._get_parameter("ultramsg_token", "")).strip()
        if not re.fullmatch(r"instance\d+", instance_id) or not token:
            self._mark_failed(
                _("UltraMsg is enabled but its credentials are incomplete."),
                max_attempts,
                permanent=True,
            )
            return False

        connect_timeout = max(
            1,
            int(self._get_parameter("ultramsg_connect_timeout", 5) or 5),
        )
        read_timeout = max(
            1,
            int(self._get_parameter("ultramsg_read_timeout", 15) or 15),
        )
        url = "https://api.ultramsg.com/%s/messages/chat" % instance_id
        try:
            response = requests.post(
                url,
                data={
                    "token": token,
                    "to": self.recipient_phone,
                    "body": self.body,
                    "priority": 10,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                timeout=(connect_timeout, read_timeout),
            )
        except requests.RequestException as error:
            self._mark_failed(
                _("UltraMsg network error: %s") % error,
                max_attempts,
            )
            return False

        response_text = (response.text or "")[:2000]
        try:
            response_data = response.json()
        except (ValueError, json.JSONDecodeError):
            response_data = {}
        sent_value = response_data.get("sent")
        sent = sent_value is True or str(sent_value).lower() == "true"
        if response.ok and sent:
            self.write({
                "state": "sent",
                "attempt_count": self.attempt_count + 1,
                "retry_cycle_attempt_count": (
                    self.retry_cycle_attempt_count + 1
                ),
                "next_attempt_at": False,
                "last_attempt_at": fields.Datetime.now(),
                "sent_at": fields.Datetime.now(),
                "http_status": response.status_code,
                "external_message_id": str(
                    response_data.get("id") or ""
                ),
                "response_message": response_text,
            })
            return True

        self._mark_failed(
            _("UltraMsg rejected the message (HTTP %(status)s): %(response)s")
            % {
                "status": response.status_code,
                "response": response_text or _("Empty response"),
            },
            max_attempts,
            http_status=response.status_code,
            permanent=(
                400 <= response.status_code < 500
                and response.status_code != 429
            ),
        )
        return False

    def _mark_failed(
        self,
        message,
        max_attempts,
        http_status=False,
        permanent=False,
    ):
        self.ensure_one()
        attempt_count = self.attempt_count + 1
        retry_cycle_attempt_count = (
            max_attempts
            if permanent
            else self.retry_cycle_attempt_count + 1
        )
        base_delay = max(
            1,
            int(self._get_parameter(
                "ultramsg_retry_base_minutes", 5
            ) or 5),
        )
        maximum_delay = max(
            base_delay,
            int(self._get_parameter(
                "ultramsg_retry_max_minutes", 60
            ) or 60),
        )
        retry_delay = min(
            maximum_delay,
            base_delay * (2 ** max(0, retry_cycle_attempt_count - 1)),
        )
        terminal_failure = retry_cycle_attempt_count >= max_attempts
        self.write({
            "state": "failed",
            "attempt_count": attempt_count,
            "retry_cycle_attempt_count": retry_cycle_attempt_count,
            "next_attempt_at": (
                fields.Datetime.now() + timedelta(minutes=retry_delay)
                if not terminal_failure
                else False
            ),
            "last_attempt_at": fields.Datetime.now(),
            "http_status": http_status or False,
            "response_message": str(message)[:2000],
        })
        if terminal_failure:
            self._alert_terminal_failure()

    def _alert_terminal_failure(self):
        self.ensure_one()
        if self.failure_alerted_at:
            return

        configured_user_id = int(
            self._get_parameter(
                "ultramsg_failure_alert_user_id", 0
            ) or 0
        )
        alert_user = self.env["res.users"].sudo().browse(
            configured_user_id
        ).exists()
        if not alert_user:
            alert_user = self.lead_id.sudo().team_id.user_id
        if alert_user and not alert_user.active:
            alert_user = self.env["res.users"]

        alert_time = fields.Datetime.now()
        self.sudo().write({
            "failure_alerted_at": alert_time,
            "failure_alert_user_id": alert_user.id or False,
        })
        self.lead_id.sudo().message_post(
            body=_(
                "WhatsApp delivery permanently failed for %(recipient)s "
                "after %(attempts)s attempt(s). Open the WhatsApp Delivery "
                "Log to review the error and retry after correcting it."
            ) % {
                "recipient": self.recipient_user_id.display_name,
                "attempts": self.attempt_count,
            },
            subtype_xmlid="mail.mt_note",
        )
        if alert_user:
            activity_type = self.env.ref(
                "mail.mail_activity_data_todo",
                raise_if_not_found=False,
            )
            model = self.env["ir.model"].sudo()._get("crm.lead")
            if activity_type and model:
                self.env["mail.activity"].sudo().create({
                    "activity_type_id": activity_type.id,
                    "summary": _("WhatsApp delivery failed"),
                    "note": _(
                        "Notification %(notification)s failed permanently. "
                        "Last error: %(error)s"
                    ) % {
                        "notification": self.display_name,
                        "error": self.response_message or "-",
                    },
                    "user_id": alert_user.id,
                    "res_model_id": model.id,
                    "res_id": self.lead_id.id,
                    "date_deadline": fields.Date.context_today(self),
                })

    def action_retry_now(self):
        if not self.env.user.has_group(
            "brokerage_crm.group_brokerage_sales_manager"
        ):
            raise AccessError(_(
                "Only a Brokerage Configuration Manager can retry WhatsApp "
                "delivery."
            ))
        enabled = self._is_enabled()
        for notification in self:
            if notification.state not in ("failed", "skipped"):
                raise ValidationError(_(
                    "Only failed or skipped WhatsApp notifications can be "
                    "retried."
                ))
            if not enabled:
                raise ValidationError(_(
                    "Enable UltraMsg in CRM Settings before retrying."
                ))
            phone = self._phone_for_user(notification.recipient_user_id)
            if not phone:
                raise ValidationError(_(
                    "The recipient still has no valid Mobile or Phone number."
                ))
            notification.sudo().write({
                "recipient_phone": phone,
                "state": "pending",
                "retry_cycle_attempt_count": 0,
                "manual_retry_count": notification.manual_retry_count + 1,
                "next_attempt_at": fields.Datetime.now(),
                "sent_at": False,
                "http_status": False,
                "external_message_id": False,
                "failure_alerted_at": False,
                "failure_alert_user_id": False,
            })
        cron = self.env.ref(
            "brokerage_crm.ir_cron_brokerage_whatsapp",
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()
        return True
