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

    telephony_provider_id = fields.Many2one(
        comodel_name="brokerage.telephony.provider",
        string="Telephony Provider Override",
        ondelete="restrict",
        check_company=True,
        help=(
            "Leave empty to use the company's default Brokerage "
            "Telephony Provider."
        ),
    )
    telephony_extension = fields.Char(
        string="PBX Extension",
        help="The salesperson's extension/DN in the configured PBX.",
    )
    telephony_device_id = fields.Char(
        string="PBX Device ID",
        help=(
            "Optional provider device identifier. For 3CX, configure this "
            "when an extension has multiple registered devices and calls "
            "must ring a specific device."
        ),
    )
