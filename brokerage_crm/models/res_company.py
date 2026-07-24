from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    brokerage_telephony_provider_id = fields.Many2one(
        comodel_name="brokerage.telephony.provider",
        string="Default Brokerage Telephony Provider",
        ondelete="restrict",
        check_company=True,
    )
