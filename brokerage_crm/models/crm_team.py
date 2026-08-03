from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CrmTeam(models.Model):
    _inherit = "crm.team"

    # Keep Odoo's native hierarchy: Team Leader -> Salespersons.
    user_id = fields.Many2one(string="Team Leader")

    brokerage_solo_campaign = fields.Boolean(
        string="Solo Campaign Team",
        tracking=True,
        help=(
            "Leads explicitly routed to this team use an isolated solo "
            "rotation. This team is excluded from normal, cross-team, and "
            "Not Interested Round Robin pools."
        ),
    )
    brokerage_working_calendar_id = fields.Many2one(
        comodel_name="resource.calendar",
        string="SLA Working Hours",
        check_company=False,
        tracking=True,
        help=(
            "Only these working hours count toward assignment reminders and "
            "escalations. Leave empty to use the company's working calendar."
        ),
    )

    brokerage_solo_next_index = fields.Integer(
        string="Solo Next Position",
        default=0,
        readonly=True,
        copy=False,
    )
    brokerage_solo_assignment_count = fields.Integer(
        string="Solo Assignments",
        default=0,
        readonly=True,
        copy=False,
        help=(
            "Reporting total only. Solo Campaign assignment follows the "
            "configured Agent Rotation Order."
        ),
    )
    brokerage_solo_last_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Last Solo Salesperson",
        readonly=True,
        copy=False,
    )
    brokerage_solo_last_assignment_datetime = fields.Datetime(
        string="Last Solo Assignment",
        readonly=True,
        copy=False,
    )

    # These counters are stored on destination teams and are used only when a
    # lead exits a solo campaign after its final SLA escalation.
    brokerage_solo_cross_next_index = fields.Integer(
        string="Solo Exit Next Position",
        default=0,
        readonly=True,
        copy=False,
    )
    brokerage_solo_cross_assignment_count = fields.Integer(
        string="Solo Exit Assignments",
        default=0,
        readonly=True,
        copy=False,
        help=(
            "Reporting total only. A Solo Campaign exit follows the "
            "configured team sequence."
        ),
    )
    brokerage_solo_cross_last_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Last Solo Exit Salesperson",
        readonly=True,
        copy=False,
    )
    brokerage_solo_cross_last_assignment_datetime = fields.Datetime(
        string="Last Solo Exit Assignment",
        readonly=True,
        copy=False,
    )

    _solo_positions_non_negative = models.Constraint(
        """
        CHECK(
            brokerage_solo_next_index >= 0
            AND brokerage_solo_cross_next_index >= 0
        )
        """,
        "Solo campaign rotation positions cannot be negative.",
    )

    def _brokerage_team_leader(self):
        self.ensure_one()
        return self.user_id

    def write(self, vals):
        result = super().write(vals)
        if "user_id" in vals:
            self.env["brokerage.crm.round.robin"].sudo().search([
                ("team_id", "in", self.ids),
                ("active", "=", True),
            ])._sync_standard_team_memberships()
        return result

    def _brokerage_sla_calendar(self):
        self.ensure_one()
        return (
            self.brokerage_working_calendar_id
            or self.company_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )

    def _lock_brokerage_solo_state(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM crm_team WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset([
            "brokerage_solo_next_index",
            "brokerage_solo_assignment_count",
            "brokerage_solo_cross_next_index",
            "brokerage_solo_cross_assignment_count",
        ])

    def _brokerage_solo_agents(self):
        """Return available solo users in configured agent sequence.

        The Solo Campaign cursor is independent, but the people and their
        ordering come from the team's Round Robin configuration when one is
        active. Its normal counters and positions are never consumed.
        """
        self.ensure_one()
        leader = self.user_id
        queue = self.env[
            "brokerage.crm.round.robin"
        ].sudo().search([
            ("team_id", "=", self.id),
            ("active", "=", True),
        ], limit=1)
        agents = self.env["res.users"]
        if queue:
            eligible_users = queue.member_ids.filtered(
                lambda user:
                    user.active
                    and not user.share
                    and user.available_for_crm_assignment
            )
            ordered_lines = queue.agent_sequence_ids.filtered(
                lambda line: line.user_id in eligible_users
            ).sorted(key=lambda line: (line.sequence, line.user_id.id))
            ordered_users = ordered_lines.mapped("user_id")
            missing_users = (eligible_users - ordered_users).sorted(
                key=lambda user: user.id
            )
            agents = ordered_users | missing_users

        # Existing installations may not yet have a queue for a Solo
        # Campaign Team. Preserve a deterministic migration fallback using
        # its native CRM memberships; the Team Leader is used only when no
        # available member exists.
        if not agents:
            memberships = self.crm_team_member_ids.filtered(
                lambda membership:
                    membership.active
                    and membership.user_id.active
                    and not membership.user_id.share
                    and membership.user_id.available_for_crm_assignment
                    and membership.user_id != leader
            ).sorted(key=lambda membership: (
                membership.create_date or fields.Datetime.from_string(
                    "1970-01-01 00:00:00"
                ),
                membership.id,
            ))
            agents = memberships.mapped("user_id")

        if agents:
            return agents
        if (
            leader
            and leader.active
            and not leader.share
            and leader.available_for_crm_assignment
        ):
            return leader
        return self.env["res.users"]

    def assign_brokerage_solo_lead(self, lead, reason=None):
        """Assign inside a solo team using its independent sequence cursor."""
        self.ensure_one()
        lead.ensure_one()
        if not self.brokerage_solo_campaign:
            raise ValidationError(_(
                "%s is not configured as a Solo Campaign Team."
            ) % self.display_name)

        self._lock_brokerage_solo_state()
        users = self._brokerage_solo_agents()
        if not users:
            raise ValidationError(_(
                "Solo Campaign Team %s has no available Team Leader or agent."
            ) % self.display_name)

        index = self.brokerage_solo_next_index % len(users)
        selected_user = users[index]
        assigned_stage = lead._find_brokerage_stage(
            "assigned", team=self
        )
        if not assigned_stage:
            raise ValidationError(_(
                "Configure an Assigned CRM stage for Sales Team %s."
            ) % self.display_name)

        previous_user = lead.user_id
        previous_team = lead.team_id
        before_snapshot = lead._brokerage_assignment_snapshot()
        now = fields.Datetime.now()
        lead_values = {
            "team_id": self.id,
            "user_id": selected_user.id,
        }
        lead_values.update(
            lead._prepare_brokerage_assignment_cycle_values(
                "solo_campaign", now
            )
        )
        lead._clear_open_brokerage_sla_activities()
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write(lead_values)
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({"stage_id": assigned_stage.id})

        self.write({
            "brokerage_solo_next_index": (index + 1) % len(users),
            "brokerage_solo_assignment_count": (
                self.brokerage_solo_assignment_count + 1
            ),
            "brokerage_solo_last_user_id": selected_user.id,
            "brokerage_solo_last_assignment_datetime": now,
        })
        self.env["brokerage.crm.assignment.history"].sudo().create({
            "lead_id": lead.id,
            "source_id": lead.source_id.id or False,
            "previous_user_id": previous_user.id or False,
            "new_user_id": selected_user.id,
            "previous_team_id": previous_team.id or False,
            "new_team_id": self.id,
            "assignment_type": "solo_campaign",
            "assigned_datetime": now,
            "assigned_by_id": self.env.user.id,
            "reason": reason or _("Solo campaign assignment"),
            "round_robin_position": index,
            "previous_stage_id": before_snapshot.get("stage_id") or False,
            "new_stage_id": lead.stage_id.id or False,
            "before_snapshot": before_snapshot,
            "after_snapshot": lead._brokerage_assignment_snapshot(),
        })
        lead.message_post(
            body=Markup(_(
                "Opportunity assigned through the isolated Solo Campaign "
                "rotation to <b>%(user)s</b> in team <b>%(team)s</b>."
            )) % {
                "user": selected_user.display_name,
                "team": self.display_name,
            },
            subtype_xmlid="mail.mt_note",
        )
        lead._queue_brokerage_whatsapp_assignment(
            selected_user,
            reason or _("New solo campaign lead"),
        )
        return selected_user

    @api.model
    def assign_brokerage_solo_cross_team(
        self, lead, preferred_team=False, reason=None
    ):
        """Reassign inside the solo team before exiting by team sequence."""
        lead.ensure_one()
        if not lead.team_id.brokerage_solo_campaign:
            return self.env["res.users"]

        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            ["brokerage.crm.solo.cross.team.dispatch"],
        )
        queue_model = self.env["brokerage.crm.round.robin"].sudo()
        current_team = lead.team_id
        same_team = False
        target_team = self.env["crm.team"]
        target_queue = queue_model
        users = current_team._brokerage_solo_agents()
        selected_user = self.env["res.users"]
        index = 0

        attempted = queue_model._current_team_visit_users(lead)
        available = queue_model._users_after_current(
            users,
            lead.user_id,
        ).filtered(lambda user: user not in attempted)
        if available:
            same_team = True
            target_team = current_team
            target_queue = queue_model.search([
                ("team_id", "=", current_team.id),
                ("active", "=", True),
            ], limit=1)
            selected_user = available[:1]
            index = users.ids.index(selected_user.id)

        if not selected_user:
            if preferred_team:
                candidate_queues = queue_model.search([
                    ("active", "=", True),
                    ("team_id", "=", preferred_team.id),
                    ("team_id.brokerage_solo_campaign", "=", False),
                ], order="sequence, id")
            else:
                all_queues = queue_model.search(
                    [("active", "=", True)],
                    order="sequence, id",
                )
                candidate_queues = queue_model._rules_after_current_team(
                    all_queues,
                    current_team,
                ).filtered(
                    lambda queue: not queue.team_id.brokerage_solo_campaign
                )
            for queue in candidate_queues:
                available = queue._get_eligible_users().filtered(
                    lambda user: user != lead.user_id
                )
                if available:
                    target_team = queue.team_id
                    target_queue = queue
                    users = available
                    break
            if not target_team:
                return self.env["res.users"]

            target_team._lock_brokerage_solo_state()
            users = target_queue._get_eligible_users().filtered(
                lambda user: user != lead.user_id
            )
            if not users:
                return self.env["res.users"]
            index = target_team.brokerage_solo_cross_next_index % len(users)
            selected_user = users[index]
        assigned_stage = lead._find_brokerage_stage(
            "assigned", team=target_team
        )
        if not assigned_stage:
            return self.env["res.users"]

        previous_user = lead.user_id
        previous_team = lead.team_id
        before_snapshot = lead._brokerage_assignment_snapshot()
        now = fields.Datetime.now()
        lead_values = {
            "team_id": target_team.id,
            "user_id": selected_user.id,
        }
        lead_values.update(
            lead._prepare_brokerage_assignment_cycle_values(
                "reassignment", now
            )
        )
        lead._clear_open_brokerage_sla_activities()
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write(lead_values)
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({"stage_id": assigned_stage.id})

        if not same_team:
            target_team.write({
                "brokerage_solo_cross_next_index": (
                    (index + 1) % len(users)
                ),
                "brokerage_solo_cross_assignment_count": (
                    target_team.brokerage_solo_cross_assignment_count + 1
                ),
                "brokerage_solo_cross_last_user_id": selected_user.id,
                "brokerage_solo_cross_last_assignment_datetime": now,
            })
        default_reason = (
            _("Solo campaign same-team reassignment after SLA breach")
            if same_team
            else _("Solo campaign cross-team reassignment after SLA breach")
        )
        self.env["brokerage.crm.assignment.history"].sudo().create({
            "lead_id": lead.id,
            "source_id": lead.source_id.id or False,
            "previous_user_id": previous_user.id or False,
            "new_user_id": selected_user.id,
            "previous_team_id": previous_team.id or False,
            "new_team_id": target_team.id,
            "assignment_type": "reassignment",
            "assigned_datetime": now,
            "assigned_by_id": self.env.user.id,
            "reason": reason or default_reason,
            "round_robin_id": target_queue.id or False,
            "round_robin_position": index,
            "previous_stage_id": before_snapshot.get("stage_id") or False,
            "new_stage_id": lead.stage_id.id or False,
            "before_snapshot": before_snapshot,
            "after_snapshot": lead._brokerage_assignment_snapshot(),
        })
        lead.message_post(
            body=Markup(_(
                "Solo campaign opportunity reassigned %(route)s after SLA "
                "from "
                "<b>%(old_user)s</b> / <b>%(old_team)s</b> to "
                "<b>%(new_user)s</b> / <b>%(new_team)s</b>. Existing normal, "
                "cross-team, and Not Interested queues were not changed."
            )) % {
                "route": _("within the same team") if same_team else _(
                    "across teams"
                ),
                "old_user": previous_user.display_name or "-",
                "old_team": previous_team.display_name or "-",
                "new_user": selected_user.display_name,
                "new_team": target_team.display_name,
            },
            subtype_xmlid="mail.mt_note",
        )
        lead._queue_brokerage_whatsapp_assignment(
            selected_user,
            reason or default_reason,
        )
        return selected_user
