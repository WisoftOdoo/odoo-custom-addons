from odoo import fields, models, _
from odoo.exceptions import ValidationError


class CrmAssignmentRecoveryWizard(models.TransientModel):
    _name = "brokerage.crm.assignment.recovery.wizard"
    _description = "Recover Brokerage Opportunity Assignment"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        required=True,
        readonly=True,
    )
    assignment_history_id = fields.Many2one(
        comodel_name="brokerage.crm.assignment.history",
        string="Assignment to Recover",
        required=True,
        readonly=True,
    )
    current_user_id = fields.Many2one(
        related="lead_id.user_id",
        string="Current Salesperson",
        readonly=True,
    )
    current_team_id = fields.Many2one(
        related="lead_id.team_id",
        string="Current Sales Team",
        readonly=True,
    )
    previous_user_id = fields.Many2one(
        related="assignment_history_id.previous_user_id",
        string="Restore Salesperson",
        readonly=True,
    )
    previous_team_id = fields.Many2one(
        related="assignment_history_id.previous_team_id",
        string="Restore Sales Team",
        readonly=True,
    )
    previous_stage_id = fields.Many2one(
        related="assignment_history_id.previous_stage_id",
        string="Restore Stage",
        readonly=True,
    )
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        if self.assignment_history_id.lead_id != self.lead_id:
            raise ValidationError(_(
                "The selected assignment does not belong to this lead."
            ))
        self.assignment_history_id.action_recover_assignment(self.reason)
        return {
            "type": "ir.actions.act_window",
            "res_model": "crm.lead",
            "res_id": self.lead_id.id,
            "view_mode": "form",
            "target": "current",
        }
