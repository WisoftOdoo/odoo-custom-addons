import re

from odoo import api, fields, models


class BrokerageCrmMeetingType(models.Model):
    _name = "brokerage.crm.meeting.type"
    _description = "CRM Meeting Type"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True, copy=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    location_mode = fields.Selection(
        selection=[
            ("location", "Physical Location Required"),
            ("online", "Online Meeting Link Required"),
            ("none", "No Location or Link Required"),
        ],
        required=True,
        default="location",
        string="Meeting Location Requirement",
    )

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The meeting type code must be unique.",
    )

    @api.model
    def _available_code(self, name):
        base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
        base = base or "meeting_type"
        candidate = base
        suffix = 2
        while self.with_context(active_test=False).search_count([
            ("code", "=", candidate),
        ]):
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code"):
                vals["code"] = self._available_code(vals.get("name"))
        return super().create(vals_list)

    def write(self, vals):
        if "code" in vals and not vals["code"]:
            vals["code"] = self._available_code(
                vals.get("name") or self[:1].name
            )
        return super().write(vals)

