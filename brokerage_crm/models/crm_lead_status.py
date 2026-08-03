from odoo import fields, models


class BrokerageCrmLeadStatus(models.Model):
    _name = "brokerage.crm.lead.status"
    _description = "Brokerage CRM Lead Status"
    _order = "sequence, name, id"

    name = fields.Char(
        required=True,
        translate=True,
    )

    code = fields.Char(
        required=True,
        index=True,
        copy=False,
    )

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer()

    requires_remarks = fields.Boolean(
        string="Require Remarks",
    )

    requires_next_activity = fields.Boolean(
        string="Require Next Activity",
    )

    is_contact_attempt = fields.Boolean(
        string="Contact Attempt Status",
    )

    is_successful_contact = fields.Boolean(
        string="Successful Contact",
    )

    is_invalid = fields.Boolean(
        string="Invalid Lead Status",
    )

    allowed_stage_ids = fields.Many2many(
        comodel_name="crm.stage",
        relation="brokerage_status_stage_rel",
        column1="status_id",
        column2="stage_id",
        string="Allowed Stages",
    )

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The lead status code must be unique.",
    )

    _code_not_empty = models.Constraint(
        "CHECK(code IS NOT NULL AND length(trim(code)) > 0)",
        "The lead status code cannot be empty.",
    )
