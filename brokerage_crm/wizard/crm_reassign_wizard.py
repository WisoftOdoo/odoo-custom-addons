from odoo import fields, models, _
from odoo.exceptions import ValidationError


class CrmReassignWizard(models.TransientModel):
    _name = "brokerage.crm.reassign.wizard"
    _description = "Reassign Brokerage Opportunity"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        required=True,
        readonly=True,
    )

    new_team_id = fields.Many2one(
        comodel_name="crm.team",
        required=True,
    )

    new_user_id = fields.Many2one(
        comodel_name="res.users",
        string="New Salesperson",
        required=True,
        domain=[
            ("share", "=", False),
            ("active", "=", True),
        ],
    )

    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()

        lead = self.lead_id

        if (
            lead.user_id == self.new_user_id
            and lead.team_id == self.new_team_id
        ):
            raise ValidationError(
                _("Select a different salesperson or sales team.")
            )

        previous_user = lead.user_id
        previous_team = lead.team_id
        now = fields.Datetime.now()
        assigned_stage = lead._find_brokerage_stage(
            "assigned", team=self.new_team_id
        )
        if not assigned_stage:
            raise ValidationError(_(
                "Configure an Assigned CRM stage for Sales Team %s before "
                "reassigning the opportunity."
            ) % self.new_team_id.display_name)

        values = {
            "team_id": self.new_team_id.id,
            "user_id": self.new_user_id.id,
        }
        values.update(
            lead._prepare_brokerage_assignment_cycle_values(
                "reassignment", now
            )
        )
        lead.sudo()._clear_open_brokerage_sla_activities()
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write(values)
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({"stage_id": assigned_stage.id})

        self.env["brokerage.crm.assignment.history"].sudo().create({
            "lead_id": lead.id,
            "source_id": lead.source_id.id or False,
            "previous_user_id": previous_user.id or False,
            "new_user_id": self.new_user_id.id,
            "previous_team_id": previous_team.id or False,
            "new_team_id": self.new_team_id.id,
            "assignment_type": "reassignment",
            "assigned_datetime": now,
            "assigned_by_id": self.env.user.id,
            "reason": self.reason,
        })

        lead.sudo().message_post(
            body=_(
                "Opportunity reassigned from <b>%(old)s</b> "
                "to <b>%(new)s</b>.<br/>Reason: %(reason)s"
            ) % {
                "old": previous_user.display_name or "-",
                "new": self.new_user_id.display_name,
                "reason": self.reason,
            },
            subtype_xmlid="mail.mt_note",
            author_id=self.env.user.partner_id.id,
        )
        lead.sudo()._queue_brokerage_whatsapp_assignment(
            self.new_user_id,
            self.reason,
        )

        return {"type": "ir.actions.act_window_close"}
