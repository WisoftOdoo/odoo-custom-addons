from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class BrokerageCrmContactAttempt(models.Model):
    _name = "brokerage.crm.contact.attempt"
    _description = "CRM Contact Attempt"
    _order = "attempt_datetime desc, id desc"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        string="Lead / Opportunity",
        required=True,
        ondelete="cascade",
        index=True,
    )

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Performed By",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
    )

    attempt_datetime = fields.Datetime(
        string="Attempt Date/Time",
        required=True,
        default=fields.Datetime.now,
        index=True,
    )

    method = fields.Selection(
        string="Legacy Method",
        selection=[
            ("call", "Phone Call"),
            ("whatsapp", "WhatsApp"),
            ("email", "Email"),
            ("sms", "SMS"),
            ("other", "Other"),
        ],
        default="call",
        index=True,
        help="Legacy compatibility value. Use Contact Method for new records.",
    )

    method_id = fields.Many2one(
        comodel_name="brokerage.crm.contact.method",
        string="Method",
        default=lambda self: self.env.ref(
            "brokerage_crm.contact_method_phone_call",
            raise_if_not_found=False,
        ),
        ondelete="restrict",
        index=True,
    )

    status_id = fields.Many2one(
        comodel_name="brokerage.crm.lead.status",
        string="Resulting Status",
        required=True,
        domain=(
            "['|', ('is_contact_attempt', '=', True), "
            "('code', '=', 'not_interested')]"
        ),
        ondelete="restrict",
    )

    successful_contact = fields.Boolean(
        related="status_id.is_successful_contact",
        store=True,
        readonly=True,
        index=True,
    )

    remarks = fields.Text()

    next_activity_type_id = fields.Many2one(
        comodel_name="mail.activity.type",
        string="Next Activity Type",
        ondelete="restrict",
    )

    next_activity_date = fields.Datetime(
        string="Next Activity Date & Time",
        help="The exact follow-up time selected when this attempt was recorded.",
    )

    activity_id = fields.Many2one(
        comodel_name="mail.activity",
        string="Created Activity",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    @api.model
    def _method_from_legacy_code(self, code):
        return self.env["brokerage.crm.contact.method"].search([
            ("code", "=", code or "call"),
        ], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        legacy_codes = dict(self._fields["method"].selection)
        for vals in vals_list:
            if vals.get("method_id"):
                method = self.env["brokerage.crm.contact.method"].browse(
                    vals["method_id"]
                )
                vals.setdefault(
                    "method",
                    method.code if method.code in legacy_codes else "other",
                )
            elif vals.get("method"):
                method = self._method_from_legacy_code(vals["method"])
                if method:
                    vals["method_id"] = method.id
        return super().create(vals_list)

    def write(self, vals):
        legacy_codes = dict(self._fields["method"].selection)
        if vals.get("method_id"):
            method = self.env["brokerage.crm.contact.method"].browse(
                vals["method_id"]
            )
            vals.setdefault(
                "method",
                method.code if method.code in legacy_codes else "other",
            )
        elif vals.get("method"):
            method = self._method_from_legacy_code(vals["method"])
            if method:
                vals["method_id"] = method.id
        return super().write(vals)

    @api.constrains(
        "status_id",
        "remarks",
        "next_activity_type_id",
        "next_activity_date",
    )
    def _check_status_requirements(self):
        for attempt in self:
            if (
                attempt.status_id.requires_remarks
                and not attempt.remarks
            ):
                raise ValidationError(
                    _("Remarks are required for the selected status.")
                )

            if attempt.status_id.requires_next_activity:
                if not attempt.next_activity_type_id:
                    raise ValidationError(
                        _("Next Activity Type is required.")
                    )

                if not attempt.next_activity_date:
                    raise ValidationError(
                        _("Next Activity Date & Time is required.")
                    )

            if (
                attempt.next_activity_date
                and attempt.next_activity_date
                < fields.Datetime.now()
            ):
                raise ValidationError(
                    _("Next Activity Date & Time cannot be in the past.")
                )

    @api.constrains("attempt_datetime")
    def _check_attempt_datetime(self):
        now = fields.Datetime.now()

        for attempt in self:
            if attempt.attempt_datetime and attempt.attempt_datetime > now:
                raise ValidationError(
                    _("Contact Attempt Date/Time cannot be in the future.")
                )
