from odoo.tests.common import TransactionCase


class TestRoundRobin(TransactionCase):
    def test_assigns_users_in_order(self):
        users = self.env["res.users"].create([
            {"name": "Broker One", "login": "broker.one@test.invalid"},
            {"name": "Broker Two", "login": "broker.two@test.invalid"},
        ])
        team = self.env["crm.team"].create({"name": "Round Robin Team"})
        rule = self.env["brokerage.crm.round.robin"].create({
            "name": "Test", "team_id": team.id,
            "member_ids": [(6, 0, users.ids)],
        })
        sequence_by_user = {
            users[0].id: 20,
            users[1].id: 10,
        }
        for line in rule.agent_sequence_ids:
            line.sequence = sequence_by_user[line.user_id.id]
        self.env["crm.stage"].create({
            "name": "Assigned Team Stage",
            "brokerage_code": "assigned",
            "team_ids": [(6, 0, [team.id])],
        })
        leads = self.env["crm.lead"].create([
            {"name": "Lead 1", "team_id": team.id},
            {"name": "Lead 2", "team_id": team.id},
        ])
        leads[0].write({"assignment_type": "round_robin"})
        leads[1].write({"assignment_type": "round_robin"})
        self.assertEqual(
            leads.mapped("user_id"),
            users.sorted(key=lambda user: sequence_by_user[user.id]),
        )
        self.assertEqual(
            rule.agent_sequence_ids.sorted("sequence").mapped("sequence"),
            [10, 20],
        )
        self.assertEqual(len(leads.assignment_history_ids), 2)
        assignment_message = leads[0].message_ids.filtered(
            lambda message: "assigned through Round Robin" in (
                message.body or ""
            )
        )[:1]
        self.assertIn("<b>", str(assignment_message.body))
        self.assertNotIn("&lt;b&gt;", str(assignment_message.body))

    def test_agent_can_trigger_internal_round_robin_across_teams(self):
        self.env["brokerage.crm.round.robin"].search([]).write({"active": False})
        agent_group = self.env.ref("brokerage_crm.group_brokerage_crm_user")
        integration_user = self.env["res.users"].create({
            "name": "Meta Integration",
            "login": "meta.integration@test.invalid",
            "group_ids": [(6, 0, [agent_group.id])],
        })
        salespeople = self.env["res.users"].create([
            {"name": "Team A Agent", "login": "team.a@test.invalid"},
            {"name": "Team B Agent", "login": "team.b@test.invalid"},
        ])
        teams = self.env["crm.team"].create([
            {"name": "External Team A"}, {"name": "External Team B"},
        ])
        self.env["brokerage.crm.round.robin"].create([
            {
                "name": "External A", "team_id": teams[0].id,
                "member_ids": [(6, 0, [salespeople[0].id])],
            },
            {
                "name": "External B", "team_id": teams[1].id,
                "member_ids": [(6, 0, [salespeople[1].id])],
            },
        ])
        assigned_stage = self.env["crm.stage"].create({
            "name": "Assigned External", "brokerage_code": "assigned",
            "team_ids": [(6, 0, teams.ids)],
        })

        leads = self.env["crm.lead"].with_user(integration_user).create([
            {"name": "Meta Lead 1", "assignment_type": "round_robin"},
            {"name": "Meta Lead 2", "assignment_type": "round_robin"},
        ]).sudo()

        self.assertEqual(set(leads.mapped("team_id").ids), set(teams.ids))
        self.assertEqual(set(leads.mapped("user_id").ids), set(salespeople.ids))
        self.assertEqual(leads.mapped("stage_id.brokerage_code"), ["assigned"])
        self.assertTrue(all(leads.mapped("assigned_datetime")))

    def test_member_changes_synchronize_rotation_lines(self):
        users = self.env["res.users"].create([
            {
                "name": "Sequence Agent One",
                "login": "sequence.one@test.invalid",
            },
            {
                "name": "Sequence Agent Two",
                "login": "sequence.two@test.invalid",
            },
            {
                "name": "Sequence Agent Three",
                "login": "sequence.three@test.invalid",
            },
        ])
        team = self.env["crm.team"].create({
            "name": "Sequence Synchronization Team",
        })
        rule = self.env["brokerage.crm.round.robin"].create({
            "name": "Sequence Synchronization",
            "team_id": team.id,
            "member_ids": [(6, 0, users[:2].ids)],
        })

        self.assertEqual(
            rule.agent_sequence_ids.sorted("sequence").mapped("user_id"),
            users[:2].sorted("id"),
        )
        self.assertEqual(
            rule.agent_sequence_ids.sorted("sequence").mapped("sequence"),
            [10, 20],
        )

        rule.member_ids = users[1:]

        self.assertEqual(
            set(rule.agent_sequence_ids.mapped("user_id").ids),
            set(users[1:].ids),
        )
        self.assertEqual(
            rule.agent_sequence_ids.filtered(
                lambda line: line.user_id == users[1]
            ).sequence,
            20,
        )
        self.assertEqual(
            rule.agent_sequence_ids.filtered(
                lambda line: line.user_id == users[2]
            ).sequence,
            30,
        )
