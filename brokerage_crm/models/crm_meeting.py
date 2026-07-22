from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class BrokerageCrmMeeting(models.Model):
    _name = "brokerage.crm.meeting"
    _description = "Brokerage CRM Meeting"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "scheduled_start desc, id desc"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        string="Lead / Opportunity",
        required=True,
        ondelete="cascade",
        tracking=True,
        index=True,
    )

    name = fields.Char(
        required=True,
        tracking=True,
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("scheduled", "Scheduled"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
            ("rescheduled", "Rescheduled"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
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
        tracking=True,
    )

    scheduled_start = fields.Datetime(
        required=True,
        tracking=True,
        index=True,
    )

    scheduled_end = fields.Datetime(
        required=True,
        tracking=True,
    )

    actual_start = fields.Datetime(tracking=True)
    actual_end = fields.Datetime(tracking=True)

    location = fields.Char(tracking=True)
    meeting_link = fields.Char(tracking=True)

    developer_id = fields.Many2one(
        comodel_name="brokerage.developer",
        string="Developer",
        tracking=True,
        ondelete="restrict",
    )

    project_id = fields.Many2one(
        comodel_name="brokerage.project",
        string="Project",
        tracking=True,
        ondelete="restrict",
        domain="[('developer_id', '=', developer_id)]",
    )

    relationship_manager_name = fields.Char(
        string="Developer RM",
        tracking=True,
    )

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
        tracking=True,
        index=True,
    )

    customer_requirements = fields.Text(tracking=True)
    agent_remarks = fields.Text(tracking=True)
    next_action = fields.Text(tracking=True)
    next_follow_up_date = fields.Date(tracking=True)

    calendar_event_id = fields.Many2one(
        comodel_name="calendar.event",
        string="Calendar Event",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    responsible_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Responsible Salesperson",
        related="lead_id.user_id",
        store=True,
        readonly=True,
    )

    @api.onchange("developer_id")
    def _onchange_developer_id(self):
        if (
            self.project_id
            and self.project_id.developer_id != self.developer_id
        ):
            self.project_id = False

        if self.developer_id:
            self.relationship_manager_name = self.developer_id.rm_name

    @api.constrains(
        "scheduled_start",
        "scheduled_end",
        "actual_start",
        "actual_end",
        "meeting_type",
        "location",
        "meeting_link",
        "developer_id",
        "project_id",
    )
    def _check_meeting_values(self):
        for meeting in self:
            if (
                meeting.scheduled_start
                and meeting.scheduled_end
                and meeting.scheduled_end <= meeting.scheduled_start
            ):
                raise ValidationError(
                    _("Scheduled end time must be after start time.")
                )

            if (
                meeting.actual_start
                and meeting.actual_end
                and meeting.actual_end <= meeting.actual_start
            ):
                raise ValidationError(
                    _("Actual end time must be after actual start time.")
                )

            if (
                meeting.meeting_type in ("zoom", "google_meet")
                and not meeting.meeting_link
            ):
                raise ValidationError(
                    _("A meeting link is required for an online meeting.")
                )

            if (
                meeting.meeting_type
                not in ("zoom", "google_meet", "phone")
                and not meeting.location
            ):
                raise ValidationError(
                    _("A location is required for this meeting type.")
                )

            if (
                meeting.project_id
                and meeting.project_id.developer_id
                != meeting.developer_id
            ):
                raise ValidationError(
                    _(
                        "The selected project does not belong to "
                        "the selected developer."
                    )
                )

    @api.constrains(
        "state",
        "actual_start",
        "actual_end",
        "outcome",
        "developer_id",
        "project_id",
        "agent_remarks",
        "next_action",
        "next_follow_up_date",
    )
    def _check_completed_meeting(self):
        for meeting in self:
            if meeting.state != "completed":
                continue

            missing = []

            if not meeting.actual_start:
                missing.append(_("Actual Start"))
            if not meeting.actual_end:
                missing.append(_("Actual End"))
            if not meeting.outcome:
                missing.append(_("Meeting Outcome"))
            if not meeting.developer_id:
                missing.append(_("Developer"))
            if not meeting.project_id:
                missing.append(_("Project"))
            if not meeting.agent_remarks:
                missing.append(_("Agent Remarks"))
            if not meeting.next_action:
                missing.append(_("Next Action"))
            if not meeting.next_follow_up_date:
                missing.append(_("Next Follow-up Date"))

            if missing:
                raise ValidationError(
                    _(
                        "A completed meeting requires:\n• %s"
                    ) % "\n• ".join(missing)
                )

    def action_open_calendar_event(self):
        self.ensure_one()

        if not self.calendar_event_id:
            raise ValidationError(
                _("This meeting does not have a linked Calendar event.")
            )

        return {
            "type": "ir.actions.act_window",
            "name": _("Calendar Event"),
            "res_model": "calendar.event",
            "res_id": self.calendar_event_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_cancel(self):
        for meeting in self:
            if meeting.state == "completed":
                raise ValidationError(
                    _("A completed meeting cannot be cancelled.")
                )

            meeting.state = "cancelled"

            if meeting.calendar_event_id:
                meeting.calendar_event_id.unlink()

            meeting.lead_id.message_post(
                body=_(
                    "Meeting <b>%s</b> was cancelled."
                ) % meeting.display_name,
                subtype_xmlid="mail.mt_note",
            )

        return True