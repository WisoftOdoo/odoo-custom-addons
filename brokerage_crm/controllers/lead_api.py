import logging

from psycopg2 import IntegrityError

from odoo import http, _
from odoo.exceptions import ValidationError
from odoo.http import request


_logger = logging.getLogger(__name__)


class BrokerageLeadApi(http.Controller):
    @http.route(
        "/brokerage/api/v1/leads",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def create_lead(self, **kwargs):
        payload = request.httprequest.get_json(silent=True)
        if not isinstance(payload, dict):
            return self._error("Request body must be a JSON object.", 400)

        customer_name = str(
            payload.get("customer_name") or payload.get("contact_name") or ""
        ).strip()
        phone = str(payload.get("phone") or payload.get("mobile") or "").strip()
        source_name = str(payload.get("source") or "Meta").strip()
        if not customer_name:
            return self._error("customer_name is required.", 400)
        if not phone:
            return self._error("phone is required.", 400)
        if not source_name:
            return self._error("source is required.", 400)

        source = request.env["utm.source"].sudo().search([
            ("name", "=ilike", source_name),
            ("round_robin_applicable", "=", True),
        ], limit=1)
        if not source:
            return self._error(
                "An active Round Robin lead source with this name was not found.",
                404,
            )

        team = request.env["crm.team"].sudo().browse()
        if payload.get("team_id") not in (None, False, ""):
            try:
                team_id = int(payload["team_id"])
            except (TypeError, ValueError):
                return self._error("team_id must be an integer.", 400)
            team = request.env["crm.team"].sudo().browse(team_id).exists()
            if not team or not team.active:
                return self._error("The requested Sales Team was not found or is inactive.", 404)

        external_lead_id = str(payload.get("external_lead_id") or "").strip()
        if external_lead_id:
            existing = self._find_duplicate(source, external_lead_id)
            if existing:
                return self._success(existing, duplicate=True, status=200)

        email = str(payload.get("email") or "").strip()
        lead_name = str(payload.get("name") or "").strip()
        description = str(payload.get("notes") or payload.get("description") or "").strip()
        values = {
            "name": lead_name or f"{source.display_name} - {customer_name}",
            "contact_name": customer_name,
            "phone": phone,
            "email_from": email or False,
            "description": description or False,
            "source_id": source.id,
            "external_lead_id": external_lead_id or False,
            "assignment_type": "round_robin",
            # External brokerage enquiries are worked directly in the CRM
            # pipeline; Odoo's separate lead qualification screen is not used.
            "type": "opportunity",
        }
        if team:
            values["team_id"] = team.id

        try:
            with request.env.cr.savepoint():
                lead = request.env["crm.lead"].sudo().create(values)
        except IntegrityError:
            if external_lead_id:
                existing = self._find_duplicate(source, external_lead_id)
                if existing:
                    return self._success(existing, duplicate=True, status=200)
            _logger.exception("Unique constraint failure while creating external lead")
            return self._error("The lead could not be created.", 409)
        except ValidationError as error:
            return self._error(str(error), 422)
        except Exception:
            _logger.exception("Unexpected error while creating an external lead")
            return self._error("The lead could not be created.", 500)

        return self._success(lead, duplicate=False, status=201)

    @staticmethod
    def _find_duplicate(source, external_lead_id):
        return request.env["crm.lead"].sudo().search([
            ("source_id", "=", source.id),
            ("external_lead_id", "=", external_lead_id),
        ], limit=1)

    @staticmethod
    def _success(lead, duplicate, status):
        return request.make_json_response({
            "success": True,
            "duplicate": duplicate,
            "lead": {
                "id": lead.id,
                "name": lead.name,
                "type": lead.type,
                "salesperson_id": lead.user_id.id or None,
                "salesperson": lead.user_id.display_name or None,
                "team_id": lead.team_id.id or None,
                "team": lead.team_id.display_name or None,
                "stage_id": lead.stage_id.id or None,
                "stage": lead.stage_id.display_name or None,
                "assigned_datetime": lead.assigned_datetime.isoformat()
                if lead.assigned_datetime else None,
            },
        }, status=status)

    @staticmethod
    def _error(message, status):
        return request.make_json_response({
            "success": False,
            "error": {"message": _(message)},
        }, status=status)
