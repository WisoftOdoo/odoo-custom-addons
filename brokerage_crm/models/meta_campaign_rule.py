from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class BrokerageCampaignRoutingPolicy(models.Model):
    """Campaign routing with independent team and salesperson cursors."""

    _name = "brokerage.meta.campaign.rule"  # retained for upgrade compatibility
    _description = "Campaign Routing Policy"
    _order = "sequence, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True,
    )
    utm_campaign_id = fields.Many2one(
        "utm.campaign", string="Odoo Campaign", ondelete="restrict", index=True,
        help="Matches API, imported and manually created leads by Campaign.",
    )
    meta_page_id = fields.Char(string="Meta Page ID", index=True)
    meta_campaign_id = fields.Char(string="Meta Campaign ID", index=True)
    meta_campaign_name = fields.Char(string="Meta Campaign Name")
    meta_form_id = fields.Char(
        string="Meta Form ID", index=True,
        help="Optional. A form-specific policy overrides its campaign-wide policy.",
    )
    assignment_type = fields.Selection(
        [("round_robin", "Round Robin"), ("manual", "Manual / New Lead")],
        default="round_robin",
        help="Deprecated compatibility value maintained automatically.",
    )
    routing_mode = fields.Selection(
        [
            ("manual", "Manual / New Lead"),
            ("global", "Global Round Robin"),
            ("dedicated_team", "Dedicated Team"),
            ("shared_teams", "Shared Teams"),
        ], required=True, default="global",
    )
    team_ids = fields.Many2many(
        "crm.team", "brokerage_campaign_policy_team_rel", "policy_id", "team_id",
        string="Permitted Teams", check_company=True,
    )
    fallback_mode = fields.Selection(
        [
            ("manager_review", "Manager Review"),
            ("hold", "Keep With Last Salesperson"),
            ("selected_teams", "Selected Fallback Teams"),
            ("global", "Global Round Robin Teams"),
        ], required=True, default="manager_review",
        help="Used only after every eligible salesperson in the primary pool was tried.",
    )
    fallback_team_ids = fields.Many2many(
        "crm.team", "brokerage_campaign_policy_fallback_team_rel",
        "policy_id", "team_id", string="Fallback Teams", check_company=True,
    )
    next_team_id = fields.Many2one("crm.team", readonly=True, copy=False)
    fallback_next_team_id = fields.Many2one("crm.team", readonly=True, copy=False)
    assignment_count = fields.Integer(readonly=True, copy=False)
    reassignment_count = fields.Integer(readonly=True, copy=False)
    not_interested_count = fields.Integer(readonly=True, copy=False)
    last_team_id = fields.Many2one("crm.team", readonly=True, copy=False)
    last_user_id = fields.Many2one("res.users", readonly=True, copy=False)
    last_assignment_datetime = fields.Datetime(readonly=True, copy=False)
    team_state_ids = fields.One2many(
        "brokerage.meta.campaign.team.state", "policy_id", readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._normalize_identifiers(vals)
            if "routing_mode" not in vals and vals.get("assignment_type"):
                vals["routing_mode"] = "manual" if vals["assignment_type"] == "manual" else "global"
        return super().create(vals_list)

    def init(self):
        """Preserve the meaning of pre-policy Manual Meta rules on upgrade."""
        self.env.cr.execute(
            """
            UPDATE brokerage_meta_campaign_rule
               SET routing_mode = 'manual'
             WHERE assignment_type = 'manual'
               AND routing_mode IS DISTINCT FROM 'manual'
            """
        )

    def write(self, vals):
        vals = dict(vals)
        self._normalize_identifiers(vals)
        if "routing_mode" in vals:
            vals["assignment_type"] = "manual" if vals["routing_mode"] == "manual" else "round_robin"
        return super().write(vals)

    @api.model
    def _normalize_identifiers(self, vals):
        for field_name in ("meta_page_id", "meta_campaign_id", "meta_form_id"):
            if field_name in vals:
                vals[field_name] = str(vals[field_name] or "").strip() or False

    @api.constrains("routing_mode", "team_ids", "fallback_mode", "fallback_team_ids")
    def _check_routing_configuration(self):
        for policy in self:
            if policy.routing_mode == "dedicated_team" and len(policy.team_ids) != 1:
                raise ValidationError(_("A Dedicated Team policy must contain exactly one team."))
            if policy.routing_mode == "shared_teams" and len(policy.team_ids) < 2:
                raise ValidationError(_("A Shared Teams policy must contain at least two teams."))
            if policy.routing_mode in ("manual", "global") and policy.team_ids:
                raise ValidationError(_("Permitted Teams apply only to Dedicated Team and Shared Teams policies."))
            if policy.fallback_mode == "selected_teams" and not policy.fallback_team_ids:
                raise ValidationError(_("Select at least one fallback team."))
            if policy.team_ids & policy.fallback_team_ids:
                raise ValidationError(_("A team cannot be in both primary and fallback pools."))

    @api.constrains("active", "company_id", "utm_campaign_id", "meta_page_id", "meta_campaign_id", "meta_form_id")
    def _check_unique_scope(self):
        for policy in self.filtered("active"):
            if not policy.utm_campaign_id and not (policy.meta_page_id and policy.meta_campaign_id):
                raise ValidationError(_("Configure an Odoo Campaign or both Meta Page ID and Meta Campaign ID."))
            scopes = []
            if policy.utm_campaign_id:
                scopes.append([("utm_campaign_id", "=", policy.utm_campaign_id.id)])
            if policy.meta_page_id and policy.meta_campaign_id:
                scopes.append([
                    ("meta_page_id", "=", policy.meta_page_id),
                    ("meta_campaign_id", "=", policy.meta_campaign_id),
                    ("meta_form_id", "=", policy.meta_form_id or False),
                ])
            for scope in scopes:
                if self.search_count([
                    ("id", "!=", policy.id), ("active", "=", True),
                    ("company_id", "=", policy.company_id.id), *scope,
                ]):
                    raise ValidationError(_("Another active policy already uses this campaign scope."))

    @api.model
    def policy_for_meta(self, page_id, campaign_id, form_id=False, company=False):
        page_id, campaign_id = str(page_id or "").strip(), str(campaign_id or "").strip()
        form_id = str(form_id or "").strip()
        if not page_id or not campaign_id:
            return self.browse()
        company = company or self.env.company
        base = [
            ("active", "=", True), ("company_id", "=", company.id),
            ("meta_page_id", "=", page_id), ("meta_campaign_id", "=", campaign_id),
        ]
        if form_id:
            exact = self.sudo().search(base + [("meta_form_id", "=", form_id)], limit=1)
            if exact:
                return exact
        return self.sudo().search(base + [("meta_form_id", "=", False)], limit=1)

    @api.model
    def policy_for_utm_campaign(self, campaign, company=False):
        if not campaign:
            return self.browse()
        company = company or self.env.company
        return self.sudo().search([
            ("active", "=", True), ("company_id", "=", company.id),
            ("utm_campaign_id", "=", campaign.id),
        ], order="sequence, id", limit=1)

    @api.model
    def assignment_type_for(self, page_id, campaign_id, form_id=False):
        policy = self.policy_for_meta(page_id, campaign_id, form_id)
        return "round_robin" if policy and policy.routing_mode != "manual" else "manual"

    def _ordered_teams(self, fallback=False):
        self.ensure_one()
        mode = self.fallback_mode if fallback else self.routing_mode
        if mode in ("dedicated_team", "shared_teams"):
            teams = self.team_ids
        elif mode == "selected_teams":
            teams = self.fallback_team_ids
        elif mode == "global":
            teams = self.env["crm.team"].sudo().search([
                ("active", "=", True),
                ("company_id", "in", [False, self.company_id.id]),
                ("brokerage_global_rr_eligible", "=", True),
            ])
        else:
            return self.env["crm.team"]
        queues = self.env["brokerage.crm.round.robin"].sudo().search([
            ("active", "=", True), ("team_id", "in", teams.ids),
        ])
        by_team = {queue.team_id.id: queue for queue in queues}
        return teams.filtered(
            lambda team: team.id in by_team and bool(by_team[team.id]._get_campaign_eligible_users())
        ).sorted(key=lambda team: (by_team[team.id].sequence, team.id))

    def _state_for_team(self, team):
        self.ensure_one()
        state = self.env["brokerage.meta.campaign.team.state"].sudo().search([
            ("policy_id", "=", self.id), ("team_id", "=", team.id),
        ], limit=1)
        return state or self.env["brokerage.meta.campaign.team.state"].sudo().create({
            "policy_id": self.id, "team_id": team.id,
        })

    def _lock(self):
        self.ensure_one()
        self.env.cr.execute("SELECT id FROM brokerage_meta_campaign_rule WHERE id=%s FOR UPDATE", [self.id])
        self.invalidate_recordset()

    @api.model
    def _after(self, records, current):
        ids = records.ids
        if current and current.id in ids:
            index = ids.index(current.id) + 1
            return records.browse(ids[index:] + ids[:index])
        return records

    @api.model
    def _from_cursor(self, records, cursor):
        ids = records.ids
        if cursor and cursor.id in ids:
            index = ids.index(cursor.id)
            return records.browse(ids[index:] + ids[:index])
        return records

    def _select_user(self, teams, lead, purpose):
        attempted = lead.campaign_routing_attempted_user_ids
        for team in teams:
            queue = self.env["brokerage.crm.round.robin"].sudo().search([
                ("team_id", "=", team.id), ("active", "=", True),
            ], limit=1)
            all_users = queue._get_campaign_eligible_users()
            available = all_users.filtered(lambda user: user not in attempted)
            if not available:
                continue
            state = self._state_for_team(team)
            field_name = {
                "initial": "initial_next_index", "sla": "sla_next_index",
                "not_interested": "not_interested_next_index",
            }[purpose]
            # Cursor applies to the full configured queue, then skips attempted users.
            start = state[field_name] % len(all_users)
            ordered = all_users.browse(all_users.ids[start:] + all_users.ids[:start])
            user = ordered.filtered(lambda candidate: candidate in available)[:1]
            return team, user, all_users.ids.index(user.id)
        return self.env["crm.team"], self.env["res.users"], 0

    def _assign(self, lead, team, user, position, purpose, reason):
        previous_user, previous_team = lead.user_id, lead.team_id
        before, now = lead._brokerage_assignment_snapshot(), fields.Datetime.now()
        stage = lead._find_brokerage_stage("assigned", team=team)
        if not stage:
            raise ValidationError(_("Configure an Assigned CRM stage for Sales Team %s.") % team.display_name)
        queue = self.env["brokerage.crm.round.robin"].sudo().search([
            ("team_id", "=", team.id), ("active", "=", True),
        ], limit=1)
        state = self._state_for_team(team)
        cursor = {"initial": "initial_next_index", "sla": "sla_next_index", "not_interested": "not_interested_next_index"}[purpose]
        count = {"initial": "initial_assignment_count", "sla": "sla_assignment_count", "not_interested": "not_interested_assignment_count"}[purpose]
        state.write({
            cursor: (position + 1) % len(queue._get_campaign_eligible_users()),
            count: state[count] + 1, "last_user_id": user.id,
            "last_assignment_datetime": now,
        })
        cycle_type = "round_robin" if purpose == "initial" else (
            "not_interested_reassignment" if purpose == "not_interested" else "reassignment"
        )
        values = {
            "team_id": team.id, "user_id": user.id,
            "campaign_routing_policy_id": self.id,
            "campaign_routing_attempted_user_ids": [(4, user.id)],
            "campaign_routing_exhausted": False,
        }
        values.update(lead._prepare_brokerage_assignment_cycle_values(cycle_type, now))
        if purpose == "not_interested":
            values["not_interested_reassignment_done"] = True
        lead._clear_open_brokerage_sla_activities()
        context = dict(skip_assignment_history=True, skip_round_robin=True, brokerage_workflow_action=True)
        lead.with_context(**context).write(values)
        lead.with_context(**context).write({"stage_id": stage.id})
        policy_count = {"initial": "assignment_count", "sla": "reassignment_count", "not_interested": "not_interested_count"}[purpose]
        self.write({
            policy_count: self[policy_count] + 1, "last_team_id": team.id,
            "last_user_id": user.id, "last_assignment_datetime": now,
        })
        self.env["brokerage.crm.assignment.history"].sudo().create({
            "lead_id": lead.id, "source_id": lead.source_id.id or False,
            "previous_user_id": previous_user.id or False, "new_user_id": user.id,
            "previous_team_id": previous_team.id or False, "new_team_id": team.id,
            "assignment_type": cycle_type, "assigned_datetime": now,
            "assigned_by_id": self.env.user.id, "reason": reason,
            "round_robin_id": queue.id or False, "round_robin_position": position,
            "previous_stage_id": before.get("stage_id") or False,
            "new_stage_id": lead.stage_id.id or False,
            "before_snapshot": before, "after_snapshot": lead._brokerage_assignment_snapshot(),
        })
        lead.message_post(
            body=Markup(self.env._("Campaign <b>%(campaign)s</b> assigned the opportunity to <b>%(user)s</b> in <b>%(team)s</b> (%(reason)s).")) % {
                "campaign": self.display_name, "user": user.display_name,
                "team": team.display_name, "reason": reason,
            }, subtype_xmlid="mail.mt_note",
        )
        lead._queue_brokerage_whatsapp_assignment(user, reason)
        return user

    def assign_initial(self, lead, reason=None):
        self.ensure_one()
        if self.routing_mode == "manual":
            return self.env["res.users"]
        self._lock()
        teams = self._ordered_teams()
        team, user, position = self._select_user(self._from_cursor(teams, self.next_team_id), lead, "initial")
        if not user:
            raise ValidationError(_("Campaign %s has no eligible salesperson in its permitted teams.") % self.display_name)
        ids = teams.ids
        self.next_team_id = teams[(ids.index(team.id) + 1) % len(teams)]
        return self._assign(lead, team, user, position, "initial", reason or _("Campaign assignment"))

    def _try_reassignment(self, lead, purpose, reason):
        self.ensure_one()
        self._lock()
        primary = self._ordered_teams()
        teams = self._after(primary, lead.team_id)
        if lead.team_id in primary:
            teams = lead.team_id | teams  # exhaust current team before next team
        team, user, position = self._select_user(teams, lead, purpose)
        if not user and self.fallback_mode in ("selected_teams", "global"):
            lead.sudo().with_context(skip_round_robin=True).write({"campaign_routing_phase": "fallback"})
            fallback = self._ordered_teams(fallback=True)
            team, user, position = self._select_user(self._from_cursor(fallback, self.fallback_next_team_id), lead, purpose)
            if user:
                ids = fallback.ids
                self.fallback_next_team_id = fallback[(ids.index(team.id) + 1) % len(fallback)]
        if user:
            return self._assign(lead, team, user, position, purpose, reason)
        self._finish_exhausted(lead)
        return self.env["res.users"]

    def reassign_after_sla(self, lead, reason=None):
        return self._try_reassignment(lead, "sla", reason or _("Campaign SLA reassignment"))

    def reassign_not_interested_once(self, lead, reason=None):
        self.env.cr.execute("SELECT id FROM crm_lead WHERE id=%s FOR UPDATE", [lead.id])
        lead.invalidate_recordset(["not_interested_reassignment_done"])
        if lead.not_interested_reassignment_done:
            return self.env["res.users"]
        lead.sudo().with_context(skip_round_robin=True).write({
            "not_interested_reassignment_done": True,
        })
        return self._try_reassignment(lead, "not_interested", reason or _("One-time campaign Not Interested reassignment"))

    def _finish_exhausted(self, lead):
        lead.sudo().with_context(skip_round_robin=True).write({
            "campaign_routing_exhausted": True, "sla_cycle_active": False,
        })
        if self.fallback_mode == "manager_review":
            activity_type = self.env.ref("brokerage_crm.mail_activity_type_manager_review", raise_if_not_found=False)
            target = lead.team_id.user_id or self.env.user
            if activity_type and target:
                lead.activity_schedule(
                    activity_type_id=activity_type.id, user_id=target.id,
                    summary=_("Campaign routing exhausted"),
                    note=_("Every eligible salesperson configured for campaign %s has been tried.") % self.display_name,
                )
        lead.message_post(
            body=_("Campaign routing stopped because every permitted salesperson has been tried."),
            subtype_xmlid="mail.mt_note",
        )

    def action_reset_rotation(self):
        self.ensure_one()
        self.team_state_ids.sudo().unlink()
        self.write({
            "next_team_id": False, "fallback_next_team_id": False,
            "assignment_count": 0, "reassignment_count": 0,
            "not_interested_count": 0, "last_team_id": False,
            "last_user_id": False, "last_assignment_datetime": False,
        })
        return True


class BrokerageCampaignTeamState(models.Model):
    _name = "brokerage.meta.campaign.team.state"
    _description = "Campaign Team Rotation State"
    _order = "policy_id, team_id"

    policy_id = fields.Many2one("brokerage.meta.campaign.rule", required=True, ondelete="cascade", index=True)
    team_id = fields.Many2one("crm.team", required=True, ondelete="cascade", index=True)
    initial_next_index = fields.Integer(default=0, readonly=True)
    sla_next_index = fields.Integer(default=0, readonly=True)
    not_interested_next_index = fields.Integer(default=0, readonly=True)
    initial_assignment_count = fields.Integer(default=0, readonly=True)
    sla_assignment_count = fields.Integer(default=0, readonly=True)
    not_interested_assignment_count = fields.Integer(default=0, readonly=True)
    last_user_id = fields.Many2one("res.users", readonly=True)
    last_assignment_datetime = fields.Datetime(readonly=True)

    _policy_team_unique = models.Constraint(
        "UNIQUE(policy_id, team_id)", "A campaign can have only one state per team."
    )
