from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    available_for_crm_assignment = fields.Boolean(
        string="Available for CRM Assignment",
        default=True,
        help=(
            "Disable this option to temporarily exclude this user "
            "from automatic CRM Round Robin assignment."
        ),
    )