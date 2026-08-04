from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    brokerage_normal_rr_next_rule_id = fields.Many2one(
        comodel_name="brokerage.crm.round.robin",
        string="Next Normal Round Robin Team",
        ondelete="set null",
        copy=False,
        help=(
            "Persistent cursor for the next team in the normal new-lead "
            "Round Robin. Reassignment queues keep their own independent "
            "count-based state."
        ),
    )

    brokerage_telephony_provider_id = fields.Many2one(
        comodel_name="brokerage.telephony.provider",
        string="Default Brokerage Telephony Provider",
        ondelete="restrict",
        check_company=True,
    )
