from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CrmRoundRobin(models.Model):
    _name = "brokerage.crm.round.robin"
    _description = "CRM Round Robin Configuration"
    _order = "sequence, name, id"

    name = fields.Char(
        required=True,
        index=True,
    )

    sequence = fields.Integer(
        default=10,
    )

    active = fields.Boolean(
        default=True,
    )

    team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Sales Team",
        required=True,
        ondelete="cascade",
        index=True,
    )
    team_leader_id = fields.Many2one(
        related="team_id.user_id",
        string="Team Leader",
        readonly=True,
    )
    team_solo_campaign = fields.Boolean(
        related="team_id.brokerage_solo_campaign",
        string="Solo Campaign Team",
        readonly=True,
    )

    member_ids = fields.Many2many(
        comodel_name="res.users",
        relation="brokerage_round_robin_user_rel",
        column1="round_robin_id",
        column2="user_id",
        string="Eligible Salespeople",
        domain=[
            ("share", "=", False),
            ("active", "=", True),
        ],
        required=True,
    )
    agent_sequence_ids = fields.One2many(
        comodel_name="brokerage.crm.round.robin.agent",
        inverse_name="round_robin_id",
        string="Agent Rotation Order",
        copy=True,
    )

    next_index = fields.Integer(
        string="Next Agent Position",
        default=0,
        readonly=True,
        copy=False,
    )

    last_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Last Assigned Salesperson",
        readonly=True,
        copy=False,
    )

    last_assignment_datetime = fields.Datetime(
        string="Last Assignment Date/Time",
        readonly=True,
        copy=False,
    )

    assignment_count = fields.Integer(
        string="Total Assignments",
        default=0,
        readonly=True,
        copy=False,
    )

    cross_team_next_index = fields.Integer(
        string="Cross-team Next Position",
        default=0,
        readonly=True,
        copy=False,
    )

    cross_team_assignment_count = fields.Integer(
        string="Cross-team Assignments",
        default=0,
        readonly=True,
        copy=False,
        help=(
            "Reporting total only. The next cross-team destination follows "
            "the configured team sequence."
        ),
    )

    last_cross_team_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Last Cross-team Salesperson",
        readonly=True,
        copy=False,
    )

    last_cross_team_assignment_datetime = fields.Datetime(
        string="Last Cross-team Assignment",
        readonly=True,
        copy=False,
    )

    not_interested_next_index = fields.Integer(
        string="Not Interested Next Position",
        default=0,
        readonly=True,
        copy=False,
    )

    not_interested_assignment_count = fields.Integer(
        string="Not Interested Assignments",
        default=0,
        readonly=True,
        copy=False,
        help=(
            "Reporting total only. A cross-team Not Interested handoff "
            "follows the configured team sequence."
        ),
    )

    last_not_interested_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Last Not Interested Salesperson",
        readonly=True,
        copy=False,
    )

    last_not_interested_assignment_datetime = fields.Datetime(
        string="Last Not Interested Assignment",
        readonly=True,
        copy=False,
    )

    _team_unique = models.Constraint(
        "UNIQUE(team_id)",
        "Only one Round Robin configuration is allowed per Sales Team.",
    )

    _next_index_non_negative = models.Constraint(
        "CHECK(next_index >= 0)",
        "The next assignment position cannot be negative.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        configurations = super().create(vals_list)
        configurations._sync_agent_sequence_lines()
        configurations._sync_standard_team_memberships()
        return configurations

    def write(self, vals):
        result = super().write(vals)
        if "member_ids" in vals:
            self._sync_agent_sequence_lines()
        if {"active", "member_ids", "team_id"} & set(vals):
            self._sync_standard_team_memberships()
        return result

    def _sync_standard_team_memberships(self):
        """Keep Odoo team access aligned with the brokerage queue.

        The custom eligible-salespeople list controls assignment, while
        ``crm.team.member`` controls the stages and leads a non-admin user can
        see.  Eligible people and the Team Leader therefore need an active
        native membership as well.
        """
        membership_model = self.env["crm.team.member"].sudo().with_context(
            active_test=False,
        )
        for configuration in self.filtered("active"):
            users = (
                configuration.member_ids
                | configuration.team_id.user_id
            ).filtered(
                lambda user: user.active and not user.share
            )
            for user in users:
                membership = membership_model.search([
                    ("crm_team_id", "=", configuration.team_id.id),
                    ("user_id", "=", user.id),
                ], order="active desc, id", limit=1)
                if membership:
                    if not membership.active:
                        membership.write({"active": True})
                else:
                    membership_model.create({
                        "crm_team_id": configuration.team_id.id,
                        "user_id": user.id,
                    })
        return True

    @api.model
    def _sync_all_standard_team_memberships(self):
        self.sudo().search([("active", "=", True)])._sync_standard_team_memberships()
        return True

    def _sync_agent_sequence_lines(self):
        line_model = self.env["brokerage.crm.round.robin.agent"]
        for configuration in self:
            lines = configuration.agent_sequence_ids
            removed_lines = lines.filtered(
                lambda line: line.user_id not in configuration.member_ids
            )
            if removed_lines:
                removed_lines.unlink()
            remaining_lines = lines - removed_lines
            existing_users = remaining_lines.mapped("user_id")
            next_sequence = max(
                remaining_lines.mapped("sequence") or [0]
            )
            for user in (configuration.member_ids - existing_users).sorted(
                key=lambda member: member.id
            ):
                next_sequence += 10
                line_model.create({
                    "round_robin_id": configuration.id,
                    "user_id": user.id,
                    "sequence": next_sequence,
                })
        return True

    @api.constrains("member_ids", "team_id")
    def _check_members(self):
        for rule in self:
            if not rule.member_ids:
                raise ValidationError(
                    _("Add at least one salesperson to the Round Robin.")
                )

            invalid_users = rule.member_ids.filtered(
                lambda user: user.share
            )
            if invalid_users:
                raise ValidationError(
                    _(
                        "Portal users cannot be included in Round Robin: %s"
                    ) % ", ".join(invalid_users.mapped("display_name"))
                )
    def _get_eligible_users(self):
        self.ensure_one()

        if self.team_id.brokerage_solo_campaign:
            return self.env["res.users"]

        eligible_users = self.member_ids.filtered(
            lambda user:
                user.active
                and not user.share
                and user.available_for_crm_assignment
        )
        ordered_lines = self.agent_sequence_ids.filtered(
            lambda line: line.user_id in eligible_users
        ).sorted(key=lambda line: (line.sequence, line.user_id.id))
        ordered_users = ordered_lines.mapped("user_id")
        missing_users = (eligible_users - ordered_users).sorted(
            key=lambda user: user.id
        )
        return ordered_users | missing_users

    def _lock_configuration(self):
        """Prevent concurrent requests from consuming the same position."""
        self.ensure_one()

        self.env.cr.execute(
            """
            SELECT id
              FROM brokerage_crm_round_robin
             WHERE id = %s
             FOR UPDATE
            """,
            [self.id],
        )

        self.invalidate_recordset([
            "next_index",
            "last_user_id",
            "assignment_count",
            "member_ids",
            "cross_team_next_index",
            "cross_team_assignment_count",
            "not_interested_next_index",
            "not_interested_assignment_count",
        ])

    def get_next_user(self):
        self.ensure_one()

        if not self.active:
            raise ValidationError(
                _("The Round Robin configuration is inactive.")
            )

        self._lock_configuration()

        users = self._get_eligible_users()

        if not users:
            raise ValidationError(
                _(
                    "No eligible salesperson is available for Sales Team %s."
                ) % self.team_id.display_name
            )

        index = self.next_index % len(users)
        selected_user = users[index]

        return selected_user, index, len(users)

    @api.model
    def assign_lead_by_normal_sequence(self, lead, reason=None):
        """Assign a new lead by team sequence, not by assignment totals.

        The company cursor identifies the next configured team. Unavailable
        teams are skipped without being removed from the sequence, and the
        cursor advances only after a successful assignment.
        """
        lead.ensure_one()
        company = lead.company_id or self.env.company

        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [
                "brokerage.crm.normal.round.robin.dispatch."
                f"{company.id}"
            ],
        )

        configurations = self.sudo().search(
            [
                ("active", "=", True),
                ("team_id.brokerage_solo_campaign", "=", False),
                "|",
                ("team_id.company_id", "=", False),
                ("team_id.company_id", "=", company.id),
            ],
            order="sequence, id",
        )
        if not configurations:
            raise ValidationError(_(
                "No active Round Robin configuration exists for any Sales "
                "Team."
            ))

        next_rule = company.sudo().brokerage_normal_rr_next_rule_id
        configuration_ids = configurations.ids
        start_index = (
            configuration_ids.index(next_rule.id)
            if next_rule.id in configuration_ids
            else 0
        )

        selected_rule = self.env["brokerage.crm.round.robin"]
        selected_index = 0
        for offset in range(len(configurations)):
            candidate_index = (
                start_index + offset
            ) % len(configurations)
            candidate = configurations[candidate_index]
            if candidate._get_eligible_users():
                selected_rule = candidate
                selected_index = candidate_index
                break

        if not selected_rule:
            raise ValidationError(_(
                "No active Round Robin configuration with eligible agents "
                "exists for any Sales Team."
            ))

        selected_user = selected_rule.assign_lead(
            lead.sudo(),
            reason=reason,
        )
        following_rule = configurations[
            (selected_index + 1) % len(configurations)
        ]
        company.sudo().write({
            "brokerage_normal_rr_next_rule_id": following_rule.id,
        })
        return selected_user

    def assign_lead(self, lead, reason=None):
        self.ensure_one()
        lead.ensure_one()

        if lead.type == "lead":
            # This is allowed if the client uses Leads, but the same
            # assignment mechanism still applies.
            pass

        selected_user, index, total_users = self.get_next_user()

        previous_user = lead.user_id
        previous_team = lead.team_id
        before_snapshot = lead._brokerage_assignment_snapshot()
        now = fields.Datetime.now()
        assigned_stage = lead._find_brokerage_stage(
            "assigned", team=self.team_id
        )
        if not assigned_stage:
            raise ValidationError(_(
                "Configure an Assigned CRM stage for Sales Team %s before "
                "using Round Robin."
            ) % self.team_id.display_name)

        lead_values = {
            "team_id": self.team_id.id,
            "user_id": selected_user.id,
        }
        lead_values.update(
            lead._prepare_brokerage_assignment_cycle_values(
                "round_robin", now
            )
        )
        lead._clear_open_brokerage_sla_activities()
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write(lead_values)

        # stage_id is a stored computed field depending on team_id. Writing
        # the new team and a team-specific stage together can make Odoo
        # recompute the stage against the previous team and restore New Lead.
        # Set the stage after the team write so Assigned always persists.
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({"stage_id": assigned_stage.id})

        next_index = (index + 1) % total_users

        self.write({
            "next_index": next_index,
            "last_user_id": selected_user.id,
            "last_assignment_datetime": now,
            "assignment_count": self.assignment_count + 1,
        })

        self.env["brokerage.crm.assignment.history"].create({
            "lead_id": lead.id,
            "source_id": lead.source_id.id or False,
            "previous_user_id": previous_user.id or False,
            "new_user_id": selected_user.id,
            "previous_team_id": previous_team.id or False,
            "new_team_id": self.team_id.id,
            "assignment_type": "round_robin",
            "assigned_datetime": now,
            "assigned_by_id": self.env.user.id,
            "reason": reason or _("Round Robin assignment"),
            "round_robin_id": self.id,
            "round_robin_position": index,
            "previous_stage_id": before_snapshot.get("stage_id") or False,
            "new_stage_id": lead.stage_id.id or False,
            "before_snapshot": before_snapshot,
            "after_snapshot": lead._brokerage_assignment_snapshot(),
        })

        lead.message_post(
            body=Markup(_(
                "Opportunity assigned through Round Robin to "
                "<b>%(user)s</b> in team <b>%(team)s</b>."
            )) % {
                "user": selected_user.display_name,
                "team": self.team_id.display_name,
            },
            subtype_xmlid="mail.mt_note",
        )
        lead._queue_brokerage_whatsapp_assignment(
            selected_user,
            reason or _("Round Robin assignment"),
        )

        return selected_user

    @api.model
    def _users_after_current(self, users, current_user):
        """Rotate an ordered user set so the next person comes first."""
        if not users:
            return users
        user_ids = users.ids
        start_index = (
            (user_ids.index(current_user.id) + 1) % len(users)
            if current_user and current_user.id in user_ids
            else 0
        )
        return users.browse(
            user_ids[start_index:] + user_ids[:start_index]
        )

    @api.model
    def _current_team_visit_users(self, lead):
        """People already tried since this lead most recently entered a team."""
        lead.ensure_one()
        attempted = lead.user_id
        histories = lead.assignment_history_ids.sorted(
            key=lambda history: (
                history.assigned_datetime,
                history.id,
            ),
            reverse=True,
        )
        for history in histories:
            if history.new_team_id != lead.team_id:
                break
            attempted |= history.new_user_id
            if history.previous_team_id != lead.team_id:
                break
        return attempted

    @api.model
    def _rules_after_current_team(self, configurations, current_team):
        """Rotate team rules according to hierarchy sequence.

        The first candidate is the configured team immediately after the
        current team.  The order wraps after the last team.  Assignment
        counters are intentionally not involved in this selection.
        """
        if not configurations:
            return configurations
        rule_ids = configurations.ids
        current_rule = configurations.filtered(
            lambda configuration: configuration.team_id == current_team
        )[:1]
        if not current_rule:
            return configurations
        start_index = (rule_ids.index(current_rule.id) + 1) % len(rule_ids)
        rotated_ids = rule_ids[start_index:] + rule_ids[:start_index]
        return configurations.browse(rotated_ids).filtered(
            lambda configuration: configuration != current_rule
        )

    @api.model
    def assign_lead_cross_team(
        self, lead, preferred_team=False, reason=None
    ):
        """Exhaust the current team before using the cross-team queue.

        Every handoff starts a fresh assignment/SLA cycle.  Same-team
        handoffs use the configured agent sequence and do not consume the
        independent normal or cross-team queue. Once the current team has
        been exhausted, the next team in configured hierarchy sequence is
        used.
        """
        lead.ensure_one()

        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            ["brokerage.crm.cross.team.dispatch"],
        )

        target_rule = self.sudo().search([
            ("active", "=", True),
            ("team_id", "=", lead.team_id.id),
            ("team_id.brokerage_solo_campaign", "=", False),
        ], limit=1)
        same_team = False
        users = self.env["res.users"]
        selected_user = self.env["res.users"]
        index = 0

        if target_rule:
            target_rule._lock_configuration()
            ordered_users = target_rule._get_eligible_users()
            attempted = self._current_team_visit_users(lead)
            available = self._users_after_current(
                ordered_users,
                lead.user_id,
            ).filtered(lambda user: user not in attempted)
            if available:
                same_team = True
                users = ordered_users
                selected_user = available[:1]
                index = users.ids.index(selected_user.id)

        if not selected_user:
            domain = [
                ("active", "=", True),
                ("team_id.brokerage_solo_campaign", "=", False),
            ]
            if preferred_team:
                domain.append(("team_id", "=", preferred_team.id))

            configurations = self.sudo().search(
                domain,
                order="sequence, id",
            )
            if not preferred_team:
                configurations = self._rules_after_current_team(
                    configurations,
                    lead.team_id,
                )
            target_rule = configurations.filtered(
                lambda configuration: bool(
                    configuration.team_id != lead.team_id
                    and
                    configuration._get_eligible_users().filtered(
                        lambda user: user != lead.user_id
                    )
                )
            )[:1]
            if not target_rule:
                return self.env["res.users"]

            target_rule._lock_configuration()
            users = target_rule._get_eligible_users().filtered(
                lambda user: user != lead.user_id
            )
            if not users:
                return self.env["res.users"]

            index = target_rule.cross_team_next_index % len(users)
            selected_user = users[index]

        assigned_stage = lead._find_brokerage_stage(
            "assigned", team=target_rule.team_id
        )
        if not assigned_stage:
            return self.env["res.users"]

        previous_user = lead.user_id
        previous_team = lead.team_id
        before_snapshot = lead._brokerage_assignment_snapshot()
        now = fields.Datetime.now()

        lead_values = {
            "team_id": target_rule.team_id.id,
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
            target_rule.write({
                "cross_team_next_index": (index + 1) % len(users),
                "cross_team_assignment_count": (
                    target_rule.cross_team_assignment_count + 1
                ),
                "last_cross_team_user_id": selected_user.id,
                "last_cross_team_assignment_datetime": now,
            })

        default_reason = (
            _("Automatic same-team reassignment after SLA breach")
            if same_team
            else _("Automatic cross-team reassignment after SLA breach")
        )

        self.env["brokerage.crm.assignment.history"].create({
            "lead_id": lead.id,
            "source_id": lead.source_id.id or False,
            "previous_user_id": previous_user.id or False,
            "new_user_id": selected_user.id,
            "previous_team_id": previous_team.id or False,
            "new_team_id": target_rule.team_id.id,
            "assignment_type": "reassignment",
            "assigned_datetime": now,
            "assigned_by_id": self.env.user.id,
            "reason": reason or default_reason,
            "round_robin_id": target_rule.id,
            "round_robin_position": index,
            "previous_stage_id": before_snapshot.get("stage_id") or False,
            "new_stage_id": lead.stage_id.id or False,
            "before_snapshot": before_snapshot,
            "after_snapshot": lead._brokerage_assignment_snapshot(),
        })

        lead.message_post(
            body=Markup(_(
                "Opportunity %(route)s reassigned from "
                "<b>%(old_user)s</b> / <b>%(old_team)s</b> to "
                "<b>%(new_user)s</b> / <b>%(new_team)s</b>. "
            )) % {
                "route": _("within the same team") if same_team else _(
                    "across teams"
                ),
                "old_user": previous_user.display_name or "-",
                "old_team": previous_team.display_name or "-",
                "new_user": selected_user.display_name,
                "new_team": target_rule.team_id.display_name,
            },
            subtype_xmlid="mail.mt_note",
        )
        lead._queue_brokerage_whatsapp_assignment(
            selected_user,
            reason or default_reason,
        )

        return selected_user

    @api.model
    def assign_lead_not_interested_once(self, lead, reason=None):
        """Hand off once inside the team, then fall back across teams."""
        lead.ensure_one()
        assigned_by = self.env.user
        lead_sudo = lead.sudo()

        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            ["brokerage.crm.not.interested.dispatch"],
        )
        self.env.cr.execute(
            "SELECT id FROM crm_lead WHERE id = %s FOR UPDATE",
            [lead.id],
        )
        lead_sudo.invalidate_recordset([
            "not_interested_reassignment_done",
            "team_id",
            "user_id",
        ])
        if lead_sudo.not_interested_reassignment_done:
            return self.env["res.users"]

        target_rule = self.sudo().search([
            ("active", "=", True),
            ("team_id", "=", lead_sudo.team_id.id),
            ("team_id.brokerage_solo_campaign", "=", False),
        ], limit=1)
        same_team = False
        users = self.env["res.users"]
        selected_user = self.env["res.users"]
        index = 0

        if target_rule:
            target_rule._lock_configuration()
            users = target_rule._get_eligible_users()
            available = self._users_after_current(
                users,
                lead_sudo.user_id,
            ).filtered(lambda user: user != lead_sudo.user_id)
            if available:
                same_team = True
                selected_user = available[:1]
                index = users.ids.index(selected_user.id)

        if not selected_user:
            configurations = self.sudo().search(
                [
                    ("active", "=", True),
                    ("team_id.brokerage_solo_campaign", "=", False),
                ],
                order="sequence, id",
            )
            configurations = self._rules_after_current_team(
                configurations,
                lead_sudo.team_id,
            )
            target_rule = configurations.filtered(
                lambda configuration: bool(
                    configuration.team_id != lead_sudo.team_id
                    and
                    configuration._get_eligible_users().filtered(
                        lambda user: user != lead_sudo.user_id
                    )
                )
            )[:1]
            if not target_rule:
                raise ValidationError(_(
                    "No eligible salesperson is available for the Not "
                    "Interested reassignment."
                ))

            target_rule._lock_configuration()
            users = target_rule._get_eligible_users().filtered(
                lambda user: user != lead_sudo.user_id
            )
            if not users:
                raise ValidationError(_(
                    "No eligible salesperson is available for the Not "
                    "Interested reassignment."
                ))

            index = target_rule.not_interested_next_index % len(users)
            selected_user = users[index]
        assigned_stage = lead_sudo._find_brokerage_stage(
            "assigned", team=target_rule.team_id
        )
        if not assigned_stage:
            raise ValidationError(_(
                "Configure an Assigned CRM stage for Sales Team %s before "
                "using the Not Interested reassignment."
            ) % target_rule.team_id.display_name)

        previous_user = lead_sudo.user_id
        previous_team = lead_sudo.team_id
        before_snapshot = lead_sudo._brokerage_assignment_snapshot()
        now = fields.Datetime.now()

        lead_sudo._clear_open_brokerage_sla_activities()
        lead_values = {
            "team_id": target_rule.team_id.id,
            "user_id": selected_user.id,
            "not_interested_reassignment_done": True,
        }
        lead_values.update(
            lead_sudo._prepare_brokerage_assignment_cycle_values(
                "not_interested_reassignment", now
            )
        )
        lead_sudo.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write(lead_values)
        lead_sudo.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({"stage_id": assigned_stage.id})

        target_rule.write({
            "not_interested_next_index": (index + 1) % len(users),
            "not_interested_assignment_count": (
                target_rule.not_interested_assignment_count + 1
            ),
            "last_not_interested_user_id": selected_user.id,
            "last_not_interested_assignment_datetime": now,
        })

        default_reason = (
            _("One-time same-team reassignment after Not Interested")
            if same_team
            else _("One-time cross-team reassignment after Not Interested")
        )
        self.env["brokerage.crm.assignment.history"].sudo().create({
            "lead_id": lead_sudo.id,
            "source_id": lead_sudo.source_id.id or False,
            "previous_user_id": previous_user.id or False,
            "new_user_id": selected_user.id,
            "previous_team_id": previous_team.id or False,
            "new_team_id": target_rule.team_id.id,
            "assignment_type": "not_interested_reassignment",
            "assigned_datetime": now,
            "assigned_by_id": assigned_by.id,
            "reason": reason or default_reason,
            "round_robin_id": target_rule.id,
            "round_robin_position": index,
            "previous_stage_id": before_snapshot.get("stage_id") or False,
            "new_stage_id": lead_sudo.stage_id.id or False,
            "before_snapshot": before_snapshot,
            "after_snapshot": lead_sudo._brokerage_assignment_snapshot(),
        })

        lead_sudo.message_post(
            body=Markup(_(
                "Opportunity marked Not Interested and reassigned once from "
                "<b>%(old_user)s</b> / <b>%(old_team)s</b> to "
                "<b>%(new_user)s</b> / <b>%(new_team)s</b> "
                "(%(route)s). The normal Round Robin queue was not changed."
            )) % {
                "old_user": previous_user.display_name or "-",
                "old_team": previous_team.display_name or "-",
                "new_user": selected_user.display_name,
                "new_team": target_rule.team_id.display_name,
                "route": _("same team") if same_team else _("cross team"),
            },
            subtype_xmlid="mail.mt_note",
            author_id=assigned_by.partner_id.id,
        )
        lead_sudo._queue_brokerage_whatsapp_assignment(
            selected_user,
            reason or default_reason,
        )

        return selected_user

    def action_reset_rotation(self):
        for rule in self:
            rule.write({
                "next_index": 0,
                "last_user_id": False,
                "last_assignment_datetime": False,
            })

        return True
