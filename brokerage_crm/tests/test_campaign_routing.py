from odoo.tests.common import TransactionCase


class TestCampaignRouting(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["brokerage.crm.round.robin"].search([]).write({"active": False})
        cls.users = cls.env["res.users"].create([
            {"name": "Campaign A1", "login": "campaign.a1@test.invalid"},
            {"name": "Campaign A2", "login": "campaign.a2@test.invalid"},
            {"name": "Campaign B1", "login": "campaign.b1@test.invalid"},
            {"name": "Campaign B2", "login": "campaign.b2@test.invalid"},
            {"name": "Campaign C1", "login": "campaign.c1@test.invalid"},
        ])
        cls.teams = cls.env["crm.team"].create([
            {"name": "Campaign Team A", "sequence": 10},
            {"name": "Campaign Team B", "sequence": 20},
            {"name": "Campaign Team C", "sequence": 30},
        ])
        cls.queues = cls.env["brokerage.crm.round.robin"].create([
            {"name": "Campaign Queue A", "team_id": cls.teams[0].id,
             "sequence": 10, "member_ids": [(6, 0, cls.users[:2].ids)]},
            {"name": "Campaign Queue B", "team_id": cls.teams[1].id,
             "sequence": 20, "member_ids": [(6, 0, cls.users[2:4].ids)]},
            {"name": "Campaign Queue C", "team_id": cls.teams[2].id,
             "sequence": 30, "member_ids": [(6, 0, cls.users[4:].ids)]},
        ])
        for queue in cls.queues:
            for index, line in enumerate(queue.agent_sequence_ids.sorted("user_id"), 1):
                line.sequence = index * 10
        cls.new_stage, cls.assigned_stage = cls.env["crm.stage"].create([
            {
                "name": "Campaign New Lead",
                "brokerage_code": "new",
                "sequence": -310,
            },
            {
                "name": "Campaign Assigned",
                "brokerage_code": "assigned",
                "sequence": -300,
                "team_ids": [(6, 0, cls.teams.ids)],
            },
        ])

    def _policy(self, name, mode, teams=False, fallback="manager_review", fallback_teams=False):
        campaign = self.env["utm.campaign"].create({"name": name})
        return self.env["brokerage.meta.campaign.rule"].create({
            "name": name,
            "utm_campaign_id": campaign.id,
            "routing_mode": mode,
            "team_ids": [(6, 0, teams.ids)] if teams else False,
            "fallback_mode": fallback,
            "fallback_team_ids": [(6, 0, fallback_teams.ids)] if fallback_teams else False,
        })

    def _leads(self, policy, count):
        return self.env["crm.lead"].create([
            {
                "name": "%s Lead %s" % (policy.name, number),
                "campaign_id": policy.utm_campaign_id.id,
                "campaign_routing_policy_id": policy.id,
                "assignment_type": "round_robin",
                "user_id": False,
                "team_id": False,
            }
            for number in range(1, count + 1)
        ])

    def test_shared_campaign_rotates_teams_and_users_independently(self):
        policy = self._policy("Shared A B", "shared_teams", self.teams[:2])
        leads = self._leads(policy, 4)
        self.assertEqual(
            [lead.team_id.id for lead in leads],
            [self.teams[0].id, self.teams[1].id, self.teams[0].id, self.teams[1].id],
        )
        self.assertEqual(
            [lead.user_id.id for lead in leads],
            [self.users[0].id, self.users[2].id, self.users[1].id, self.users[3].id],
        )
        self.assertEqual(policy.assignment_count, 4)
        self.assertEqual(self.queues.mapped("assignment_count"), [0, 0, 0])

    def test_dedicated_campaign_never_leaves_selected_team(self):
        policy = self._policy("Dedicated A", "dedicated_team", self.teams[:1])
        leads = self._leads(policy, 3)
        self.assertEqual([lead.team_id.id for lead in leads], [self.teams[0].id] * 3)
        self.assertEqual(
            [lead.user_id.id for lead in leads],
            [self.users[0].id, self.users[1].id, self.users[0].id],
        )

    def test_policies_do_not_share_rotation_positions(self):
        first = self._policy("Independent One", "shared_teams", self.teams[:2])
        second = self._policy("Independent Two", "shared_teams", self.teams[:2])
        first_lead = self._leads(first, 1)
        second_lead = self._leads(second, 1)
        self.assertEqual(first_lead.team_id, self.teams[0])
        self.assertEqual(second_lead.team_id, self.teams[0])
        self.assertEqual(first_lead.user_id, self.users[0])
        self.assertEqual(second_lead.user_id, self.users[0])

    def test_sla_exhausts_current_team_then_next_campaign_team(self):
        policy = self._policy("SLA A B", "shared_teams", self.teams[:2])
        lead = self._leads(policy, 1)
        policy.reassign_after_sla(lead)
        self.assertEqual((lead.team_id, lead.user_id), (self.teams[0], self.users[1]))
        policy.reassign_after_sla(lead)
        self.assertEqual((lead.team_id, lead.user_id), (self.teams[1], self.users[2]))
        self.assertNotIn(lead.user_id, self.users[4:])

    def test_not_interested_reassigns_only_once_inside_campaign(self):
        policy = self._policy("NI A B", "shared_teams", self.teams[:2])
        lead = self._leads(policy, 1)
        first = policy.reassign_not_interested_once(lead)
        self.assertEqual(first, self.users[1])
        self.assertFalse(policy.reassign_not_interested_once(lead))
        self.assertEqual(lead.user_id, self.users[1])

    def test_global_policy_uses_only_opted_in_teams(self):
        self.teams[1].brokerage_global_rr_eligible = True
        policy = self._policy("Global Opt In", "global")
        leads = self._leads(policy, 2)
        self.assertEqual([lead.team_id.id for lead in leads], [self.teams[1].id] * 2)
        self.assertEqual([lead.user_id.id for lead in leads], self.users[2:4].ids)

    def test_selected_fallback_runs_only_after_primary_pool_is_exhausted(self):
        policy = self._policy(
            "Fallback A B to C", "shared_teams", self.teams[:2],
            "selected_teams", self.teams[2:],
        )
        lead = self._leads(policy, 1)
        for expected_user in (self.users[1], self.users[2], self.users[3], self.users[4]):
            policy.reassign_after_sla(lead)
            self.assertEqual(lead.user_id, expected_user)
        self.assertEqual(lead.team_id, self.teams[2])
        self.assertEqual(lead.campaign_routing_phase, "fallback")

    def test_manual_policy_never_assigns_or_starts_sla(self):
        policy = self._policy("Manual Campaign", "manual")
        lead = self._leads(policy, 1)
        self.assertEqual(lead.assignment_type, "manual")
        self.assertFalse(lead.user_id)
        self.assertFalse(lead.team_id)
        self.assertFalse(lead.sla_cycle_active)
        self.assertEqual(lead._stage_code(lead.stage_id), "new")

    def test_exhausted_campaign_stops_sla_and_requests_review(self):
        policy = self._policy("Exhaust C", "dedicated_team", self.teams[2:])
        lead = self._leads(policy, 1)
        self.assertFalse(policy.reassign_after_sla(lead))
        self.assertTrue(lead.campaign_routing_exhausted)
        self.assertFalse(lead.sla_cycle_active)
        self.assertTrue(lead.activity_ids.filtered(lambda activity: activity.summary == "Campaign routing exhausted"))
