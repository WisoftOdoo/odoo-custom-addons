import hashlib
import hmac
import json
import logging
from datetime import timedelta

import requests
from psycopg2 import IntegrityError

from odoo import api, fields, models, modules, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class BrokerageMetaWebhookEvent(models.Model):
    _name = "brokerage.meta.webhook.event"
    _description = "Meta Lead Ads Webhook Event"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, readonly=True)
    meta_lead_id = fields.Char(required=True, readonly=True, index=True)
    page_id = fields.Char(readonly=True, index=True)
    form_id = fields.Char(readonly=True)
    ad_id = fields.Char(readonly=True)
    payload = fields.Text(required=True, readonly=True)
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("processed", "Processed"),
            ("failed", "Failed"),
        ],
        required=True,
        default="pending",
        readonly=True,
        index=True,
    )
    attempt_count = fields.Integer(default=0, readonly=True)
    next_attempt_at = fields.Datetime(readonly=True, index=True)
    last_attempt_at = fields.Datetime(readonly=True)
    processed_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)
    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        readonly=True,
        ondelete="set null",
        index=True,
    )
    duplicate = fields.Boolean(readonly=True)
    duplicate_action = fields.Char(readonly=True)

    _meta_lead_unique = models.Constraint(
        "UNIQUE(meta_lead_id)",
        "This Meta lead webhook has already been received.",
    )

    @api.model
    def _parameter(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(
            "brokerage_crm.%s" % key,
            default,
        )

    @api.model
    def enqueue_payload(self, payload):
        if payload.get("object") != "page":
            return self.browse()
        events = self.browse()
        expected_page_id = str(self._parameter("meta_page_id", "") or "")
        serialized_payload = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for entry in payload.get("entry", []):
            page_id = str(entry.get("id") or "")
            if expected_page_id and page_id != expected_page_id:
                _logger.warning(
                    "Ignored Meta lead event for unexpected Page %s",
                    page_id,
                )
                continue
            for change in entry.get("changes", []):
                if change.get("field") != "leadgen":
                    continue
                value = change.get("value") or {}
                meta_lead_id = str(
                    value.get("leadgen_id") or value.get("lead_id") or ""
                )
                if not meta_lead_id:
                    continue
                existing = self.sudo().search([
                    ("meta_lead_id", "=", meta_lead_id),
                ], limit=1)
                if existing:
                    events |= existing
                    continue
                try:
                    with self.env.cr.savepoint():
                        event = self.sudo().create({
                            "name": _("Meta Lead %s") % meta_lead_id,
                            "meta_lead_id": meta_lead_id,
                            "page_id": page_id or value.get("page_id"),
                            "form_id": str(value.get("form_id") or ""),
                            "ad_id": str(value.get("ad_id") or ""),
                            "payload": serialized_payload,
                        })
                except IntegrityError:
                    event = self.sudo().search([
                        ("meta_lead_id", "=", meta_lead_id),
                    ], limit=1)
                events |= event
        if events.filtered(lambda event: event.state in ("pending", "failed")):
            cron = self.env.ref(
                "brokerage_crm.ir_cron_process_meta_webhooks",
                raise_if_not_found=False,
            )
            if cron:
                cron.sudo()._trigger()
        return events

    @api.model
    def _cron_process_pending(self, limit=30):
        now = fields.Datetime.now()
        max_attempts = max(
            1,
            int(self._parameter("meta_max_attempts", 5) or 5),
        )
        self.env.cr.execute(
            """
            SELECT id
              FROM brokerage_meta_webhook_event
             WHERE state IN ('pending', 'failed')
               AND attempt_count < %s
               AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
             ORDER BY create_date, id
             FOR UPDATE SKIP LOCKED
             LIMIT %s
            """,
            [max_attempts, now, limit],
        )
        event_ids = [row[0] for row in self.env.cr.fetchall()]
        for event in self.sudo().browse(event_ids):
            event.write({
                "state": "processing",
                "last_attempt_at": now,
                "attempt_count": event.attempt_count + 1,
                "last_error": False,
            })
            try:
                with self.env.cr.savepoint():
                    event._process_event()
            except Exception as error:
                _logger.exception(
                    "Could not process Meta webhook event %s",
                    event.id,
                )
                event._mark_failed(error, max_attempts)
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

    def _process_event(self):
        self.ensure_one()
        lead_data = self._retrieve_meta_lead()
        mapped = self._map_meta_lead(lead_data)
        lead, duplicate, duplicate_action = self._ingest_meta_lead(mapped)
        self.write({
            "state": "processed",
            "processed_at": fields.Datetime.now(),
            "next_attempt_at": False,
            "last_error": False,
            "lead_id": lead.id,
            "duplicate": duplicate,
            "duplicate_action": duplicate_action or False,
            "form_id": str(lead_data.get("form_id") or self.form_id or ""),
            "ad_id": str(lead_data.get("ad_id") or self.ad_id or ""),
        })
        return lead

    def _retrieve_meta_lead(self):
        self.ensure_one()
        if modules.module.current_test and not self.env.context.get(
            "allow_meta_request"
        ):
            raise ValidationError(_(
                "External Meta requests are disabled during automated tests."
            ))
        token = str(self._parameter("meta_page_access_token", "") or "")
        app_secret = str(self._parameter("meta_app_secret", "") or "")
        graph_version = str(
            self._parameter("meta_graph_version", "v24.0") or "v24.0"
        ).strip()
        timeout = max(
            1,
            int(self._parameter("meta_request_timeout", 15) or 15),
        )
        if not token or not app_secret:
            raise ValidationError(_(
                "Meta Lead Ads credentials are incomplete in CRM Settings."
            ))
        appsecret_proof = hmac.new(
            app_secret.encode("utf-8"),
            token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        url = "https://graph.facebook.com/%s/%s" % (
            graph_version,
            self.meta_lead_id,
        )
        try:
            response = requests.get(
                url,
                params={
                    "fields": (
                        "id,created_time,ad_id,ad_name,adset_id,adset_name,"
                        "campaign_id,campaign_name,form_id,is_organic,"
                        "platform,field_data"
                    ),
                    "access_token": token,
                    "appsecret_proof": appsecret_proof,
                },
                headers={"Accept": "application/json"},
                timeout=(5, timeout),
            )
        except requests.RequestException as error:
            raise ValidationError(_("Meta Graph API network error: %s") % error)
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            data = {}
        if not response.ok or data.get("error"):
            error_data = data.get("error") or {}
            message = error_data.get("message") or response.text or _(
                "Unknown Meta Graph API error"
            )
            raise ValidationError(_(
                "Meta Graph API returned HTTP %(status)s: %(message)s",
                status=response.status_code,
                message=str(message)[:1000],
            ))
        return data

    @api.model
    def _map_meta_lead(self, data):
        answers = {}
        for field_data in data.get("field_data", []):
            key = str(field_data.get("name") or "").strip().casefold()
            values = field_data.get("values") or []
            answers[key] = str(values[0]).strip() if values else ""
        first_name = answers.get("first_name", "")
        last_name = answers.get("last_name", "")
        customer_name = (
            answers.get("full_name")
            or answers.get("name")
            or " ".join(filter(None, (first_name, last_name)))
        ).strip()
        email = (
            answers.get("email")
            or answers.get("email_address")
        ).strip()
        phone = (
            answers.get("phone_number")
            or answers.get("phone")
            or answers.get("mobile_number")
            or answers.get("mobile")
        ).strip()
        if not email and not phone:
            raise ValidationError(_(
                "The Meta lead contains neither an email address nor a phone "
                "number. Check the Instant Form field mapping."
            ))
        if not customer_name:
            customer_name = email.split("@", 1)[0] if email else phone
        return {
            "customer_name": customer_name,
            "email": email,
            "phone": phone,
            "campaign_name": str(data.get("campaign_name") or "").strip(),
            "campaign_id": str(data.get("campaign_id") or "").strip(),
            "ad_name": str(data.get("ad_name") or "").strip(),
            "ad_id": str(data.get("ad_id") or "").strip(),
            "adset_name": str(data.get("adset_name") or "").strip(),
            "adset_id": str(data.get("adset_id") or "").strip(),
            "form_id": str(data.get("form_id") or "").strip(),
            "platform": str(data.get("platform") or "Meta").strip(),
            "created_time": str(data.get("created_time") or "").strip(),
            "answers": answers,
        }

    @api.model
    def _utm_record(self, model_name, name):
        name = str(name or "").strip()
        if not name:
            return self.env[model_name].browse()
        return self.env["utm.mixin"].sudo()._find_or_create_record(
            model_name,
            name,
        )

    def _ingest_meta_lead(self, mapped):
        self.ensure_one()
        try:
            source_id = int(self._parameter("meta_source_id", 0) or 0)
        except (TypeError, ValueError):
            source_id = 0
        source = self.env["utm.source"].sudo().browse(source_id).exists()
        if not source:
            source = self.env.ref(
                "brokerage_crm.lead_source_meta",
                raise_if_not_found=False,
            )
        if not source:
            raise ValidationError(_(
                "Configure the Meta Lead Source in CRM Settings."
            ))
        campaign_label = mapped["campaign_name"] or (
            _("Meta Campaign %s") % mapped["campaign_id"]
            if mapped["campaign_id"] else ""
        )
        campaign = self._utm_record("utm.campaign", campaign_label)
        medium = self._utm_record("utm.medium", "Meta Lead Ads")
        campaign_policy = self.env[
            "brokerage.meta.campaign.rule"
        ].sudo().policy_for_meta(
            self.page_id,
            mapped["campaign_id"],
            mapped["form_id"],
        )
        assignment_type = (
            "round_robin"
            if campaign_policy and campaign_policy.routing_mode != "manual"
            else "manual"
        )
        customer_name = mapped["customer_name"]
        email = mapped["email"]
        phone = mapped["phone"]
        duplicate_key = self.env[
            "crm.lead"
        ].sudo()._brokerage_build_deduplication_key(
            customer_name,
            email,
            phone,
        )
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [duplicate_key],
        )
        existing = self.env[
            "crm.lead"
        ].sudo()._brokerage_find_duplicate_by_contact(
            email,
            phone,
            duplicate_key=duplicate_key,
        )
        if existing:
            action = existing._brokerage_handle_duplicate_enquiry(
                source,
                campaign,
                medium,
                customer_name,
                email,
                phone,
                assignment_type,
                campaign_policy=campaign_policy,
            )
            return existing, True, action

        technical_lines = [
            _("Meta Lead ID: %s") % self.meta_lead_id,
            _("Meta Page ID: %s") % (self.page_id or "-"),
            _("Meta Form ID: %s") % (mapped["form_id"] or "-"),
            _("Meta Campaign: %s") % (campaign_label or "-"),
            _("Meta Ad Set: %s") % (
                mapped["adset_name"] or mapped["adset_id"] or "-"
            ),
            _("Meta Ad: %s") % (
                mapped["ad_name"] or mapped["ad_id"] or "-"
            ),
            _("Meta Platform: %s") % (mapped["platform"] or "-"),
            _("Meta Submitted At: %s") % (mapped["created_time"] or "-"),
            _("Assignment Mode: %s") % dict(
                self.env["crm.lead"]._fields["assignment_type"].selection
            ).get(assignment_type, assignment_type),
        ]
        contact_keys = {
            "full_name", "name", "first_name", "last_name", "email",
            "email_address", "phone_number", "phone", "mobile_number",
            "mobile",
        }
        custom_answers = [
            "%s: %s" % (key.replace("_", " ").title(), value)
            for key, value in sorted(mapped["answers"].items())
            if key not in contact_keys and value
        ]
        if custom_answers:
            technical_lines.extend([
                "",
                _("Meta Form Answers:"),
                *custom_answers,
            ])
        lead_values = {
            "name": "%s - %s" % (source.display_name, customer_name),
            "contact_name": customer_name,
            "phone": phone or False,
            "email_from": email or False,
            "description": "\n".join(technical_lines),
            "source_id": source.id,
            "campaign_id": campaign.id or False,
            "medium_id": medium.id or False,
            "assignment_type": assignment_type,
            "user_id": False,
            "team_id": False,
            "type": "opportunity",
        }
        if campaign_policy:
            lead_values["campaign_routing_policy_id"] = campaign_policy.id
        lead = self.env["crm.lead"].sudo().create(lead_values)
        return lead, False, False

    def action_retry_now(self):
        self.sudo().write({
            "state": "pending",
            "attempt_count": 0,
            "next_attempt_at": fields.Datetime.now(),
            "last_error": False,
        })
        cron = self.env.ref(
            "brokerage_crm.ir_cron_process_meta_webhooks",
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()
        return True
