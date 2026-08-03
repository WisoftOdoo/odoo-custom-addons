import re

from odoo import api, fields, models, _


class BrokerageCrmContactMethod(models.Model):
    _name = "brokerage.crm.contact.method"
    _description = "CRM Contact Method"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True, copy=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The contact method code must be unique.",
    )

    @api.model
    def _available_code(self, name):
        base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
        base = base or "contact_method"
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

