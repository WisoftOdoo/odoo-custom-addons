import hmac
import logging

from odoo import http, _
from odoo.exceptions import ValidationError
from odoo.http import request


_logger = logging.getLogger(__name__)


class BrokerageTelephonyApi(http.Controller):
    @http.route(
        "/brokerage/api/v1/telephony/events/<string:provider_code>",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def receive_event(self, provider_code, **kwargs):
        provider = request.env[
            "brokerage.telephony.provider"
        ].sudo().search([
            ("code", "=", provider_code),
            ("active", "=", True),
        ], limit=1)
        if not provider:
            return self._error("Telephony provider not found.", 404)

        supplied_token = request.httprequest.headers.get(
            "X-Brokerage-Telephony-Token", ""
        )
        expected_token = provider.webhook_token or ""
        if not supplied_token or not hmac.compare_digest(
            supplied_token,
            expected_token,
        ):
            return self._error("Invalid telephony webhook token.", 401)

        payload = request.httprequest.get_json(silent=True)
        if not isinstance(payload, dict):
            return self._error(
                "Request body must be a JSON object.",
                400,
            )
        try:
            with request.env.cr.savepoint():
                event, duplicate = request.env[
                    "brokerage.telephony.event"
                ].sudo().process_payload(provider, payload)
        except ValidationError as error:
            return self._error(str(error), 422)
        except Exception:
            _logger.exception(
                "Unexpected telephony event error for provider %s",
                provider.id,
            )
            return self._error(
                "The telephony event could not be processed.",
                500,
            )

        call = event.call_id
        return request.make_json_response({
            "success": True,
            "duplicate": duplicate,
            "event_id": event.event_id,
            "call": {
                "id": call.id,
                "reference": call.name,
                "external_call_id": call.external_call_id,
                "state": call.state,
                "ring_duration_seconds": call.ring_duration_seconds,
                "talk_duration_seconds": call.talk_duration_seconds,
                "total_duration_seconds": call.total_duration_seconds,
            },
        }, status=200)

    @staticmethod
    def _error(message, status):
        return request.make_json_response({
            "success": False,
            "error": {"message": _(message)},
        }, status=status)
