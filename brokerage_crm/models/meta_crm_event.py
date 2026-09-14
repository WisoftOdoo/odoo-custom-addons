import calendar
import hashlib
import json
import logging
import re
import uuid
from datetime import timedelta

import requests

from odoo import api, fields, models, modules, tools, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class BrokerageMetaCrmEvent(models.Model):
    """Reliable, isolated outbound queue for Meta CRM funnel events."""

    _name = "brokerage.meta.crm.event"
    _description = "Meta CRM Outbound Event"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, readonly=True)
    lead_id = fields.Many2one(
        "crm.lead", readonly=True, ondelete="set null", index=True,
    )
    webhook_event_id = fields.Many2one(
        "brokerage.meta.webhook.event",
        string="Inbound Meta Event",
        readonly=True,
        ondelete="set null",
        index=True,
    )
    meta_lead_id = fields.Char(required=True, readonly=True, index=True)
    event_name = fields.Char(required=True, readonly=True, index=True)
    event_key = fields.Char(required=True, readonly=True, index=True)
    event_id = fields.Char(required=True, readonly=True)
    event_time = fields.Datetime(required=True, readonly=True, index=True)
    stage_id = fields.Many2one("crm.stage", readonly=True, ondelete="set null")
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("sending", "Sending"),
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
    last_attempt_at = fields.Datetime(readonly=True)
    next_attempt_at = fields.Datetime(readonly=True, index=True)
    sent_at = fields.Datetime(readonly=True)
    http_status = fields.Integer(readonly=True)
    request_payload = fields.Text(readonly=True)
    response_payload = fields.Text(readonly=True)
    last_error = fields.Text(readonly=True)

    _event_key_unique = models.Constraint(
        "UNIQUE(event_key)",
        "This Meta CRM stage event has already been queued.",
    )

    @api.model
    def _parameter(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(
            "brokerage_crm.%s" % key,
            default,
        )

    @api.model
    def _enabled(self):
        return tools.str2bool(
            self._parameter("meta_crm_feedback_enabled", "False"),
            default=False,
        )

    @api.model
    def _latest_webhook_event(self, lead):
        return self.env["brokerage.meta.webhook.event"].sudo().search([
            ("lead_id", "=", lead.id),
            ("state", "=", "processed"),
        ], order="processed_at desc, id desc", limit=1)

    @api.model
    def enqueue_for_lead(
        self,
        lead,
        event_name,
        webhook_event=False,
        event_time=False,
    ):
        """Queue one event per Meta lead ID and funnel event name.

        This method never performs an external request and intentionally does
        nothing for manual/API leads that have no inbound Meta webhook record.
        """
        lead.ensure_one()
        if not self._enabled():
            return self.browse()
        webhook_event = webhook_event or self._latest_webhook_event(lead)
        if not webhook_event or not webhook_event.meta_lead_id:
            return self.browse()
        event_name = re.sub(r"[^A-Za-z0-9_]", "", event_name or "")[:40]
        if not event_name:
            return self.browse()
        raw_key = "%s|%s|%s" % (
            lead.id,
            webhook_event.meta_lead_id,
            event_name,
        )
        event_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        existing = self.sudo().search([
            ("event_key", "=", event_key),
        ], limit=1)
        if existing:
            return existing
        event_time = event_time or fields.Datetime.now()
        event = self.sudo().create({
            "name": _("%(event)s - %(lead)s", event=event_name, lead=lead.display_name),
            "lead_id": lead.id,
            "webhook_event_id": webhook_event.id,
            "meta_lead_id": webhook_event.meta_lead_id,
            "event_name": event_name,
            "event_key": event_key,
            "event_id": "odoo-%s" % uuid.uuid4().hex,
            "event_time": event_time,
            "stage_id": lead.stage_id.id or False,
        })
        cron = self.env.ref(
            "brokerage_crm.ir_cron_send_meta_crm_events",
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()
        return event

    @api.model
    def _sha256(self, value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @api.model
    def _normalize_email(self, value):
        return str(value or "").strip().casefold()

    @api.model
    def _normalize_phone(self, value):
        return re.sub(r"\D", "", str(value or ""))

    def _build_payload(self):
        self.ensure_one()
        if not self.lead_id:
            raise ValidationError(_("The related Odoo lead no longer exists."))
        lead = self.lead_id.sudo()
        user_data = {"lead_id": self.meta_lead_id}
        email = self._normalize_email(lead.email_from)
        phone = self._normalize_phone(lead.phone)
        if email:
            user_data["em"] = [self._sha256(email)]
        if phone:
            user_data["ph"] = [self._sha256(phone)]
        event_datetime = fields.Datetime.to_datetime(self.event_time)
        event_time = calendar.timegm(event_datetime.utctimetuple())
        crm_name = str(
            self._parameter("meta_crm_name", "Odoo CRM") or "Odoo CRM"
        ).strip()
        custom_data = {
            "event_source": "crm",
            "lead_event_source": crm_name,
            "odoo_stage": lead.stage_id.display_name or "",
            "odoo_assignment_type": lead.assignment_type or "",
            "odoo_sales_team": lead.team_id.display_name or "",
            "odoo_campaign": lead.campaign_id.display_name or "",
        }
        if self.event_name == "Purchase":
            currency = lead.company_currency or lead.company_id.currency_id
            custom_data.update({
                "value": float(lead.expected_revenue or 0.0),
                "currency": currency.name or "AED",
            })
        payload = {
            "data": [{
                "event_name": self.event_name,
                "event_time": event_time,
                "event_id": self.event_id,
                "action_source": "system_generated",
                "user_data": user_data,
                "custom_data": custom_data,
            }],
        }
        test_event_code = str(
            self._parameter("meta_crm_test_event_code", "") or ""
        ).strip()
        if test_event_code:
            payload["test_event_code"] = test_event_code
        return payload

    def _send(self):
        self.ensure_one()
        if modules.module.current_test and not self.env.context.get(
            "allow_meta_crm_request"
        ):
            raise ValidationError(_(
                "External Meta CRM requests are disabled during automated tests."
            ))
        dataset_id = str(
            self._parameter("meta_crm_dataset_id", "") or ""
        ).strip()
        access_token = str(
            self._parameter("meta_crm_access_token", "") or ""
        ).strip()
        graph_version = str(
            self._parameter("meta_crm_graph_version", "v26.0") or "v26.0"
        ).strip()
        timeout = max(
            1,
            int(self._parameter("meta_crm_request_timeout", 15) or 15),
        )
        if not dataset_id or not access_token:
            raise ValidationError(_(
                "Meta CRM Dataset ID or access token is missing in CRM Settings."
            ))
        payload = self._build_payload()
        url = "https://graph.facebook.com/%s/%s/events" % (
            graph_version,
            dataset_id,
        )
        try:
            response = requests.post(
                url,
                params={"access_token": access_token},
                json=payload,
                headers={"Accept": "application/json"},
                timeout=(5, timeout),
            )
        except requests.RequestException as error:
            raise ValidationError(_("Meta CRM network error: %s") % error)
        try:
            response_data = response.json()
        except (ValueError, json.JSONDecodeError):
            response_data = {"raw_response": str(response.text or "")[:4000]}
        self.write({
            "http_status": response.status_code,
            "request_payload": json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ),
            "response_payload": json.dumps(
                response_data, ensure_ascii=False, separators=(",", ":")
            )[:8000],
        })
        if not response.ok or response_data.get("error"):
            error = response_data.get("error") or {}
            message = error.get("message") or response.text or _(
                "Unknown Meta CRM API error"
            )
            raise ValidationError(_(
                "Meta CRM API returned HTTP %(status)s: %(message)s",
                status=response.status_code,
                message=str(message)[:2000],
            ))
        self.write({
            "state": "sent",
            "sent_at": fields.Datetime.now(),
            "next_attempt_at": False,
            "last_error": False,
        })
        return True

    def _mark_failed(self, error, max_attempts):
        self.ensure_one()
        delays = (1, 5, 15, 60, 180)
        delay_index = min(max(self.attempt_count - 1, 0), len(delays) - 1)
        exhausted = self.attempt_count >= max_attempts
        self.write({
            "state": "failed",
            "next_attempt_at": (
                False
                if exhausted
                else fields.Datetime.now() + timedelta(minutes=delays[delay_index])
            ),
            "last_error": str(error)[:4000],
        })

    @api.model
    def _cron_send_pending(self, limit=50):
        if not self._enabled():
            return True
        now = fields.Datetime.now()
        max_attempts = max(
            1,
            int(self._parameter("meta_crm_max_attempts", 5) or 5),
        )
        self.env.cr.execute(
            """
            SELECT id
              FROM brokerage_meta_crm_event
             WHERE state IN ('pending', 'failed')
               AND attempt_count < %s
               AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
             ORDER BY event_time, id
             FOR UPDATE SKIP LOCKED
             LIMIT %s
            """,
            [max_attempts, now, limit],
        )
        for event in self.sudo().browse([row[0] for row in self.env.cr.fetchall()]):
            event.write({
                "state": "sending",
                "attempt_count": event.attempt_count + 1,
                "last_attempt_at": now,
                "last_error": False,
            })
            if not event.lead_id:
                event.write({
                    "state": "skipped",
                    "next_attempt_at": False,
                    "last_error": _("The related Odoo lead was deleted."),
                })
                continue
            try:
                with self.env.cr.savepoint():
                    event._send()
            except Exception as error:
                _logger.exception("Could not send Meta CRM event %s", event.id)
                event._mark_failed(error, max_attempts)
        return True

    def action_retry_now(self):
        self.sudo().write({
            "state": "pending",
            "attempt_count": 0,
            "next_attempt_at": fields.Datetime.now(),
            "last_error": False,
        })
        cron = self.env.ref(
            "brokerage_crm.ir_cron_send_meta_crm_events",
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()
        return True


class CrmLeadMetaFeedback(models.Model):
    _inherit = "crm.lead"

    _META_STAGE_EVENTS = {
        "new": "CREATED",
        "hot": "QUALIFIED",
        "not_interested": "UNQUALIFIED",
        "won": "QUALIFIED",
    }

    def _brokerage_meta_event_for_stage(self):
        self.ensure_one()
        stage = self.stage_id
        code = self._stage_code(stage)
        event_name = self._META_STAGE_EVENTS.get(code)
        if event_name:
            return event_name
        return False

    def write(self, vals):
        tracked = bool(
            {"stage_id", "active", "probability", "lost_reason_id"}
            & set(vals)
        ) and not self.env.context.get("skip_meta_crm_feedback")
        before = {}
        if tracked:
            before = {
                lead.id: {
                    "stage_id": lead.stage_id.id,
                    "active": lead.active,
                    "probability": lead.probability,
                    "lost_reason_id": lead.lost_reason_id.id,
                }
                for lead in self
            }
        result = super().write(vals)
        if not tracked:
            return result
        queue = self.env["brokerage.meta.crm.event"].sudo()
        for lead in self:
            old = before[lead.id]
            became_lost = (
                old["active"]
                and not lead.active
                and not lead.stage_id.is_won
            ) or (
                not old["lost_reason_id"]
                and bool(lead.lost_reason_id)
            )
            if became_lost:
                event_name = "UNQUALIFIED"
            elif lead.stage_id.id != old["stage_id"]:
                event_name = lead._brokerage_meta_event_for_stage()
            elif old["probability"] != 100 and lead.probability == 100:
                event_name = "QUALIFIED"
            else:
                event_name = False
            if event_name:
                queue.enqueue_for_lead(lead.sudo(), event_name)
        return result


class MetaWebhookEventFeedback(models.Model):
    _inherit = "brokerage.meta.webhook.event"

    def _process_event(self):
        lead = super()._process_event()
        self.env["brokerage.meta.crm.event"].sudo().enqueue_for_lead(
            lead.sudo(),
            "CREATED",
            webhook_event=self,
            event_time=self.processed_at or fields.Datetime.now(),
        )
        return lead
