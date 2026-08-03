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

    recorded_datetime = fields.Datetime(
        string="Recorded Date/Time",
        required=True,
        default=fields.Datetime.now,
        readonly=True,
        copy=False,
        index=True,
        help=(
            "Wall-clock time used to validate that the meeting belongs to "
            "the current assignment cycle."
        ),
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
        string="Legacy Meeting Type",
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
        default="office",
        tracking=True,
        help="Legacy compatibility value. Use Meeting Type for new records.",
    )

    meeting_type_id = fields.Many2one(
        comodel_name="brokerage.crm.meeting.type",
        string="Meeting Type",
        default=lambda self: self.env.ref(
            "brokerage_crm.meeting_type_office",
            raise_if_not_found=False,
        ),
        ondelete="restrict",
        tracking=True,
        index=True,
    )

    meeting_type_location_mode = fields.Selection(
        related="meeting_type_id.location_mode",
        string="Meeting Location Requirement",
        readonly=True,
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
        string="Legacy Meeting Outcome",
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
        help="Legacy compatibility value. Use Meeting Outcome for new records.",
    )

    outcome_id = fields.Many2one(
        comodel_name="brokerage.crm.meeting.outcome",
        string="Meeting Outcome",
        ondelete="restrict",
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

    @api.model
    def _meeting_type_from_legacy_code(self, code):
        return self.env["brokerage.crm.meeting.type"].search([
            ("code", "=", code or "office"),
        ], limit=1)

    @api.model
    def _meeting_outcome_from_legacy_code(self, code):
        return self.env["brokerage.crm.meeting.outcome"].with_context(
            active_test=False,
        ).search([
            ("code", "=", code),
        ], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        legacy_codes = dict(self._fields["meeting_type"].selection)
        legacy_outcomes = dict(self._fields["outcome"].selection)
        for vals in vals_list:
            if vals.get("meeting_type_id"):
                meeting_type = self.env[
                    "brokerage.crm.meeting.type"
                ].browse(vals["meeting_type_id"])
                vals.setdefault(
                    "meeting_type",
                    meeting_type.code
                    if meeting_type.code in legacy_codes
                    else "other",
                )
            elif vals.get("meeting_type"):
                meeting_type = self._meeting_type_from_legacy_code(
                    vals["meeting_type"]
                )
                if meeting_type:
                    vals["meeting_type_id"] = meeting_type.id
            if vals.get("outcome_id"):
                outcome = self.env[
                    "brokerage.crm.meeting.outcome"
                ].browse(vals["outcome_id"])
                vals.setdefault(
                    "outcome",
                    outcome.code
                    if outcome.code in legacy_outcomes
                    else "other",
                )
            elif vals.get("outcome"):
                outcome = self._meeting_outcome_from_legacy_code(
                    vals["outcome"]
                )
                if outcome:
                    vals["outcome_id"] = outcome.id
        return super().create(vals_list)

    def write(self, vals):
        legacy_codes = dict(self._fields["meeting_type"].selection)
        legacy_outcomes = dict(self._fields["outcome"].selection)
        if vals.get("meeting_type_id"):
            meeting_type = self.env[
                "brokerage.crm.meeting.type"
            ].browse(vals["meeting_type_id"])
            vals.setdefault(
                "meeting_type",
                meeting_type.code
                if meeting_type.code in legacy_codes
                else "other",
            )
        elif vals.get("meeting_type"):
            meeting_type = self._meeting_type_from_legacy_code(
                vals["meeting_type"]
            )
            if meeting_type:
                vals["meeting_type_id"] = meeting_type.id
        if vals.get("outcome_id"):
            outcome = self.env[
                "brokerage.crm.meeting.outcome"
            ].browse(vals["outcome_id"])
            vals.setdefault(
                "outcome",
                outcome.code
                if outcome.code in legacy_outcomes
                else "other",
            )
        elif vals.get("outcome"):
            outcome = self._meeting_outcome_from_legacy_code(vals["outcome"])
            if outcome:
                vals["outcome_id"] = outcome.id
        return super().write(vals)

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
        "meeting_type_id",
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
                meeting.meeting_type_location_mode == "online"
                and not meeting.meeting_link
            ):
                raise ValidationError(
                    _("A meeting link is required for an online meeting.")
                )

            if (
                meeting.meeting_type_location_mode == "location"
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
        "outcome_id",
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
            if not meeting.outcome_id:
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
