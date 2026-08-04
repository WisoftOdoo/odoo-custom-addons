from markupsafe import Markup

from odoo import fields, models, _
from odoo.exceptions import ValidationError


class CrmStageCorrectionWizard(models.TransientModel):
    _name = "brokerage.crm.stage.correction.wizard"
    _description = "Correct Brokerage Opportunity Stage"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        required=True,
        readonly=True,
    )
    current_stage_id = fields.Many2one(
        related="lead_id.stage_id",
        string="Current Stage",
        readonly=True,
    )
    target_stage_id = fields.Many2one(
        comodel_name="crm.stage",
        string="Correct Stage",
        required=True,
        domain=[("brokerage_code", "!=", False)],
    )
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        lead = self.lead_id
        current_stage = lead.stage_id
        target_stage = self.target_stage_id

        if target_stage == current_stage:
            raise ValidationError(_("Select a different stage."))
        if target_stage.sequence >= current_stage.sequence:
            raise ValidationError(_(
                "Correct Stage is only for audited backward corrections. "
                "Use the normal workflow actions to move forward."
            ))

        lead.sudo()._clear_open_brokerage_sla_activities()
        lead.sudo().with_context(
            brokerage_workflow_action=True,
            skip_round_robin=True,
            skip_assignment_history=True,
        ).write({
            "stage_id": target_stage.id,
            "sla_cycle_active": False,
        })
        lead.sudo().message_post(
            body=Markup(_(
                "Stage corrected by <b>%(manager)s</b> from "
                "<b>%(old_stage)s</b> to <b>%(new_stage)s</b>."
                "<br/>Reason: %(reason)s"
            )) % {
                "manager": self.env.user.display_name,
                "old_stage": current_stage.display_name,
                "new_stage": target_stage.display_name,
                "reason": self.reason,
            },
            subtype_xmlid="mail.mt_note",
            author_id=self.env.user.partner_id.id,
        )

        return {
            "type": "ir.actions.act_window",
            "res_model": "crm.lead",
            "res_id": lead.id,
            "view_mode": "form",
            "target": "current",
        }
