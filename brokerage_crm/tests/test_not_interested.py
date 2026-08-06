from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestNotInterestedReassignment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["brokerage.crm.round.robin"].search([]).write({
            "active": False,
        })

        cls.agents = cls.env["res.users"].create([
            {
                "name": "Not Interested Agent A",
                "login": "not.interested.a@test.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref(
                        "brokerage_crm.group_brokerage_crm_user"
                    ).id,
                ])],
            },
            {
                "name": "Not Interested Agent B",
                "login": "not.interested.b@test.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref(
                        "brokerage_crm.group_brokerage_crm_user"
                    ).id,
                ])],
            },
        ])
        cls.teams = cls.env["crm.team"].create([
            {"name": "Not Interested Team A", "user_id": cls.env.user.id},
            {"name": "Not Interested Team B", "user_id": cls.env.user.id},
        ])
        cls.assigned_stage = cls.env["crm.stage"].create({
            "name": "Assigned Not Interested Test",
            "brokerage_code": "assigned",
            "team_ids": [(6, 0, cls.teams.ids)],
        })
        cls.not_interested_stage = cls.env.ref(
            "brokerage_crm.crm_stage_not_interested"
        )
        cls.not_interested_stage.write({
            "team_ids": [(6, 0, cls.teams.ids)],
        })
        cls.configurations = cls.env[
            "brokerage.crm.round.robin"
        ].create([
            {
                "name": "Not Interested Queue A",
                "team_id": cls.teams[0].id,
                "member_ids": [(6, 0, [cls.agents[0].id])],
            },
            {
                "name": "Not Interested Queue B",
                "team_id": cls.teams[1].id,
                "member_ids": [(6, 0, [cls.agents[1].id])],
            },
        ])
        cls.not_interested_status = cls.env.ref(
            "brokerage_crm.lead_status_not_interested"
        )
        cls.assigned_status = cls.env.ref(
            "brokerage_crm.lead_status_assigned"
        )

    def _record_not_interested(self, lead, remarks):
        wizard = self.env[
            "brokerage.crm.contact.attempt.wizard"
        ].with_user(lead.user_id).create({
            "lead_id": lead.id,
            "method": "call",
            "status_id": self.not_interested_status.id,
            "remarks": remarks,
        })
        return wizard.action_confirm()

    def test_not_interested_reassigns_once_with_independent_queue(self):
        lead = self.env["crm.lead"].create({
            "name": "One-time Not Interested Lead",
            "type": "opportunity",
            "team_id": self.teams[0].id,
            "user_id": self.agents[0].id,
            "stage_id": self.assigned_stage.id,
            "lead_status_id": self.assigned_status.id,
        })
        normal_state = [
            (rule.next_index, rule.assignment_count)
            for rule in self.configurations
        ]
        sla_cross_state = [
            (rule.cross_team_next_index, rule.cross_team_assignment_count)
            for rule in self.configurations
        ]

        result = self._record_not_interested(
            lead, "Customer declined the first agent"
        )

        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "crm.lead")
        self.assertEqual(result["target"], "current")
        self.assertEqual(lead.team_id, self.teams[1])
        self.assertEqual(lead.user_id, self.agents[1])
        self.assertEqual(lead.stage_id, self.assigned_stage)
        self.assertEqual(lead.lead_status_id, self.assigned_status)
        self.assertTrue(lead.not_interested_reassignment_done)
        self.assertEqual(
            lead.assignment_type,
            "not_interested_reassignment",
        )
        with self.assertRaises(AccessError):
            self.env["crm.lead"].with_user(
                self.agents[0]
            ).browse(lead.id).read(["name"])
        self.configurations.invalidate_recordset()
        self.assertEqual(
            [
                (rule.next_index, rule.assignment_count)
                for rule in self.configurations
            ],
            normal_state,
        )
        self.assertEqual(
            [
                (
                    rule.cross_team_next_index,
                    rule.cross_team_assignment_count,
                )
                for rule in self.configurations
            ],
            sla_cross_state,
        )
        self.assertEqual(
            self.configurations[1].not_interested_assignment_count,
            1,
        )
        independent_state = [
            (
                rule.not_interested_next_index,
                rule.not_interested_assignment_count,
            )
            for rule in self.configurations
        ]

        self._record_not_interested(
            lead,
            "Customer also declined the second agent",
        )

        self.assertEqual(lead.team_id, self.teams[1])
        self.assertEqual(lead.user_id, self.agents[1])
        self.assertEqual(lead.stage_id, self.not_interested_stage)
        self.assertEqual(lead.lead_status_id, self.not_interested_status)
        self.assertEqual(len(lead.contact_attempt_ids), 2)
        self.configurations.invalidate_recordset()
        self.assertEqual(
            [
                (
                    rule.not_interested_next_index,
                    rule.not_interested_assignment_count,
                )
                for rule in self.configurations
            ],
            independent_state,
        )
        self.assertEqual(
            len(lead.assignment_history_ids.filtered(
                lambda history: history.assignment_type
                == "not_interested_reassignment"
            )),
            1,
        )

    def test_not_interested_prefers_one_same_team_handoff(self):
        second_team_a_agent = self.env["res.users"].create({
            "name": "Not Interested Agent A2",
            "login": "not.interested.a2@test.invalid",
            "group_ids": [(6, 0, [
                self.env.ref(
                    "brokerage_crm.group_brokerage_crm_user"
                ).id,
            ])],
        })
        self.configurations[0].member_ids |= second_team_a_agent
        for line in self.configurations[0].agent_sequence_ids:
            line.sequence = (
                10 if line.user_id == self.agents[0] else 20
            )
        lead = self.env["crm.lead"].create({
            "name": "Same-team Not Interested Lead",
            "type": "opportunity",
            "team_id": self.teams[0].id,
            "user_id": self.agents[0].id,
            "stage_id": self.assigned_stage.id,
            "lead_status_id": self.assigned_status.id,
        })
        normal_state = [
            (rule.next_index, rule.assignment_count)
            for rule in self.configurations
        ]
        cross_state = [
            (rule.cross_team_next_index, rule.cross_team_assignment_count)
            for rule in self.configurations
        ]

        self._record_not_interested(
            lead,
            "Customer declined the first Team A salesperson",
        )

        lead.invalidate_recordset()
        self.configurations.invalidate_recordset()
        self.assertEqual(lead.team_id, self.teams[0])
        self.assertEqual(lead.user_id, second_team_a_agent)
        self.assertTrue(lead.not_interested_reassignment_done)
        self.assertEqual(
            self.configurations[0].not_interested_assignment_count,
            1,
        )
        self.assertEqual(
            [(rule.next_index, rule.assignment_count)
             for rule in self.configurations],
            normal_state,
        )
        self.assertEqual(
            [(rule.cross_team_next_index, rule.cross_team_assignment_count)
             for rule in self.configurations],
            cross_state,
        )

        self._record_not_interested(
            lead,
            "Customer declined the one-time reassigned salesperson",
        )
        lead.invalidate_recordset()
        self.assertEqual(lead.team_id, self.teams[0])
        self.assertEqual(lead.user_id, second_team_a_agent)
        self.assertEqual(lead.stage_id, self.not_interested_stage)

    def test_not_interested_cross_team_follows_hierarchy_not_counts(self):
        self.configurations[0].write({"sequence": 10})
        self.configurations[1].write({
            "sequence": 20,
            "not_interested_assignment_count": 100,
        })
        team_c_agent = self.env["res.users"].create({
            "name": "Not Interested Agent C",
            "login": "not.interested.c@test.invalid",
            "group_ids": [(6, 0, [
                self.env.ref(
                    "brokerage_crm.group_brokerage_crm_user"
                ).id,
            ])],
        })
        team_c = self.env["crm.team"].create({
            "name": "Not Interested Team C",
            "user_id": self.env.user.id,
        })
        self.assigned_stage.team_ids |= team_c
        configuration_c = self.env["brokerage.crm.round.robin"].create({
            "name": "Not Interested Queue C",
            "sequence": 30,
            "team_id": team_c.id,
            "member_ids": [(6, 0, [team_c_agent.id])],
            "not_interested_assignment_count": 0,
        })
        lead = self.env["crm.lead"].create({
            "name": "Not Interested hierarchy beats count",
            "type": "opportunity",
            "team_id": self.teams[0].id,
            "user_id": self.agents[0].id,
            "stage_id": self.assigned_stage.id,
            "lead_status_id": self.assigned_status.id,
        })

        self._record_not_interested(
            lead,
            "Use the next team by hierarchy",
        )

        lead.invalidate_recordset()
        self.configurations.invalidate_recordset()
        configuration_c.invalidate_recordset()
        self.assertEqual(lead.team_id, self.teams[1])
        self.assertEqual(lead.user_id, self.agents[1])
        self.assertEqual(
            self.configurations[1].not_interested_assignment_count,
            101,
        )
        self.assertEqual(
            configuration_c.not_interested_assignment_count,
            0,
        )
