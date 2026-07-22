from odoo import fields, models, _
from odoo.exceptions import ValidationError


class CrmScheduleMeetingWizard(models.TransientModel):
    _name = "brokerage.crm.schedule.meeting.wizard"
    _description = "Schedule Brokerage Meeting"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        required=True,
        readonly=True,
    )

    name = fields.Char(
        required=True,
        default="Client Meeting",
    )

    meeting_type = fields.Selection(
        selection=[
            ("office", "Office Meeting"),
            ("customer_location", "Customer Location"),
            ("zoom", "Zoom"),
            ("google_meet", "Google Meet"),
            ("phone", "Phone Meeting"),
            ("project_visit", "Project Visit"),
            ("developer_office", "Developer Office"),
            ("other", "Other"),
        ],
        required=True,
        default="office",
    )

    scheduled_start = fields.Datetime(required=True)
    scheduled_end = fields.Datetime(required=True)

    location = fields.Char()
    meeting_link = fields.Char()

    developer_id = fields.Many2one(
        comodel_name="brokerage.developer",
    )

    project_id = fields.Many2one(
        comodel_name="brokerage.project",
        domain="[('developer_id', '=', developer_id)]",
    )

    relationship_manager_name = fields.Char(
        string="Developer RM",
    )

    def action_confirm(self):
        self.ensure_one()

        lead = self.lead_id

        if self.scheduled_end <= self.scheduled_start:
            raise ValidationError(
                _("Meeting end must be after meeting start.")
            )

        meeting = self.env["brokerage.crm.meeting"].create({
            "lead_id": lead.id,
            "name": self.name,
            "state": "scheduled",
            "meeting_type": self.meeting_type,
            "scheduled_start": self.scheduled_start,
            "scheduled_end": self.scheduled_end,
            "location": self.location,
            "meeting_link": self.meeting_link,
            "developer_id": self.developer_id.id or False,
            "project_id": self.project_id.id or False,
            "relationship_manager_name": (
                self.relationship_manager_name
            ),
        })

        partner_ids = []

        if lead.partner_id:
            partner_ids.append(lead.partner_id.id)

        if lead.user_id.partner_id:
            partner_ids.append(lead.user_id.partner_id.id)

        event_values = {
            "name": self.name,
            "start": self.scheduled_start,
            "stop": self.scheduled_end,
            "user_id": lead.user_id.id or self.env.user.id,
            "partner_ids": [(6, 0, partner_ids)],
            "location": self.location,
            "description": _(
                "Brokerage CRM meeting for opportunity: %s"
            ) % lead.display_name,
        }

        if "opportunity_id" in self.env["calendar.event"]._fields:
            event_values["opportunity_id"] = lead.id

        calendar_event = self.env["calendar.event"].create(
            event_values
        )

        meeting.calendar_event_id = calendar_event.id

        status = self.env["brokerage.crm.lead.status"].search(
            [("code", "=", "meeting_scheduled")],
            limit=1,
        )

        stage = lead._find_brokerage_stage("meeting_scheduled")

        values = {
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
                "Meeting <b>%(name)s</b> scheduled for %(date)s."
            ) % {
                "name": meeting.display_name,
                "date": self.scheduled_start,
            },
            subtype_xmlid="mail.mt_note",
        )

        return {"type": "ir.actions.act_window_close"}
