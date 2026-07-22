from odoo import fields, models


class UtmSource(models.Model):
    _inherit = "utm.source"

    brokerage_category = fields.Selection(
        selection=[
            ("marketing", "Marketing"),
            ("manual", "Manual"),
            ("referral", "Referral"),
            ("walk_in", "Walk-in"),
            ("bulk", "Bulk Upload"),
            ("developer", "Developer Referral"),
            ("other", "Other"),
        ],
        string="Brokerage Category",
        default="other",
        required=True,
    )

    round_robin_applicable = fields.Boolean(
        string="Apply Round Robin",
    )

    sla_applicable = fields.Boolean(
        string="Apply SLA",
        default=True,
    )

    penalty_applicable = fields.Boolean(
        string="Apply Penalty",
        default=True,
    )

    is_bulk_source = fields.Boolean(
        string="Bulk Upload Source",
    )

    default_team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Default Sales Team",
    )

    require_direct_assignment = fields.Boolean(
        string="Require Direct Assignment",
        help="The user must select the salesperson for this source.",
    )