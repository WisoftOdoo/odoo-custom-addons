from odoo.tests.common import TransactionCase


class TestRoundRobin(TransactionCase):
    def test_normal_team_rotation_uses_sequence_not_assignment_count(self):
        self.env["brokerage.crm.round.robin"].search([]).write({
            "active": False,
        })
        company = self.env.company
        company.brokerage_normal_rr_next_rule_id = False
        users = self.env["res.users"].create([
            {"name": "Sequence A", "login": "team.sequence.a@test.invalid"},
            {"name": "Sequence B", "login": "team.sequence.b@test.invalid"},
            {"name": "Sequence C", "login": "team.sequence.c@test.invalid"},
        ])
        teams = self.env["crm.team"].create([
            {"name": "Sequence Team A", "sequence": 30},
            {"name": "Sequence Team B", "sequence": 10},
            {"name": "Sequence Team C", "sequence": 20},
        ])
        rules = self.env["brokerage.crm.round.robin"].create([
            {
                "name": "Sequence Rule A",
                "sequence": 30,
                "team_id": teams[0].id,
                "member_ids": [(6, 0, [users[0].id])],
                "assignment_count": 0,
            },
            {
                "name": "Sequence Rule B",
                "sequence": 10,
                "team_id": teams[1].id,
                "member_ids": [(6, 0, [users[1].id])],
                "assignment_count": 100,
            },
            {
                "name": "Sequence Rule C",
                "sequence": 20,
                "team_id": teams[2].id,
                "member_ids": [(6, 0, [users[2].id])],
                "assignment_count": 50,
            },
        ])
        self.env["crm.stage"].create({
            "name": "Assigned Sequence Stage",
            "brokerage_code": "assigned",
            "team_ids": [(6, 0, teams.ids)],
        })

        leads = self.env["crm.lead"].create([
            {
                "name": f"Sequence Lead {number}",
                "assignment_type": "round_robin",
            }
            for number in range(1, 5)
        ])

        self.assertEqual(
            [lead.team_id.id for lead in leads],
            [teams[1].id, teams[2].id, teams[0].id, teams[1].id],
        )
        self.assertEqual(
            [lead.user_id.id for lead in leads],
            [users[1].id, users[2].id, users[0].id, users[1].id],
        )
        self.assertEqual(
            company.brokerage_normal_rr_next_rule_id,
            rules[2],
        )
        self.assertEqual(rules.mapped("assignment_count"), [1, 102, 51])

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
            {"name": "Lead 1", "team_id": team.id, "user_id": False},
            {"name": "Lead 2", "team_id": team.id, "user_id": False},
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

        history = leads[0].assignment_history_ids
        app_notifications = self.env["mail.message"].sudo().search([
            ("model", "=", "crm.lead"),
            ("res_id", "=", leads[0].id),
            ("message_type", "=", "user_notification"),
            ("partner_ids", "in", users[1].partner_id.id),
            ("subject", "=", "New CRM Lead Assigned: Lead 1"),
        ])
        self.assertEqual(len(app_notifications), 1)
        self.assertEqual(
            history.odoo_notification_message_id,
            app_notifications,
        )

        # Re-entering the delivery helper must not generate a second app
        # notification for the same assignment audit event.
        history._notify_new_assignee_in_odoo_once()
        self.assertEqual(
            self.env["mail.message"].sudo().search_count([
                ("model", "=", "crm.lead"),
                ("res_id", "=", leads[0].id),
                ("message_type", "=", "user_notification"),
                ("partner_ids", "in", users[1].partner_id.id),
                ("subject", "=", "New CRM Lead Assigned: Lead 1"),
            ]),
            1,
        )

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

    def test_eligible_people_and_leader_get_native_team_membership(self):
        leader, agent = self.env["res.users"].create([
            {
                "name": "Membership Team Leader",
                "login": "membership.leader@test.invalid",
            },
            {
                "name": "Membership Agent",
                "login": "membership.agent@test.invalid",
            },
        ])
        team = self.env["crm.team"].create({
            "name": "Membership Synchronization Team",
            "user_id": leader.id,
        })
        self.env["brokerage.crm.round.robin"].create({
            "name": "Membership Synchronization Queue",
            "team_id": team.id,
            "member_ids": [(6, 0, [agent.id, leader.id])],
        })

        self.assertEqual(
            set(team.crm_team_member_ids.mapped("user_id").ids),
            {leader.id, agent.id},
        )
        self.assertTrue(all(team.crm_team_member_ids.mapped("active")))
