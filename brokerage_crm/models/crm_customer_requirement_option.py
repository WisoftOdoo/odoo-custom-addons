import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class BrokerageCrmCustomerRequirementOption(models.Model):
    _name = "brokerage.crm.customer.requirement.option"
    _description = "CRM Customer Requirement Option"
    _order = "option_type, sequence, name, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True, copy=False)
    option_type = fields.Selection(
        selection=[
            ("requirement_type", "Requirement Type"),
            ("property_category", "Property Category"),
            ("bedroom_count", "Bedroom Count"),
            ("purchase_timeline", "Purchase Timeline"),
            ("buyer_type", "Buyer Type"),
            ("purchase_mode", "Purchase Mode"),
        ],
        required=True,
        index=True,
        default=lambda self: self.env.context.get("default_option_type"),
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _type_code_unique = models.Constraint(
        "UNIQUE(option_type, code)",
        "The option code must be unique inside each option type.",
    )

    @api.model
    def _available_code(self, option_type, name):
        base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
        base = base or "option"
        candidate = base
        suffix = 2
        while self.with_context(active_test=False).search_count([
            ("option_type", "=", option_type),
            ("code", "=", candidate),
        ]):
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    @api.model_create_multi
    def create(self, vals_list):
        default_type = self.env.context.get("default_option_type")
        for vals in vals_list:
            vals.setdefault("option_type", default_type)
            if not vals.get("code"):
                vals["code"] = self._available_code(
                    vals.get("option_type"),
                    vals.get("name"),
                )
        return super().create(vals_list)

    def write(self, vals):
        if "code" in vals and not vals["code"]:
            self.ensure_one()
            vals = dict(vals)
            vals["code"] = self._available_code(
                vals.get("option_type") or self.option_type,
                vals.get("name") or self.name,
            )
        return super().write(vals)


class CrmLeadCustomerRequirementOptions(models.Model):
    _inherit = "crm.lead"

    requirement_type_id = fields.Many2one(
        comodel_name="brokerage.crm.customer.requirement.option",
        string="Requirement Type",
        tracking=True,
        ondelete="restrict",
        domain=[("option_type", "=", "requirement_type")],
    )
    property_category_id = fields.Many2one(
        comodel_name="brokerage.crm.customer.requirement.option",
        string="Property Category",
        tracking=True,
        ondelete="restrict",
        domain=[("option_type", "=", "property_category")],
    )
    bedroom_count_id = fields.Many2one(
        comodel_name="brokerage.crm.customer.requirement.option",
        string="Bedroom Count",
        tracking=True,
        ondelete="restrict",
        domain=[("option_type", "=", "bedroom_count")],
    )
    purchase_timeline_id = fields.Many2one(
        comodel_name="brokerage.crm.customer.requirement.option",
        string="Purchase Timeline",
        tracking=True,
        ondelete="restrict",
        domain=[("option_type", "=", "purchase_timeline")],
    )
    buyer_type_id = fields.Many2one(
        comodel_name="brokerage.crm.customer.requirement.option",
        string="Buyer Type",
        tracking=True,
        ondelete="restrict",
        domain=[("option_type", "=", "buyer_type")],
    )
    purchase_mode_id = fields.Many2one(
        comodel_name="brokerage.crm.customer.requirement.option",
        string="Purchase Mode",
        tracking=True,
        ondelete="restrict",
        domain=[("option_type", "=", "purchase_mode")],
    )

    _customer_requirement_option_fields = (
        ("requirement_type", "requirement_type_id", "requirement_type"),
        ("property_category", "property_category_id", "property_category"),
        ("bedroom_count", "bedroom_count_id", "bedroom_count"),
        ("purchase_timeline", "purchase_timeline_id", "purchase_timeline"),
        ("buyer_type", "buyer_type_id", "buyer_type"),
        ("purchase_mode", "purchase_mode_id", "purchase_mode"),
    )

    @api.model
    def _prepare_customer_requirement_option_values(self, values):
        values = dict(values)
        option_model = self.env[
            "brokerage.crm.customer.requirement.option"
        ].with_context(active_test=False)
        for legacy_field, option_field, option_type in (
            self._customer_requirement_option_fields
        ):
            if option_field in values:
                option = option_model.browse(values.get(option_field)).exists()
                allowed_values = dict(self._fields[legacy_field].selection)
                values[legacy_field] = (
                    option.code
                    if (
                        option
                        and option.option_type == option_type
                        and option.code in allowed_values
                    )
                    else False
                )
            elif legacy_field in values:
                legacy_value = values.get(legacy_field)
                option = option_model.search([
                    ("option_type", "=", option_type),
                    ("code", "=", legacy_value),
                ], limit=1) if legacy_value else option_model
                values[option_field] = option.id or False
        return values

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([
            self._prepare_customer_requirement_option_values(values)
            for values in vals_list
        ])

    def write(self, values):
        return super().write(
            self._prepare_customer_requirement_option_values(values)
        )

    @api.constrains(
        "requirement_type_id",
        "property_category_id",
        "bedroom_count_id",
        "purchase_timeline_id",
        "buyer_type_id",
        "purchase_mode_id",
    )
    def _check_customer_requirement_option_types(self):
        for lead in self:
            for _legacy_field, option_field, option_type in (
                self._customer_requirement_option_fields
            ):
                option = lead[option_field]
                if option and option.option_type != option_type:
                    raise ValidationError(_(
                        "%(option)s is not valid for %(field)s.",
                        option=option.display_name,
                        field=lead._fields[option_field].string,
                    ))

    @api.model
    def _brokerage_migrate_customer_requirement_options(self):
        option_model = self.env[
            "brokerage.crm.customer.requirement.option"
        ].sudo().with_context(active_test=False)
        lead_model = self.sudo().with_context(
            active_test=False,
            tracking_disable=True,
        )
        for legacy_field, option_field, option_type in (
            self._customer_requirement_option_fields
        ):
            options = option_model.search([("option_type", "=", option_type)])
            for option in options:
                leads = lead_model.search([
                    (legacy_field, "=", option.code),
                    (option_field, "=", False),
                ])
                if leads:
                    leads.write({option_field: option.id})
        return True
