import json
import logging
import uuid
from datetime import timedelta

import requests

from odoo import api, fields, models, tools, _


_logger = logging.getLogger(__name__)


class BrokerageMetaConversionWebhook(models.Model):
    """Reliable outbound conversion delivery to the external Meta lead system."""

    _name = "brokerage.meta.conversion.webhook"
    _description = "Meta Conversion External Webhook"
    _order = "event_time, id"

    name = fields.Char(required=True, readonly=True)
    lead_id = fields.Many2one("crm.lead", readonly=True, ondelete="set null", index=True)
    meta_event_id = fields.Many2one(
        "brokerage.meta.crm.event", readonly=True, ondelete="set null", index=True,
    )
    event_key = fields.Char(required=True, readonly=True, index=True)
    event_id = fields.Char(required=True, readonly=True)
    event_name = fields.Char(required=True, readonly=True, index=True)
    event_time = fields.Datetime(required=True, readonly=True, index=True)
    state = fields.Selection([
        ("pending", "Pending"), ("sending", "Sending"), ("sent", "Sent"),
        ("failed", "Failed"), ("skipped", "Skipped"),
    ], default="pending", required=True, readonly=True, index=True)
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
        "This external Meta conversion event has already been queued.",
    )

    @api.model
    def _parameter(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(
            "brokerage_crm.%s" % key, default,
        )

    @api.model
    def _enabled(self):
        return tools.str2bool(self._parameter("external_conversion_enabled", "False"), default=False)

    @api.model
    def enqueue_for_meta_event(self, meta_event):
        meta_event.ensure_one()
        if not self._enabled() or not meta_event.lead_id:
            return self.browse()
        raw_key = "%s|%s|%s" % (meta_event.lead_id.id, meta_event.meta_lead_id, meta_event.event_name)
        event_key = meta_event._sha256(raw_key)
        existing = self.sudo().search([("event_key", "=", event_key)], limit=1)
        if existing:
            return existing
        event = self.sudo().create({
            "name": _("External %(event)s - %(lead)s", event=meta_event.event_name, lead=meta_event.lead_id.display_name),
            "lead_id": meta_event.lead_id.id,
            "meta_event_id": meta_event.id,
            "event_key": event_key,
            "event_id": "odoo-%s" % uuid.uuid4().hex,
            "event_name": meta_event.event_name,
            "event_time": meta_event.event_time,
        })
        cron = self.env.ref("brokerage_crm.ir_cron_send_external_conversion_events", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
        return event

    def _build_payload(self):
        self.ensure_one()
        lead = self.lead_id.sudo()
        meta_event = self.meta_event_id
        return {
            "test": tools.str2bool(self._parameter("external_conversion_test_mode", "False"), default=False),
            "event_name": self.event_name,
            "event_id": self.event_id,
            "source": "Meta",
            "meta_lead_id": meta_event.meta_lead_id,
            "event_time": fields.Datetime.to_string(self.event_time),
            "lead": {
                "name": lead.contact_name or lead.partner_name or lead.name or "",
                "email": lead.email_from or "",
                "phone": lead.phone or "",
            },
            "odoo": {
                "stage": lead.stage_id.display_name or "",
                "assignment_type": lead.assignment_type or "",
                "sales_team": lead.team_id.display_name or "",
                "campaign": lead.campaign_id.display_name or "",
            },
        }

    def _send(self):
        self.ensure_one()
        url = str(self._parameter("external_conversion_url", "") or "").strip()
        if not url:
            raise ValueError(_("External conversion webhook URL is not configured."))
        payload = self._build_payload()
        timeout = max(1, int(self._parameter("external_conversion_timeout", 15) or 15))
        response = requests.post(
            url, json=payload, headers={"Accept": "application/json"}, timeout=(5, timeout),
        )
        try:
            response_data = response.json()
        except (ValueError, json.JSONDecodeError):
            response_data = {"raw_response": str(response.text or "")[:4000]}
        self.write({
            "http_status": response.status_code,
            "request_payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            "response_payload": json.dumps(response_data, ensure_ascii=False, separators=(",", ":"))[:8000],
        })
        if not response.ok:
            raise ValueError(_("External conversion webhook returned HTTP %s: %s") % (response.status_code, response.text[:2000]))
        self.write({"state": "sent", "sent_at": fields.Datetime.now(), "next_attempt_at": False, "last_error": False})

    def _mark_failed(self, error, max_attempts):
        delays = (1, 5, 15, 60, 180)
        exhausted = self.attempt_count >= max_attempts
        delay = delays[min(max(self.attempt_count - 1, 0), len(delays) - 1)]
        self.write({
            "state": "failed",
            "next_attempt_at": False if exhausted else fields.Datetime.now() + timedelta(minutes=delay),
            "last_error": str(error)[:4000],
        })

    @api.model
    def _cron_send_pending(self, limit=50):
        if not self._enabled():
            return True
        now = fields.Datetime.now()
        max_attempts = max(1, int(self._parameter("external_conversion_max_attempts", 5) or 5))
        self.env.cr.execute("""
            SELECT id FROM brokerage_meta_conversion_webhook
            WHERE state IN ('pending', 'failed') AND attempt_count < %s
              AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
            ORDER BY event_time, id FOR UPDATE SKIP LOCKED LIMIT %s
        """, [max_attempts, now, limit])
        for event in self.sudo().browse([row[0] for row in self.env.cr.fetchall()]):
            event.write({"state": "sending", "attempt_count": event.attempt_count + 1, "last_attempt_at": now, "last_error": False})
            try:
                with self.env.cr.savepoint():
                    event._send()
            except Exception as error:
                _logger.exception("Could not send external Meta conversion event %s", event.id)
                event._mark_failed(error, max_attempts)
        return True

