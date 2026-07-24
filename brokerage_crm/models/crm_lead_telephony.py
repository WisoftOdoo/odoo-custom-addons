from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class CrmLeadTelephony(models.Model):
    _inherit = "crm.lead"

    telephony_call_ids = fields.One2many(
        comodel_name="brokerage.telephony.call",
        inverse_name="lead_id",
        string="PBX Calls",
        readonly=True,
    )
    telephony_call_count = fields.Integer(
        compute="_compute_telephony_call_count",
    )

    @api.depends("telephony_call_ids")
    def _compute_telephony_call_count(self):
        for lead in self:
            lead.telephony_call_count = len(lead.telephony_call_ids)

    def _get_brokerage_telephony_provider(self, user):
        self.ensure_one()
        return (
            user.telephony_provider_id
            or self.company_id.brokerage_telephony_provider_id
        )

    def action_brokerage_call_customer(self):
        self.ensure_one()
        user = self.env.user
        if (
            self.user_id != user
            and not user.has_group(
                "brokerage_crm.group_brokerage_sales_manager"
            )
        ):
            raise AccessError(_(
                "Only the assigned salesperson or a Sales Manager can "
                "start a PBX call for this lead."
            ))
        provider = self._get_brokerage_telephony_provider(user)
        if not provider:
            raise ValidationError(_(
                "Configure a default Brokerage Telephony Provider or a "
                "provider override on your user profile."
            ))
        call = self.env[
            "brokerage.telephony.call"
        ].create_outbound_for_lead(self, user, provider)
        failed = call.state == "failed"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": (
                    _("Call Request Failed")
                    if failed
                    else _("Call Requested")
                ),
                "message": (
                    call.initiation_error
                    if failed
                    else _(
                        "Your PBX/device should ring first. Answer it to "
                        "connect to the customer."
                    )
                ),
                "type": "danger" if failed else "success",
                "sticky": failed,
            },
        }

    def action_view_telephony_calls(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("PBX Calls"),
            "res_model": "brokerage.telephony.call",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {
                "create": False,
                "edit": False,
                "delete": False,
            },
        }
