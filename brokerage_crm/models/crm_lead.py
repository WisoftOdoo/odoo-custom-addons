from datetime import timedelta
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = "crm.lead"

    external_lead_id = fields.Char(
        string="External Lead ID",
        copy=False,
        index=True,
        tracking=True,
    )

    _source_external_lead_unique = models.Constraint(
        "UNIQUE(source_id, external_lead_id)",
        "This external lead has already been imported for this source.",
    )

    '''Source and classification fields'''
    lead_status_id = fields.Many2one(
        comodel_name="brokerage.crm.lead.status",
        string="Lead Status",
        tracking=True,
        index=True,
    )

    lead_quality_id = fields.Many2one(
        comodel_name="brokerage.crm.lead.quality",
        string="Lead Quality",
        tracking=True,
        index=True,
    )

    source_category = fields.Selection(
        related="source_id.brokerage_category",
        string="Source Category",
        store=True,
        index=True,
    )

    '''Assignment fields'''
    assignment_type = fields.Selection(
        selection=[
            ("round_robin", "Round Robin"),
            ("manual", "Manual"),
            ("referral", "Referral"),
            ("walk_in", "Walk-in"),
            ("bulk", "Bulk Distribution"),
            ("reassignment", "Reassignment"),
            (
                "not_interested_reassignment",
                "Not Interested Reassignment",
            ),
        ],
        tracking=True,
        index=True,
    )

    assigned_datetime = fields.Datetime(
        string="Assigned Date/Time",
        tracking=True,
        readonly=True,
        copy=False,
    )

    sla_cycle_active = fields.Boolean(
        string="SLA Cycle Active",
        default=False,
        readonly=True,
        copy=False,
        index=True,
        help=(
            "Technical flag activated only by a real assignment cycle. "
            "Moving a progressed lead back to Assigned does not reactivate "
            "an old SLA timer."
        ),
    )

    first_contact_datetime = fields.Datetime(
        string="First Contact Date/Time",
        tracking=True,
        readonly=True,
        copy=False,
    )

    last_status_update = fields.Datetime(
        string="Last Status Update",
        readonly=True,
        copy=False,
    )

    last_meaningful_update = fields.Datetime(
        string="Last Meaningful Update",
        readonly=True,
        copy=False,
    )

    not_interested_reassignment_done = fields.Boolean(
        string="Not Interested Reassignment Completed",
        readonly=True,
        copy=False,
        default=False,
        index=True,
    )

    contact_attempt_count = fields.Integer(
        compute="_compute_brokerage_counts",
    )

    meeting_count = fields.Integer(
        compute="_compute_brokerage_counts",
    )

    assignment_history_count = fields.Integer(
        compute="_compute_brokerage_counts",
    )

    '''Customer qualification fields'''
    requirement_type = fields.Selection(
        selection=[
            ("investment", "Investment"),
            ("end_use", "End Use"),
            ("both", "Investment and End Use"),
        ],
        tracking=True,
    )

    company_currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="company_id.currency_id",
        string="Company Currency",
        readonly=True,
    )

    budget_from = fields.Monetary(
        currency_field="company_currency_id",
        tracking=True,
    )

    budget_to = fields.Monetary(
        currency_field="company_currency_id",
        tracking=True,
    )

    preferred_location = fields.Char(tracking=True)

    property_category = fields.Selection(
        selection=[
            ("apartment", "Apartment"),
            ("villa", "Villa"),
            ("townhouse", "Townhouse"),
            ("penthouse", "Penthouse"),
            ("plot", "Plot"),
            ("commercial", "Commercial"),
            ("other", "Other"),
        ],
        tracking=True,
    )

    unit_preference = fields.Char(tracking=True)

    bedroom_count = fields.Selection(
        selection=[
            ("studio", "Studio"),
            ("1", "1 Bedroom"),
            ("2", "2 Bedrooms"),
            ("3", "3 Bedrooms"),
            ("4", "4 Bedrooms"),
            ("5_plus", "5+ Bedrooms"),
        ],
        tracking=True,
    )

    purchase_timeline = fields.Selection(
        selection=[
            ("immediate", "Immediate"),
            ("one_month", "Within 1 Month"),
            ("three_months", "Within 3 Months"),
            ("six_months", "Within 6 Months"),
            ("later", "More Than 6 Months"),
            ("unknown", "Not Confirmed"),
        ],
        tracking=True,
    )

    buyer_type = fields.Selection(
        selection=[
            ("resident", "UAE Resident"),
            ("non_resident", "Non-resident"),
            ("investor", "Investor"),
            ("end_user", "End User"),
        ],
        tracking=True,
    )

    purchase_mode = fields.Selection(
        selection=[
            ("cash", "Cash"),
            ("finance", "Finance"),
            ("undecided", "Not Confirmed"),
        ],
        tracking=True,
    )

    preferred_developer_id = fields.Many2one(
        comodel_name="brokerage.developer",
        tracking=True,
    )

    preferred_project_id = fields.Many2one(
        comodel_name="brokerage.project",
        tracking=True,
        domain="[('developer_id', '=', preferred_developer_id)]",
    )

    customer_requirement_notes = fields.Text(tracking=True)

    '''Forecast and Hot fields'''
    forecast_remarks = fields.Text(tracking=True)

    final_developer_id = fields.Many2one(
        comodel_name="brokerage.developer",
        tracking=True,
    )

    final_project_id = fields.Many2one(
        comodel_name="brokerage.project",
        tracking=True,
        domain="[('developer_id', '=', final_developer_id)]",
    )

    final_unit_type = fields.Char(tracking=True)

    estimated_property_value = fields.Monetary(
        currency_field="company_currency_id",
        tracking=True,
    )

    expected_booking_date = fields.Date(tracking=True)

    '''Related Records'''
    contact_attempt_ids = fields.One2many(
        comodel_name="brokerage.crm.contact.attempt",
        inverse_name="lead_id",
    )

    brokerage_meeting_ids = fields.One2many(
        comodel_name="brokerage.crm.meeting",
        inverse_name="lead_id",
    )

    assignment_history_ids = fields.One2many(
        comodel_name="brokerage.crm.assignment.history",
        inverse_name="lead_id",
    )

    @api.model_create_multi
    def create(self, vals_list):
        round_robin_flags = []
        direct_assignment_flags = []
        explicit_team_flags = []
        for vals in vals_list:
            round_robin_flags.append(vals.get("assignment_type") == "round_robin")
            direct_assignment_flags.append(bool(vals.get("user_id")))
            explicit_team_flags.append(bool(vals.get("team_id")))
            if vals.get("user_id"):
                vals.setdefault("assigned_datetime", fields.Datetime.now())

        leads = super().create(vals_list)
        for lead, use_round_robin, is_direct, has_explicit_team in zip(
            leads,
            round_robin_flags,
            direct_assignment_flags,
            explicit_team_flags,
        ):
            if use_round_robin:
                lead.with_context(
                    force_global_round_robin=not has_explicit_team
                )._apply_round_robin_assignment()
            elif is_direct and lead.user_id:
                lead._record_direct_assignment(False, lead.user_id)
        return leads

    def write(self, vals):
        previous = {
            lead.id: (lead.user_id, lead.team_id, lead.assignment_type)
            for lead in self
        }
        stage = self.env["crm.stage"].browse(vals.get("stage_id"))
        if stage and not self.env.context.get("brokerage_workflow_action"):
            for lead in self:
                lead._validate_brokerage_stage_move(stage)

        if stage and self._stage_code(stage) != "assigned":
            vals = dict(vals)
            vals["sla_cycle_active"] = False

        trigger_round_robin = (
            vals.get("assignment_type") == "round_robin"
            and not self.env.context.get("skip_round_robin")
        )
        if trigger_round_robin:
            # Let the requested type be stored, then assign atomically using the
            # configured queue. Any user_id supplied in the same write is ignored.
            vals = dict(vals)
            vals.pop("user_id", None)

        result = super().write(vals)

        if stage and self._stage_code(stage) in (
            "contact_attempted", "contacted", "not_interested"
        ):
            self._clear_open_brokerage_sla_activities()

        if trigger_round_robin:
            for lead in self:
                lead._apply_round_robin_assignment()
            return result

        if "user_id" in vals and not self.env.context.get("skip_assignment_history"):
            now = fields.Datetime.now()
            for lead in self:
                old_user, old_team, old_type = previous[lead.id]
                if lead.user_id != old_user:
                    lead.with_context(skip_assignment_history=True).write({
                        "assigned_datetime": now if lead.user_id else False,
                        "first_contact_datetime": False,
                        "last_meaningful_update": now if lead.user_id else False,
                    })
                    if lead.user_id:
                        lead._record_direct_assignment(old_user, lead.user_id, old_team)
        return result

    def _record_direct_assignment(self, previous_user, new_user, previous_team=False):
        self.ensure_one()
        if not self.team_id:
            return
        self.env["brokerage.crm.assignment.history"].create({
            "lead_id": self.id,
            "source_id": self.source_id.id or False,
            "previous_user_id": previous_user.id if previous_user else False,
            "new_user_id": new_user.id,
            "previous_team_id": previous_team.id if previous_team else False,
            "new_team_id": self.team_id.id or False,
            "assignment_type": self.assignment_type or "manual",
            "assigned_datetime": self.assigned_datetime or fields.Datetime.now(),
            "assigned_by_id": self.env.user.id,
            "reason": _("Direct assignment"),
        })
        self._queue_brokerage_whatsapp_assignment(
            new_user,
            _("Direct assignment"),
        )

    def _queue_brokerage_whatsapp_assignment(self, user, reason=None):
        self.ensure_one()
        if not user:
            return self.env["brokerage.whatsapp.notification"]
        try:
            return self.env[
                "brokerage.whatsapp.notification"
            ].sudo().queue_assignment(
                self.sudo(),
                user.sudo(),
                reason=reason,
            )
        except Exception:
            _logger.exception(
                "Could not queue assignment WhatsApp for CRM lead %s",
                self.id,
            )
            return self.env["brokerage.whatsapp.notification"]

    def _queue_brokerage_whatsapp_sla(
        self,
        user,
        event_type,
        minutes,
        rule,
        assignment_datetime,
    ):
        self.ensure_one()
        if not user:
            return self.env["brokerage.whatsapp.notification"]
        try:
            return self.env[
                "brokerage.whatsapp.notification"
            ].sudo().queue_sla(
                self.sudo(),
                user.sudo(),
                event_type,
                minutes,
                rule.sudo(),
                assignment_datetime,
            )
        except Exception:
            _logger.exception(
                "Could not queue SLA WhatsApp for CRM lead %s event %s",
                self.id,
                event_type,
            )
            return self.env["brokerage.whatsapp.notification"]

    def _apply_round_robin_assignment(self):
        for lead in self:
            team = False if self.env.context.get("force_global_round_robin") else (
                lead.team_id or lead.source_id.default_team_id
            )
            round_robin = self.env["brokerage.crm.round.robin"].sudo()
            if team:
                rule = round_robin.search([
                    ("team_id", "=", team.id), ("active", "=", True)
                ], limit=1)
            else:
                # Serialize team selection as well as the per-team agent
                # selection. This keeps simultaneous external submissions fair.
                self.env.cr.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    ["brokerage.crm.round.robin.dispatch"],
                )
                configurations = round_robin.search(
                    [("active", "=", True)],
                    order="assignment_count, sequence, id",
                )
                rule = configurations.filtered(
                    lambda configuration: configuration._get_eligible_users()
                )[:1]
            if not rule:
                scope = team.display_name if team else _("any Sales Team")
                raise ValidationError(_(
                    "No active Round Robin configuration with eligible agents "
                    "exists for %s."
                ) % scope)
            # Configuration and assignment history are intentionally elevated:
            # agents/integration users may create leads but must not receive
            # permission to edit the Round Robin setup itself.
            rule.assign_lead(lead.sudo())

    def _stage_code(self, stage):
        if stage.brokerage_code:
            return stage.brokerage_code
        normalized = (stage.name or "").strip().lower().replace("/", " ")
        normalized = "_".join(normalized.split())
        aliases = {
            "new_lead": "new", "assigned": "assigned",
            "contact_attempted": "contact_attempted", "contacted": "contacted",
            "meeting_scheduled": "meeting_scheduled",
            "meeting_completed": "meeting_completed", "forecast": "forecast",
            "hot_booking_expected": "hot", "kyc_in_progress": "kyc",
            "not_interested": "not_interested",
        }
        return aliases.get(normalized)

    def _find_brokerage_stage(self, code, team=False):
        self.ensure_one()
        target_team = team or self.team_id
        stage = self.env["crm.stage"].search([
            ("brokerage_code", "=", code),
            "|", ("team_ids", "=", False), ("team_ids", "in", target_team.ids),
        ], order="sequence, id", limit=1)
        if stage:
            return stage
        names = {
            "contact_attempted": "Contact Attempted",
            "contacted": "Contacted",
            "not_interested": "Not Interested",
            "meeting_scheduled": "Meeting Scheduled",
            "meeting_completed": "Meeting Completed",
        }
        return self.env["crm.stage"].search([
            ("name", "=ilike", names.get(code, code)),
            "|", ("team_ids", "=", False), ("team_ids", "in", target_team.ids),
        ], order="sequence, id", limit=1)

    def _prepare_brokerage_assignment_cycle_values(
        self, assignment_type, assigned_datetime=None
    ):
        """Reset transient workflow evidence for a new salesperson cycle."""
        self.ensure_one()
        assigned_datetime = assigned_datetime or fields.Datetime.now()
        assigned_status = self.env[
            "brokerage.crm.lead.status"
        ].sudo().search([("code", "=", "assigned")], limit=1)
        return {
            "assignment_type": assignment_type,
            "assigned_datetime": assigned_datetime,
            "sla_cycle_active": True,
            "first_contact_datetime": False,
            "last_status_update": assigned_datetime,
            "last_meaningful_update": assigned_datetime,
            "lead_status_id": assigned_status.id or False,
            "forecast_remarks": False,
            "final_developer_id": False,
            "final_project_id": False,
            "final_unit_type": False,
            "estimated_property_value": 0,
            "expected_booking_date": False,
        }

    def _current_assignment_contact_attempts(self):
        self.ensure_one()
        domain = [("lead_id", "=", self.id)]
        if self.assigned_datetime:
            domain.append((
                "attempt_datetime",
                ">=",
                self.assigned_datetime,
            ))
        if self.user_id:
            domain.append(("user_id", "=", self.user_id.id))
        return self.env["brokerage.crm.contact.attempt"].search(domain)

    def _current_assignment_meetings(self):
        self.ensure_one()
        domain = [("lead_id", "=", self.id)]
        if self.assigned_datetime:
            domain.append(("create_date", ">=", self.assigned_datetime))
        if self.user_id:
            domain.append(("create_uid", "=", self.user_id.id))
        return self.env["brokerage.crm.meeting"].search(domain)

    def _validate_brokerage_stage_move(self, target_stage):
        self.ensure_one()
        code = self._stage_code(target_stage)
        current_code = self._stage_code(self.stage_id)
        if (
            current_code
            and code
            and target_stage.sequence < self.stage_id.sequence
        ):
            raise ValidationError(_(
                "Leads cannot be moved backward from %(current)s to "
                "%(target)s by dragging the pipeline card. Ask a Sales "
                "Manager to use Correct Stage when a genuine correction "
                "is required."
            ) % {
                "current": self.stage_id.display_name,
                "target": target_stage.display_name,
            })

        attempts = self._current_assignment_contact_attempts()
        successful_attempts = attempts.filtered("successful_contact")
        meetings = self._current_assignment_meetings()
        if code == "contact_attempted" and not attempts:
            raise ValidationError(
                _(
                    "The current salesperson must record a Contact Attempt "
                    "after this assignment before moving to Contact Attempted."
                )
            )
        if code == "contacted" and not successful_attempts:
            raise ValidationError(
                _(
                    "The current salesperson must record a successful contact "
                    "after this assignment before moving to Contacted."
                )
            )
        if code in (
            "meeting_scheduled", "meeting_completed", "forecast", "hot", "kyc"
        ) and not successful_attempts:
            raise ValidationError(_(
                "The current salesperson must record a successful contact "
                "before progressing to meeting and later stages."
            ))
        if code == "meeting_scheduled" and not meetings.filtered(
            lambda meeting: meeting.state in ("scheduled", "rescheduled", "completed")
        ):
            raise ValidationError(
                _(
                    "The current salesperson must schedule and log a meeting "
                    "after this assignment before moving to Meeting Scheduled."
                )
            )
        if code in ("meeting_completed", "forecast", "hot", "kyc") and not meetings.filtered(
            lambda meeting: meeting.state == "completed"
        ):
            raise ValidationError(
                _(
                    "The current salesperson must complete a meeting created "
                    "after this assignment before moving forward."
                )
            )
        if code == "hot" and not all((
            self.final_developer_id, self.final_project_id,
            self.final_unit_type, self.expected_booking_date,
        )):
            raise ValidationError(
                _("Final developer, project, unit type and expected booking date are required for Hot / Booking Expected.")
            )

    @api.model
    def _cron_check_brokerage_sla(self):
        now = fields.Datetime.now()
        rules = self.env["brokerage.crm.sla.rule"].search([
            ("active", "=", True),
            ("rule_type", "=", "first_contact"),
        ])
        for rule in rules:
            domain = [
                ("active", "=", True),
                ("user_id", "!=", False),
                ("assigned_datetime", "!=", False),
                ("sla_cycle_active", "=", True),
                (
                    "assignment_type",
                    "in",
                    [
                        "round_robin",
                        "reassignment",
                        "not_interested_reassignment",
                    ],
                ),
            ]
            if rule.team_id:
                domain.append(("team_id", "=", rule.team_id.id))
            if rule.source_category:
                domain.append(("source_category", "=", rule.source_category))
            if rule.quality_id:
                domain.append(("lead_quality_id", "=", rule.quality_id.id))
            for lead in self.search(domain):
                if lead.source_id and not lead.source_id.sla_applicable:
                    continue
                if lead._stage_code(lead.stage_id) != "assigned":
                    continue
                lead._process_sla_rule(rule, now)
        return True

    def _process_sla_rule(self, rule, now):
        self.ensure_one()
        assignment_datetime = self.assigned_datetime
        elapsed = (now - assignment_datetime).total_seconds() / 60
        events = [
            ("reminder_1", rule.reminder_1_minutes),
            ("reminder_2", rule.reminder_2_minutes),
            ("reminder_3", rule.reminder_3_minutes),
            ("escalation", rule.escalation_minutes),
            ("reassignment", rule.reassignment_minutes),
        ]
        for event_type, minutes in events:
            if not minutes or elapsed < minutes:
                continue
            deadline = assignment_datetime + timedelta(minutes=minutes)
            existing = self.env["brokerage.crm.sla.log"].search_count([
                ("lead_id", "=", self.id), ("rule_id", "=", rule.id),
                ("event_type", "=", event_type),
                ("assignment_datetime", "=", assignment_datetime),
            ])
            if existing:
                continue

            if event_type == "reassignment":
                reassigned_user = self.env[
                    "brokerage.crm.round.robin"
                ].assign_lead_cross_team(
                    self,
                    preferred_team=rule.reassignment_team_id,
                    reason=_(
                        "Automatic cross-team reassignment after "
                        "manager escalation"
                    ),
                )
                if not reassigned_user:
                    continue
                self.env["brokerage.crm.sla.log"].create({
                    "lead_id": self.id,
                    "rule_id": rule.id,
                    "assignment_datetime": assignment_datetime,
                    "deadline": deadline,
                    "state": "breached",
                    "completed_at": now,
                    "event_type": event_type,
                })
                self._clear_open_brokerage_sla_activities()
                self.message_post(
                    body=_(
                        "SLA Reassignment triggered after %s minutes."
                    ) % minutes,
                    subtype_xmlid="mail.mt_note",
                )
                continue

            target_user = self.user_id
            if event_type == "escalation":
                target_user = (
                    rule.escalation_user_id
                    or self.team_id.user_id
                    or self.user_id
                )
            self.env["brokerage.crm.sla.log"].create({
                "lead_id": self.id, "rule_id": rule.id,
                "assignment_datetime": assignment_datetime,
                "deadline": deadline, "state": "breached",
                "completed_at": now, "event_type": event_type,
            })
            self.env["mail.activity"].create({
                "res_model_id": self.env["ir.model"]._get_id("crm.lead"),
                "res_id": self.id,
                "activity_type_id": rule.activity_type_id.id,
                "user_id": target_user.id,
                "date_deadline": fields.Date.context_today(self),
                "summary": _("SLA %s: update assigned lead") % event_type.replace("_", " ").title(),
                "note": _("No contact attempt or qualifying update was recorded within %s minutes.") % minutes,
            })
            self._queue_brokerage_whatsapp_sla(
                target_user,
                event_type,
                minutes,
                rule,
                assignment_datetime,
            )
            self.message_post(
                body=_("SLA %(event)s triggered after %(minutes)s minutes.") % {
                    "event": event_type.replace("_", " ").title(),
                    "minutes": minutes,
                },
                subtype_xmlid="mail.mt_note",
            )

    def _clear_open_brokerage_sla_activities(self):
        activities = self.env["mail.activity"].search([
            ("res_model", "=", "crm.lead"),
            ("res_id", "in", self.ids),
            ("summary", "ilike", "SLA "),
        ])
        activities.unlink()

    @api.depends(
        "contact_attempt_ids",
        "brokerage_meeting_ids",
        "assignment_history_ids",
    )
    def _compute_brokerage_counts(self):
        for lead in self:
            lead.contact_attempt_count = len(lead.contact_attempt_ids)
            lead.meeting_count = len(lead.brokerage_meeting_ids)
            lead.assignment_history_count = len(
                lead.assignment_history_ids
            )

    @api.constrains("budget_from", "budget_to")
    def _check_budget_range(self):
        for lead in self:
            if lead.budget_from < 0 or lead.budget_to < 0:
                raise ValidationError(
                    _("Budget values cannot be negative.")
                )

            if (
                lead.budget_from
                and lead.budget_to
                and lead.budget_from > lead.budget_to
            ):
                raise ValidationError(
                    _("Budget From cannot be greater than Budget To.")
                )
            
    @api.constrains("estimated_property_value")
    def _check_estimated_property_value(self):
        for lead in self:
            if lead.estimated_property_value < 0:
                raise ValidationError(
                    _("Estimated Property Value cannot be negative.")
                )
            
    @api.constrains(
        "preferred_developer_id",
        "preferred_project_id",
        "final_developer_id",
        "final_project_id",
    )
    def _check_project_developer_consistency(self):
        for lead in self:
            if (
                lead.preferred_project_id
                and lead.preferred_project_id.developer_id
                != lead.preferred_developer_id
            ):
                raise ValidationError(
                    _(
                        "The preferred project does not belong to "
                        "the selected preferred developer."
                    )
                )

            if (
                lead.final_project_id
                and lead.final_project_id.developer_id
                != lead.final_developer_id
            ):
                raise ValidationError(
                    _(
                        "The final project does not belong to "
                        "the selected final developer."
                    )
                )
            
    @api.onchange("preferred_developer_id")
    def _onchange_preferred_developer_id(self):
        if (
            self.preferred_project_id
            and self.preferred_project_id.developer_id
            != self.preferred_developer_id
        ):
            self.preferred_project_id = False


    @api.onchange("final_developer_id")
    def _onchange_final_developer_id(self):
        if (
            self.final_project_id
            and self.final_project_id.developer_id
            != self.final_developer_id
        ):
            self.final_project_id = False

    def action_view_contact_attempts(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": _("Contact Attempts"),
            "res_model": "brokerage.crm.contact.attempt",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {
                "default_lead_id": self.id,
            },
        }

    def action_view_brokerage_meetings(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": _("Meetings"),
            "res_model": "brokerage.crm.meeting",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {
                "default_lead_id": self.id,
            },
        }


    def action_view_assignment_history(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": _("Assignment History"),
            "res_model": "brokerage.crm.assignment.history",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {
                "default_lead_id": self.id,
                "create": False,
                "edit": False,
                "delete": False,
            },
        }
