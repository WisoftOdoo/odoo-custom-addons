import json
import secrets
from datetime import timedelta
from urllib.parse import quote, urlparse

import requests

from odoo import api, fields, models, modules, _
from odoo.exceptions import ValidationError


class BrokerageTelephonyProvider(models.Model):
    _name = "brokerage.telephony.provider"
    _description = "Brokerage Telephony Provider"
    _order = "company_id, sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(
        required=True,
        copy=False,
        index=True,
        help="Stable identifier used in the inbound event URL.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
        ondelete="cascade",
        index=True,
    )
    adapter_type = fields.Selection(
        selection=[
            ("generic_http", "Generic HTTP PBX"),
            ("three_cx", "3CX Call Control"),
        ],
        required=True,
        default="generic_http",
    )
    base_url = fields.Char(
        string="PBX Base URL",
        help="HTTPS base URL of the PBX, for example https://pbx.example.com.",
    )
    outbound_url = fields.Char(
        string="Outbound Call URL",
        help=(
            "Generic adapter endpoint that accepts the normalized Brokerage "
            "Telephony call request."
        ),
    )
    outbound_auth_type = fields.Selection(
        selection=[
            ("none", "No Authentication"),
            ("bearer", "Bearer Token"),
            ("api_key", "API Key Header"),
        ],
        required=True,
        default="bearer",
    )
    outbound_token = fields.Char(
        string="Outbound API Secret",
        copy=False,
        groups="base.group_system",
    )
    api_key_header = fields.Char(
        string="API Key Header",
        default="X-API-Key",
        groups="base.group_system",
    )
    client_id = fields.Char(
        string="3CX Client ID",
        copy=False,
        groups="base.group_system",
    )
    client_secret = fields.Char(
        string="3CX API Key",
        copy=False,
        groups="base.group_system",
    )
    access_token = fields.Char(
        string="Cached Access Token",
        readonly=True,
        copy=False,
        groups="base.group_system",
    )
    access_token_expires_at = fields.Datetime(
        readonly=True,
        copy=False,
        groups="base.group_system",
    )
    webhook_token = fields.Char(
        string="Inbound Webhook Token",
        required=True,
        default=lambda self: secrets.token_urlsafe(32),
        copy=False,
        groups="base.group_system",
    )
    webhook_url = fields.Char(
        compute="_compute_webhook_url",
        string="Inbound Event URL",
    )
    call_timeout_seconds = fields.Integer(default=30)
    connect_timeout = fields.Integer(default=5)
    read_timeout = fields.Integer(default=20)
    verify_ssl = fields.Boolean(
        string="Verify TLS Certificate",
        default=True,
        help="Keep enabled in production.",
    )

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The telephony provider code must be unique.",
    )

    @api.depends("code")
    def _compute_webhook_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url", ""
        ).rstrip("/")
        for provider in self:
            provider.webhook_url = (
                "%s/brokerage/api/v1/telephony/events/%s"
                % (base_url, quote(provider.code or "", safe=""))
            )

    @api.model
    def _adapter_method_map(self):
        """Extension point for future provider-specific adapter modules."""
        return {
            "generic_http": "_initiate_generic_http",
            "three_cx": "_initiate_three_cx",
        }

    @api.constrains(
        "code",
        "adapter_type",
        "base_url",
        "outbound_url",
        "outbound_auth_type",
        "outbound_token",
        "api_key_header",
        "client_id",
        "client_secret",
        "webhook_token",
        "call_timeout_seconds",
        "connect_timeout",
        "read_timeout",
    )
    def _check_configuration(self):
        for provider in self:
            provider_code = (provider.code or "").strip()
            if not provider_code or not all(
                character.isalnum() or character in ("-", "_")
                for character in provider_code
            ):
                raise ValidationError(_(
                    "Provider Code may contain only letters, numbers, "
                    "hyphens, and underscores."
                ))
            if len(provider.webhook_token or "") < 24:
                raise ValidationError(_(
                    "The inbound webhook token must contain at least "
                    "24 characters."
                ))
            if provider.call_timeout_seconds <= 0:
                raise ValidationError(_("Call timeout must be positive."))
            if provider.connect_timeout <= 0 or provider.read_timeout <= 0:
                raise ValidationError(_("HTTP timeouts must be positive."))

            if provider.adapter_type == "generic_http":
                if not provider.outbound_url:
                    raise ValidationError(_(
                        "Enter the Outbound Call URL for the Generic HTTP "
                        "PBX adapter."
                    ))
                provider._validate_secure_url(provider.outbound_url)
                if (
                    provider.outbound_auth_type in ("bearer", "api_key")
                    and not provider.outbound_token
                ):
                    raise ValidationError(_(
                        "Enter the outbound API secret for the selected "
                        "authentication method."
                    ))
                if (
                    provider.outbound_auth_type == "api_key"
                    and not provider.api_key_header
                ):
                    raise ValidationError(_("Enter the API key header name."))
            elif provider.adapter_type == "three_cx":
                if not provider.base_url:
                    raise ValidationError(_("Enter the 3CX PBX Base URL."))
                provider._validate_secure_url(provider.base_url)
                if not provider.client_id or not provider.client_secret:
                    raise ValidationError(_(
                        "Enter the 3CX Client ID and API Key."
                    ))

    @api.model
    def _validate_secure_url(self, url):
        parsed = urlparse((url or "").strip())
        is_local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.netloc
            or (parsed.scheme != "https" and not is_local)
        ):
            raise ValidationError(_(
                "Telephony URLs must use HTTPS. HTTP is allowed only for "
                "localhost development."
            ))

    def write(self, vals):
        if {"base_url", "client_id", "client_secret"} & set(vals):
            vals = dict(vals)
            vals.update({
                "access_token": False,
                "access_token_expires_at": False,
            })
        return super().write(vals)

    def initiate_call(self, call):
        self.ensure_one()
        call.ensure_one()
        if not self.active:
            raise ValidationError(_("The telephony provider is inactive."))
        adapter_method = self._adapter_method_map().get(self.adapter_type)
        if not adapter_method or not hasattr(self, adapter_method):
            raise ValidationError(_(
                "No outbound adapter is registered for %s."
            ) % self.adapter_type)
        return getattr(self, adapter_method)(call)

    def _request(self, method, url, **kwargs):
        self.ensure_one()
        if (
            modules.module.current_test
            and not self.env.context.get("allow_telephony_request")
        ):
            raise ValidationError(_(
                "External telephony requests are disabled during tests."
            ))
        kwargs.setdefault(
            "timeout",
            (max(1, self.connect_timeout), max(1, self.read_timeout)),
        )
        kwargs.setdefault("verify", self.verify_ssl)
        try:
            return requests.request(method, url, **kwargs)
        except requests.RequestException as error:
            raise ValidationError(_(
                "The telephony provider could not be reached: %s"
            ) % error) from error

    @api.model
    def _response_json(self, response):
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            data = {}
        if not response.ok:
            message = (
                (data.get("message") if isinstance(data, dict) else False)
                or (
                    data.get("reasontext")
                    if isinstance(data, dict)
                    else False
                )
                or (
                    data.get("error_description")
                    if isinstance(data, dict)
                    else False
                )
                or (response.text or "")[:1000]
                or _("Empty provider response")
            )
            raise ValidationError(_(
                "The telephony provider rejected the request "
                "(HTTP %(status)s): %(message)s"
            ) % {
                "status": response.status_code,
                "message": message,
            })
        if not isinstance(data, dict):
            raise ValidationError(_(
                "The telephony provider response must be a JSON object."
            ))
        return data

    def _initiate_generic_http(self, call):
        self.ensure_one()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.outbound_auth_type == "bearer":
            headers["Authorization"] = "Bearer %s" % self.outbound_token
        elif self.outbound_auth_type == "api_key":
            headers[self.api_key_header] = self.outbound_token

        payload = {
            "request_id": call.request_uid,
            "provider_code": self.code,
            "direction": "outgoing",
            "agent": {
                "odoo_user_id": call.user_id.id,
                "extension": call.agent_extension,
                "device_id": call.agent_device_id or None,
            },
            "customer": {
                "odoo_lead_id": call.lead_id.id,
                "phone": call.to_number,
            },
            "callback": {
                "url": self.webhook_url,
                "header": "X-Brokerage-Telephony-Token",
            },
            "timeout_seconds": self.call_timeout_seconds,
        }
        response = self._request(
            "POST",
            self.outbound_url,
            headers=headers,
            json=payload,
        )
        data = self._response_json(response)
        return {
            "external_call_id": str(
                data.get("external_call_id")
                or data.get("call_id")
                or data.get("id")
                or ""
            ) or False,
            "state": self._normalize_provider_state(
                data.get("status") or data.get("state") or "initiated"
            ),
            "response": data,
        }

    def _get_three_cx_access_token(self):
        self.ensure_one()
        now = fields.Datetime.now()
        if (
            self.access_token
            and self.access_token_expires_at
            and self.access_token_expires_at > now + timedelta(minutes=1)
        ):
            return self.access_token

        token_url = "%s/connect/token" % self.base_url.rstrip("/")
        response = self._request(
            "POST",
            token_url,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        data = self._response_json(response)
        token = str(data.get("access_token") or "").strip()
        if not token:
            raise ValidationError(_(
                "3CX did not return an access token."
            ))
        expires_in = max(120, int(data.get("expires_in") or 3600))
        self.sudo().write({
            "access_token": token,
            "access_token_expires_at": now + timedelta(seconds=expires_in),
        })
        return token

    def _initiate_three_cx(self, call):
        self.ensure_one()
        token = self._get_three_cx_access_token()
        extension = quote(call.agent_extension, safe="")
        if call.agent_device_id:
            device = quote(call.agent_device_id, safe="")
            path = "/callcontrol/%s/devices/%s/makecall" % (
                extension,
                device,
            )
        else:
            path = "/callcontrol/%s/makecall" % extension
        response = self._request(
            "POST",
            "%s%s" % (self.base_url.rstrip("/"), path),
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer %s" % token,
                "Content-Type": "application/json",
            },
            json={
                "destination": call.to_number,
                "timeout": self.call_timeout_seconds,
                "attacheddata": {
                    "odoo_request_id": call.request_uid,
                    "odoo_lead_id": str(call.lead_id.id),
                },
            },
        )
        data = self._response_json(response)
        result = data.get("result") or {}
        external_call_id = (
            result.get("callid")
            or result.get("call_id")
            or data.get("callid")
            or data.get("call_id")
        )
        return {
            "external_call_id": (
                str(external_call_id) if external_call_id is not None else False
            ),
            "state": self._normalize_provider_state(
                result.get("status")
                or data.get("finalstatus")
                or "initiated"
            ),
            "response": data,
        }

    @api.model
    def _normalize_provider_state(self, state):
        normalized = str(state or "").strip().lower().replace(" ", "_")
        return {
            "initiated": "initiated",
            "accepted": "initiated",
            "calling": "ringing",
            "ringing": "ringing",
            "connected": "answered",
            "answered": "answered",
            "ongoing": "answered",
            "terminated": "completed",
            "completed": "completed",
            "ended": "completed",
            "missed": "missed",
            "no_answer": "missed",
            "noanswer": "missed",
            "failed": "failed",
            "error": "failed",
            "cancelled": "cancelled",
            "canceled": "cancelled",
            "rejected": "cancelled",
        }.get(normalized, "initiated")

    def action_regenerate_webhook_token(self):
        self.ensure_one()
        self.write({"webhook_token": secrets.token_urlsafe(32)})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Webhook Token Regenerated"),
                "message": _(
                    "Update the PBX integration before sending more events."
                ),
                "type": "warning",
                "sticky": True,
            },
        }
