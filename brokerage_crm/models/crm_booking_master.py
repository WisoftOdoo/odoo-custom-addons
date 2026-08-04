import re

from odoo import api, fields, models


class BrokerageCrmBookingPaymentMethod(models.Model):
    _name = "brokerage.crm.booking.payment.method"
    _description = "CRM Booking Payment Method"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True, copy=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The booking payment method code must be unique.",
    )

    @api.model
    def _available_code(self, name):
        base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
        base = base or "booking_payment_method"
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


class BrokerageCrmBookingDocumentationStatus(models.Model):
    _name = "brokerage.crm.booking.documentation.status"
    _description = "CRM Booking Documentation Status"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True, copy=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    allows_closing = fields.Boolean(
        string="Documentation Complete",
        help=(
            "When enabled, this status allows a fully documented booking "
            "to move to Closed Won."
        ),
    )

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The booking documentation status code must be unique.",
    )

    @api.model
    def _available_code(self, name):
        base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
        base = base or "booking_documentation_status"
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

    @api.model
    def _backfill_pending_booking_status(self):
        """Give pre-existing leads the same default as newly created leads."""
        pending = self.env.ref(
            "brokerage_crm.booking_documentation_status_pending",
            raise_if_not_found=False,
        )
        if pending:
            self.env["crm.lead"].with_context(active_test=False).search([
                ("booking_documentation_status_id", "=", False),
            ]).write({
                "booking_documentation_status_id": pending.id,
            })
