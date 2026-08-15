import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request


_logger = logging.getLogger(__name__)


class BrokerageMetaWebhook(http.Controller):
    _route = "/brokerage/api/v1/meta/webhook"

    @http.route(
        _route,
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
        save_session=False,
    )
    def meta_webhook(self, **kwargs):
        if request.httprequest.method == "GET":
            return self._verify_subscription()
        return self._receive_event()

    @staticmethod
    def _parameter(key, default=""):
        return request.env["ir.config_parameter"].sudo().get_param(
            "brokerage_crm.%s" % key,
            default,
        )

    def _verify_subscription(self):
        args = request.httprequest.args
        configured_token = str(self._parameter("meta_verify_token") or "")
        supplied_token = str(args.get("hub.verify_token") or "")
        if (
            args.get("hub.mode") == "subscribe"
            and configured_token
            and hmac.compare_digest(configured_token, supplied_token)
        ):
            return request.make_response(
                str(args.get("hub.challenge") or ""),
                headers=[("Content-Type", "text/plain; charset=utf-8")],
                status=200,
            )
        return request.make_response(
            "Webhook verification failed.",
            status=403,
        )

    def _receive_event(self):
        enabled = str(self._parameter("meta_enabled", "False")).lower()
        if enabled not in ("true", "1", "yes"):
            return request.make_response(
                "Meta Lead Ads integration is disabled.",
                status=503,
            )

        raw_body = request.httprequest.get_data(cache=True) or b""
        app_secret = str(self._parameter("meta_app_secret") or "")
        signature = request.httprequest.headers.get(
            "X-Hub-Signature-256",
            "",
        )
        expected_signature = "sha256=%s" % hmac.new(
            app_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest() if app_secret else ""
        if not (
            signature
            and expected_signature
            and hmac.compare_digest(signature, expected_signature)
        ):
            return request.make_response(
                "Invalid webhook signature.",
                status=403,
            )

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return request.make_response("Invalid JSON payload.", status=400)
        if not isinstance(payload, dict):
            return request.make_response("Invalid webhook payload.", status=400)

        try:
            request.env[
                "brokerage.meta.webhook.event"
            ].sudo().enqueue_payload(payload)
        except Exception:
            # Returning a server error asks Meta to retry delivery. Never log
            # request headers because they contain the signed credential.
            _logger.exception("Could not persist a Meta Lead Ads webhook")
            return request.make_response(
                "Webhook event could not be queued.",
                status=500,
            )
        return request.make_response(
            "EVENT_RECEIVED",
            headers=[("Content-Type", "text/plain; charset=utf-8")],
            status=200,
        )
