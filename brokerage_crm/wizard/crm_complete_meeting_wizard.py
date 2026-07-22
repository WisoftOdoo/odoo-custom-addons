from odoo import fields, models, _
from odoo.exceptions import ValidationError


class CrmCompleteMeetingWizard(models.TransientModel):
    _name = "brokerage.crm.complete.meeting.wizard"
    _description = "Complete Brokerage Meeting"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        required=True,
        readonly=True,
    )

    meeting_id = fields.Many2one(
        comodel_name="brokerage.crm.meeting",
        required=True,
        domain="[('lead_id', '=', lead_id), "
               "('state', 'in', ['scheduled', 'rescheduled'])]",
    )

    actual_start = fields.Datetime(required=True)
    actual_end = fields.Datetime(required=True)

    outcome = fields.Selection(
        selection=[
            ("interested", "Interested"),
            ("follow_up", "Follow-up Required"),
            ("project_shortlisted", "Project Shortlisted"),
            ("unit_shortlisted", "Unit Shortlisted"),
            ("budget_mismatch", "Budget Mismatch"),
            ("not_interested", "Not Interested"),
            ("reschedule", "Reschedule Required"),
            ("decision_pending", "Decision Pending"),
            ("other", "Other"),
        ],
        required=True,
    )

    developer_id = fields.Many2one(
        comodel_name="brokerage.developer",
        required=True,
    )

    project_id = fields.Many2one(
        comodel_name="brokerage.project",
        required=True,
        domain="[('developer_id', '=', developer_id)]",
    )

    customer_requirements = fields.Text()
    agent_remarks = fields.Text(required=True)
    next_action = fields.Text(required=True)
    next_follow_up_date = fields.Date(required=True)

    next_activity_type_id = fields.Many2one(
        comodel_name="mail.activity.type",
        required=True,
    )

    def action_confirm(self):
        self.ensure_one()

        if self.actual_end <= self.actual_start:
            raise ValidationError(
                _("Actual end must be after actual start.")
            )

        meeting = self.meeting_id
        lead = self.lead_id

        meeting.write({
            "state": "completed",
            "actual_start": self.actual_start,
            "actual_end": self.actual_end,
            "outcome": self.outcome,
            "developer_id": self.developer_id.id,
            "project_id": self.project_id.id,
            "customer_requirements": self.customer_requirements,
            "agent_remarks": self.agent_remarks,
            "next_action": self.next_action,
            "next_follow_up_date": self.next_follow_up_date,
        })

        self.env["mail.activity"].create({
            "res_model_id": self.env["ir.model"]._get_id("crm.lead"),
            "res_id": lead.id,
            "activity_type_id": self.next_activity_type_id.id,
            "user_id": lead.user_id.id or self.env.user.id,
            "date_deadline": self.next_follow_up_date,
            "summary": self.next_action,
            "note": self.agent_remarks,
        })

        status = self.env["brokerage.crm.lead.status"].search(
            [("code", "=", "meeting_completed")],
            limit=1,
        )

        stage = lead._find_brokerage_stage("meeting_completed")

        values = {
            "preferred_developer_id": self.developer_id.id,
            "preferred_project_id": self.project_id.id,
            "last_meaningful_update": fields.Datetime.now(),
        }

        if status:
            values["lead_status_id"] = status.id

        if stage:
            values["stage_id"] = stage.id

        lead.with_context(
            brokerage_workflow_action=True,
        ).write(values)

        lead.message_post(
            body=_(
                "<b>Meeting completed</b><br/>"
                "Outcome: %(outcome)s<br/>"
                "Developer: %(developer)s<br/>"
                "Project: %(project)s<br/>"
                "Next action: %(action)s"
            ) % {
                "outcome": dict(
                    self._fields["outcome"].selection
                ).get(self.outcome),
                "developer": self.developer_id.display_name,
                "project": self.project_id.display_name,
                "action": self.next_action,
            },
            subtype_xmlid="mail.mt_note",
        )

        return {"type": "ir.actions.act_window_close"}
