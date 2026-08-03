import uuid
from datetime import timezone

from dateutil.parser import isoparse
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class BrokerageTelephonyCall(models.Model):
    _name = "brokerage.telephony.call"
    _description = "Brokerage Telephony Call"
    _order = "started_at desc, create_date desc, id desc"

    name = fields.Char(required=True, readonly=True, copy=False)
    provider_id = fields.Many2one(
        comodel_name="brokerage.telephony.provider",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
    )
    company_id = fields.Many2one(
        related="provider_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    request_uid = fields.Char(
        required=True,
        readonly=True,
        copy=False,
        index=True,
        default=lambda self: str(uuid.uuid4()),
    )
    external_call_id = fields.Char(readonly=True, copy=False, index=True)
    external_parent_call_id = fields.Char(readonly=True, copy=False, index=True)
    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        readonly=True,
        ondelete="set null",
        index=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        readonly=True,
        ondelete="set null",
        index=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
    )
    direction = fields.Selection(
        selection=[
            ("outgoing", "Outgoing"),
            ("incoming", "Incoming"),
        ],
        required=True,
        default="outgoing",
        readonly=True,
        index=True,
    )
    state = fields.Selection(
        selection=[
            ("initiated", "Initiated"),
            ("ringing", "Ringing"),
            ("answered", "Answered"),
            ("completed", "Completed"),
            ("missed", "Missed"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="initiated",
        readonly=True,
        index=True,
    )
    from_number = fields.Char(readonly=True)
    to_number = fields.Char(required=True, readonly=True)
    agent_extension = fields.Char(required=True, readonly=True, index=True)
    agent_device_id = fields.Char(readonly=True)
    started_at = fields.Datetime(readonly=True, index=True)
    answered_at = fields.Datetime(readonly=True, index=True)
    ended_at = fields.Datetime(readonly=True, index=True)
    ring_duration_seconds = fields.Integer(readonly=True)
    talk_duration_seconds = fields.Integer(readonly=True)
    total_duration_seconds = fields.Integer(readonly=True)
    termination_reason = fields.Char(readonly=True)
    recording_url = fields.Char(readonly=True)
    initiation_error = fields.Text(readonly=True)
    provider_response = fields.Json(readonly=True)
    event_ids = fields.One2many(
        comodel_name="brokerage.telephony.event",
        inverse_name="call_id",
        readonly=True,
    )
    event_count = fields.Integer(compute="_compute_event_count")

    _provider_request_unique = models.Constraint(
        "UNIQUE(provider_id, request_uid)",
        "This provider call request already exists.",
    )
    _provider_external_call_unique = models.Constraint(
        "UNIQUE(provider_id, external_call_id)",
        "This provider call has already been imported.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            values.setdefault(
                "name",
                self.env["ir.sequence"].next_by_code(
                    "brokerage.telephony.call"
                ) or _("New Call"),
            )
        return super().create(vals_list)

    @api.depends("event_ids")
    def _compute_event_count(self):
        for call in self:
            call.event_count = len(call.event_ids)

    @api.constrains("started_at", "answered_at", "ended_at")
    def _check_call_timeline(self):
        for call in self:
            if (
                call.started_at
                and call.answered_at
                and call.answered_at < call.started_at
            ):
                raise ValidationError(_(
                    "Answered time cannot be earlier than call start time."
                ))
            if (
                call.answered_at
                and call.ended_at
                and call.ended_at < call.answered_at
            ):
                raise ValidationError(_(
                    "Call end time cannot be earlier than answered time."
                ))
            if (
                call.started_at
                and call.ended_at
                and call.ended_at < call.started_at
            ):
                raise ValidationError(_(
                    "Call end time cannot be earlier than call start time."
                ))

    @api.model
    def create_outbound_for_lead(self, lead, user, provider):
        lead.ensure_one()
        user.ensure_one()
        provider.ensure_one()
        number = lead.phone
        if not number:
            raise ValidationError(_(
                "Enter the customer's Phone before calling."
            ))
        if not user.telephony_extension:
            raise ValidationError(_(
                "Configure a PBX extension on the salesperson's user profile."
            ))
        call = self.sudo().create({
            "provider_id": provider.id,
            "lead_id": lead.id,
            "partner_id": lead.partner_id.id or False,
            "user_id": user.id,
            "direction": "outgoing",
            "state": "initiated",
            "from_number": user.telephony_extension,
            "to_number": number,
            "agent_extension": user.telephony_extension,
            "agent_device_id": user.telephony_device_id or False,
            "started_at": fields.Datetime.now(),
        })
        try:
            result = provider.initiate_call(call)
        except ValidationError as error:
            call.write({
                "state": "failed",
                "ended_at": fields.Datetime.now(),
                "termination_reason": _("Outbound request failed"),
                "initiation_error": str(error),
            })
            return call

        values = {
            "state": result.get("state") or "initiated",
            "external_call_id": result.get("external_call_id") or False,
            "provider_response": result.get("response") or {},
            "initiation_error": False,
        }
        call.write(values)
        lead.sudo().message_post(
            body=Markup(_(
                "<b>PBX call requested</b><br/>"
                "Agent: %(agent)s<br/>"
                "Customer number: %(number)s<br/>"
                "Call reference: %(reference)s"
            )) % {
                "agent": user.display_name,
                "number": number,
                "reference": call.name,
            },
            subtype_xmlid="mail.mt_note",
            author_id=user.partner_id.id,
        )
        return call

    @api.model
    def _parse_event_datetime(self, value, label):
        if not value:
            return False
        if isinstance(value, str):
            try:
                parsed = isoparse(value)
            except (TypeError, ValueError) as error:
                raise ValidationError(_(
                    "%(label)s must be an ISO-8601 date/time."
                ) % {"label": label}) from error
        else:
            parsed = fields.Datetime.to_datetime(value)
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    @api.model
    def _duration_value(self, payload, key, start=False, end=False):
        value = payload.get(key)
        if value not in (None, False, ""):
            try:
                duration = int(float(value))
            except (TypeError, ValueError) as error:
                raise ValidationError(_(
                    "%s must be a non-negative number of seconds."
                ) % key) from error
            if duration < 0:
                raise ValidationError(_(
                    "%s must be a non-negative number of seconds."
                ) % key)
            return duration
        if start and end:
            return max(0, int((end - start).total_seconds()))
        return 0

    @api.model
    def _state_rank(self, state):
        return {
            "initiated": 10,
            "ringing": 20,
            "answered": 30,
            "completed": 40,
            "missed": 40,
            "failed": 40,
            "cancelled": 40,
        }.get(state, 0)

    @api.model
    def _prepare_event_values(self, call, provider, payload):
        state = provider._normalize_provider_state(
            payload.get("status") or payload.get("state")
        )
        current_terminal = call.state in (
            "completed", "missed", "failed", "cancelled"
        )
        if (
            current_terminal
            or self._state_rank(state) < self._state_rank(call.state)
        ):
            state = call.state

        started_at = self._parse_event_datetime(
            payload.get("started_at") or payload.get("time_start"),
            _("started_at"),
        ) or call.started_at
        answered_at = self._parse_event_datetime(
            payload.get("answered_at") or payload.get("time_answered"),
            _("answered_at"),
        ) or call.answered_at
        ended_at = self._parse_event_datetime(
            payload.get("ended_at") or payload.get("time_end"),
            _("ended_at"),
        ) or call.ended_at

        values = {
            "state": state,
            "started_at": started_at,
            "answered_at": answered_at,
            "ended_at": ended_at,
            "termination_reason": (
                payload.get("termination_reason")
                or payload.get("reason")
                or call.termination_reason
            ),
            "recording_url": (
                payload.get("recording_url") or call.recording_url
            ),
            "external_parent_call_id": (
                payload.get("parent_call_id")
                or payload.get("call_history_id")
                or call.external_parent_call_id
            ),
        }
        if not call.external_call_id and payload.get("external_call_id"):
            values["external_call_id"] = str(
                payload["external_call_id"]
            )
        values.update({
            "ring_duration_seconds": self._duration_value(
                payload,
                "ring_duration_seconds",
                started_at,
                answered_at or ended_at,
            ),
            "talk_duration_seconds": self._duration_value(
                payload,
                "talk_duration_seconds",
                answered_at,
                ended_at,
            ),
            "total_duration_seconds": self._duration_value(
                payload,
                "total_duration_seconds",
                started_at,
                ended_at,
            ),
        })
        return values

    @api.model
    def _find_user_for_event(self, provider, payload):
        extension = str(
            payload.get("agent_extension") or ""
        ).strip()
        if not extension:
            return self.env["res.users"]
        return self.env["res.users"].sudo().search([
            ("active", "=", True),
            ("telephony_extension", "=", extension),
            "|",
            ("telephony_provider_id", "=", provider.id),
            "&",
            ("telephony_provider_id", "=", False),
            ("company_id.brokerage_telephony_provider_id", "=", provider.id),
        ], limit=1)

    @api.model
    def _find_or_create_from_event(self, provider, payload):
        request_uid = str(payload.get("request_id") or "").strip()
        external_call_id = str(
            payload.get("external_call_id")
            or payload.get("call_id")
            or ""
        ).strip()
        call = self.sudo().browse()
        if request_uid:
            call = self.sudo().search([
                ("provider_id", "=", provider.id),
                ("request_uid", "=", request_uid),
            ], limit=1)
        if not call and external_call_id:
            call = self.sudo().search([
                ("provider_id", "=", provider.id),
                ("external_call_id", "=", external_call_id),
            ], limit=1)
        if call:
            return call
        if not external_call_id:
            raise ValidationError(_(
                "An unknown call event must include external_call_id."
            ))

        user = self._find_user_for_event(provider, payload)
        if not user:
            raise ValidationError(_(
                "No active Odoo user matches agent_extension %(extension)s "
                "for this provider."
            ) % {
                "extension": payload.get("agent_extension") or "-",
            })
        lead = self.env["crm.lead"].sudo().browse()
        if payload.get("lead_id"):
            try:
                lead = self.env["crm.lead"].sudo().browse(
                    int(payload["lead_id"])
                ).exists()
            except (TypeError, ValueError):
                raise ValidationError(_("lead_id must be an integer."))

        direction = payload.get("direction") or "incoming"
        if direction not in ("incoming", "outgoing"):
            raise ValidationError(_(
                "direction must be incoming or outgoing."
            ))
        to_number = str(payload.get("to_number") or "").strip()
        from_number = str(payload.get("from_number") or "").strip()
        customer_number = (
            from_number if direction == "incoming" else to_number
        )
        if not customer_number:
            raise ValidationError(_(
                "The event must include the customer phone number."
            ))
        return self.sudo().create({
            "provider_id": provider.id,
            "external_call_id": external_call_id,
            "external_parent_call_id": (
                payload.get("parent_call_id")
                or payload.get("call_history_id")
                or False
            ),
            "lead_id": lead.id or False,
            "partner_id": lead.partner_id.id or False,
            "user_id": user.id,
            "direction": direction,
            "state": "initiated",
            "from_number": from_number or False,
            "to_number": to_number or customer_number,
            "agent_extension": user.telephony_extension,
            "agent_device_id": payload.get("agent_device_id") or False,
        })

    def action_view_events(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Telephony Events"),
            "res_model": "brokerage.telephony.event",
            "view_mode": "list,form",
            "domain": [("call_id", "=", self.id)],
            "context": {
                "create": False,
                "edit": False,
                "delete": False,
            },
        }


class BrokerageTelephonyEvent(models.Model):
    _name = "brokerage.telephony.event"
    _description = "Brokerage Telephony Event"
    _order = "received_at desc, id desc"

    provider_id = fields.Many2one(
        comodel_name="brokerage.telephony.provider",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
    )
    call_id = fields.Many2one(
        comodel_name="brokerage.telephony.call",
        required=True,
        readonly=True,
        ondelete="cascade",
        index=True,
    )
    event_id = fields.Char(required=True, readonly=True, copy=False, index=True)
    event_type = fields.Char(readonly=True)
    received_at = fields.Datetime(
        required=True,
        readonly=True,
        default=fields.Datetime.now,
        index=True,
    )
    payload = fields.Json(required=True, readonly=True)

    _provider_event_unique = models.Constraint(
        "UNIQUE(provider_id, event_id)",
        "This telephony event has already been processed.",
    )

    @api.model
    def process_payload(self, provider, payload):
        provider.ensure_one()
        if not isinstance(payload, dict):
            raise ValidationError(_("The event body must be a JSON object."))
        event_id = str(payload.get("event_id") or "").strip()
        if not event_id:
            raise ValidationError(_("event_id is required."))
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            ["brokerage.telephony.event:%s:%s" % (
                provider.id,
                event_id,
            )],
        )
        existing = self.sudo().search([
            ("provider_id", "=", provider.id),
            ("event_id", "=", event_id),
        ], limit=1)
        if existing:
            return existing, True

        call_model = self.env["brokerage.telephony.call"]
        call = call_model._find_or_create_from_event(provider, payload)
        values = call_model._prepare_event_values(call, provider, payload)
        call.sudo().write(values)
        event = self.sudo().create({
            "provider_id": provider.id,
            "call_id": call.id,
            "event_id": event_id,
            "event_type": (
                payload.get("event_type")
                or payload.get("status")
                or payload.get("state")
                or "update"
            ),
            "payload": payload,
        })
        return event, False
