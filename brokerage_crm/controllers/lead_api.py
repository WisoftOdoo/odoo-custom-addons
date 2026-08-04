import logging

from psycopg2 import IntegrityError

from odoo import http, tools, _
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

        has_explicit_customer_name = bool(
            payload.get("customer_name") or payload.get("contact_name")
        )
        customer_name = str(
            payload.get("customer_name")
            or payload.get("contact_name")
            or payload.get("name")
            or ""
        ).strip()
        phone = str(
            payload.get("phone")
            or payload.get("mobile")
            or payload.get("mobile_number")
            or ""
        ).strip()
        email = str(
            payload.get("email") or payload.get("email_from") or ""
        ).strip()
        source_name = str(
            payload.get("source") or payload.get("utm_source") or ""
        ).strip()
        assignment_type = str(
            payload.get("assignment_type") or ""
        ).strip().lower()
        if not customer_name:
            return self._error("name or customer_name is required.", 400)
        if not email:
            return self._error("email is required.", 400)
        if not phone:
            return self._error("phone is required.", 400)
        if not source_name:
            return self._error("source is required.", 400)
        if not assignment_type:
            return self._error("assignment_type is required.", 400)
        if assignment_type not in {"manual", "round_robin"}:
            return self._error(
                "assignment_type must be either 'manual' or 'round_robin'.",
                400,
            )

        source = request.env["utm.source"].sudo().search([
            ("name", "=ilike", source_name),
        ], limit=1)
        if not source:
            return self._error(
                "A lead source with this name was not found.",
                404,
            )

        campaign = self._find_or_create_utm(
            "utm.campaign",
            payload.get("campaign")
            or payload.get("campaign_name")
            or payload.get("utm_campaign"),
        )
        medium = self._find_or_create_utm(
            "utm.medium",
            payload.get("medium")
            or payload.get("medium_name")
            or payload.get("utm_medium"),
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

        duplicate_key = request.env[
            "crm.lead"
        ].sudo()._brokerage_build_deduplication_key(
            customer_name,
            email,
            phone,
        )
        # Serialize requests for the same customer identity. This prevents two
        # simultaneous webhooks from both passing the search before either one
        # commits its new lead.
        request.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [duplicate_key],
        )
        existing = self._find_duplicate(
            duplicate_key,
            customer_name,
            email,
        )
        if existing:
            try:
                with request.env.cr.savepoint():
                    duplicate_action = existing._brokerage_handle_duplicate_enquiry(
                        source,
                        campaign,
                        medium,
                        customer_name,
                        email,
                        phone,
                        assignment_type,
                    )
            except ValidationError as error:
                return self._error(str(error), 422)
            except Exception:
                _logger.exception(
                    "Unexpected error while processing a repeat enquiry"
                )
                return self._error(
                    "The repeat enquiry could not be processed.",
                    500,
                )
            return self._success(
                existing,
                duplicate=True,
                status=200,
                duplicate_action=duplicate_action,
            )

        lead_name = str(
            payload.get("lead_name")
            or (payload.get("name") if has_explicit_customer_name else "")
            or ""
        ).strip()
        description = str(payload.get("notes") or payload.get("description") or "").strip()
        values = {
            "name": lead_name or f"{source.display_name} - {customer_name}",
            "contact_name": customer_name,
            "phone": phone,
            "email_from": email or False,
            "description": description or False,
            "source_id": source.id,
            "campaign_id": campaign.id or False,
            "medium_id": medium.id or False,
            "assignment_type": assignment_type,
            # Do not let a public API request inherit Odoo's Public user or
            # the public user's default Sales Team.
            "user_id": False,
            "team_id": team.id if team else False,
            # External brokerage enquiries are worked directly in the CRM
            # pipeline; Odoo's separate lead qualification screen is not used.
            "type": "opportunity",
        }
        if assignment_type == "manual":
            new_stage = self._find_new_lead_stage(team)
            if not new_stage:
                return self._error(
                    "Configure a New Lead CRM stage before creating manual leads.",
                    422,
                )
            values["stage_id"] = new_stage.id

        try:
            with request.env.cr.savepoint():
                lead = request.env["crm.lead"].sudo().create(values)
        except IntegrityError:
            existing = self._find_duplicate(
                duplicate_key,
                customer_name,
                email,
            )
            if existing:
                return self._success(
                    existing,
                    duplicate=True,
                    status=200,
                    duplicate_action="active_duplicate",
                )
            _logger.exception("Unique constraint failure while creating external lead")
            return self._error("The lead could not be created.", 409)
        except ValidationError as error:
            return self._error(str(error), 422)
        except Exception:
            _logger.exception("Unexpected error while creating an external lead")
            return self._error("The lead could not be created.", 500)

        return self._success(lead, duplicate=False, status=201)

    @staticmethod
    def _find_duplicate(duplicate_key, customer_name, email):
        lead_model = request.env["crm.lead"].sudo().with_context(
            active_test=False,
        )
        existing = lead_model.search([
            ("brokerage_deduplication_key", "=", duplicate_key),
        ], order="id", limit=1)
        if existing:
            return existing

        # Compatibility fallback for records whose stored key was generated
        # by the previous name+email+phone algorithm. It can be removed after
        # all databases have recomputed the field at least once.
        normalized_email = tools.email_normalize(str(email or "").strip())
        if not normalized_email:
            return lead_model.browse()
        candidates = lead_model.search([
            ("email_normalized", "=", normalized_email),
        ], order="id")
        for candidate in candidates:
            current_key = candidate._brokerage_build_deduplication_key(
                customer_name,
                candidate.email_from,
                candidate.phone,
                candidate.company_id,
            )
            if current_key == duplicate_key:
                candidate._compute_brokerage_deduplication_key()
                return candidate
        return lead_model.browse()

    @staticmethod
    def _find_or_create_utm(model_name, value):
        name = str(value or "").strip()
        if not name:
            return request.env[model_name].sudo().browse()
        return request.env["utm.mixin"].sudo()._find_or_create_record(
            model_name,
            name,
        )

    @staticmethod
    def _find_new_lead_stage(team):
        stage_model = request.env["crm.stage"].sudo()
        domain = [("brokerage_code", "=", "new")]
        if team:
            return stage_model.search(
                domain + [
                    "|",
                    ("team_ids", "=", False),
                    ("team_ids", "in", team.ids),
                ],
                order="sequence, id",
                limit=1,
            )
        # Unassigned API leads may use the configured brokerage New Lead
        # stage even when that stage is limited to operational sales teams.
        return stage_model.search(domain, order="sequence, id", limit=1)

    @staticmethod
    def _success(lead, duplicate, status, duplicate_action=None):
        return request.make_json_response({
            "success": True,
            "duplicate": duplicate,
            "duplicate_action": duplicate_action,
            "lead": {
                "id": lead.id,
                "name": lead.name,
                "type": lead.type,
                "assignment_type": lead.assignment_type,
                "source_id": lead.source_id.id or None,
                "source": lead.source_id.display_name or None,
                "campaign_id": lead.campaign_id.id or None,
                "campaign": lead.campaign_id.display_name or None,
                "medium_id": lead.medium_id.id or None,
                "medium": lead.medium_id.display_name or None,
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
