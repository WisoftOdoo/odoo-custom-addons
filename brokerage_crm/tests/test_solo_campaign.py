from datetime import datetime, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestBrokerageSoloCampaign(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["brokerage.crm.sla.rule"].search([]).write({
            "active": False,
        })
        cls.env["brokerage.crm.round.robin"].search([]).write({
            "active": False,
        })
        cls.env["ir.config_parameter"].sudo().set_param(
            "brokerage_crm.ultramsg_enabled", "False"
        )
        leader_group = cls.env.ref(
            "brokerage_crm.group_brokerage_team_leader"
        )
        agent_group = cls.env.ref(
            "brokerage_crm.group_brokerage_crm_user"
        )

        def create_user(name, login, group):
            return cls.env["res.users"].create({
                "name": name,
                "login": login,
                "group_ids": [(6, 0, [group.id])],
            })

        cls.solo_leader = create_user(
            "Solo Leader",
            "solo.leader@test.invalid",
            leader_group,
        )
        cls.leader_only = create_user(
            "Solo Only Leader",
            "solo.only.leader@test.invalid",
            leader_group,
        )
        cls.normal_leaders = cls.env["res.users"].create([
            {
                "name": "Normal Leader A",
                "login": "normal.leader.a@test.invalid",
                "group_ids": [(6, 0, [leader_group.id])],
            },
            {
                "name": "Normal Leader B",
                "login": "normal.leader.b@test.invalid",
                "group_ids": [(6, 0, [leader_group.id])],
            },
        ])
        cls.solo_agents = cls.env["res.users"].create([
            {
                "name": "Solo Agent A",
                "login": "solo.agent.a@test.invalid",
                "group_ids": [(6, 0, [agent_group.id])],
            },
            {
                "name": "Solo Agent B",
                "login": "solo.agent.b@test.invalid",
                "group_ids": [(6, 0, [agent_group.id])],
            },
        ])
        cls.normal_agents = cls.env["res.users"].create([
            {
                "name": "Normal Agent A",
                "login": "normal.agent.a@test.invalid",
                "group_ids": [(6, 0, [agent_group.id])],
            },
            {
                "name": "Normal Agent B",
                "login": "normal.agent.b@test.invalid",
                "group_ids": [(6, 0, [agent_group.id])],
            },
        ])
        cls.always_open = cls.env["resource.calendar"].create({
            "name": "Solo Tests 24/7",
            "tz": "UTC",
            "attendance_ids": [
                (0, 0, {
                    "name": "Open",
                    "dayofweek": str(day),
                    "hour_from": 0,
                    "hour_to": 24,
                })
                for day in range(7)
            ],
        })
        cls.solo_team = cls.env["crm.team"].create({
            "name": "Solo Campaign Team",
            "user_id": cls.solo_leader.id,
            "member_ids": [(6, 0, cls.solo_agents.ids)],
            "brokerage_solo_campaign": True,
            "brokerage_working_calendar_id": cls.always_open.id,
        })
        cls.leader_only_team = cls.env["crm.team"].create({
            "name": "Solo Leader Only Team",
            "user_id": cls.leader_only.id,
            "brokerage_solo_campaign": True,
            "brokerage_working_calendar_id": cls.always_open.id,
        })
        cls.normal_teams = cls.env["crm.team"].create([
            {
                "name": "Normal Campaign Team A",
                "user_id": cls.normal_leaders[0].id,
                "member_ids": [(6, 0, [cls.normal_agents[0].id])],
                "brokerage_working_calendar_id": cls.always_open.id,
            },
            {
                "name": "Normal Campaign Team B",
                "user_id": cls.normal_leaders[1].id,
                "member_ids": [(6, 0, [cls.normal_agents[1].id])],
                "brokerage_working_calendar_id": cls.always_open.id,
            },
        ])
        cls.assigned_stage = cls.env["crm.stage"].create({
            "name": "Assigned Solo Tests",
            "brokerage_code": "assigned",
            "team_ids": [(6, 0, (
                cls.solo_team
                | cls.leader_only_team
                | cls.normal_teams
            ).ids)],
        })
        cls.not_interested_stage = cls.env["crm.stage"].create({
            "name": "Not Interested Solo Tests",
            "brokerage_code": "not_interested",
            "team_ids": [(6, 0, [cls.solo_team.id])],
        })
        cls.normal_queues = cls.env[
            "brokerage.crm.round.robin"
        ].create([
            {
                "name": "Normal Queue A",
                "team_id": cls.normal_teams[0].id,
                "member_ids": [(6, 0, [cls.normal_agents[0].id])],
            },
            {
                "name": "Normal Queue B",
                "team_id": cls.normal_teams[1].id,
                "member_ids": [(6, 0, [cls.normal_agents[1].id])],
            },
        ])
        cls.solo_source = cls.env["utm.source"].create({
            "name": "Dedicated Solo Campaign",
            "brokerage_category": "marketing",
            "sla_applicable": True,
            "default_team_id": cls.solo_team.id,
        })

    def _create_solo_lead(self, name="Solo Test Lead", team=None):
        values = {
            "name": name,
            "type": "opportunity",
            "assignment_type": "round_robin",
        }
        if team:
            values["team_id"] = team.id
        else:
            values["source_id"] = self.solo_source.id
        return self.env["crm.lead"].create(values)

    def test_source_default_team_uses_isolated_solo_rotation(self):
        queue_state = [
            (
                queue.next_index,
                queue.assignment_count,
                queue.cross_team_next_index,
                queue.cross_team_assignment_count,
                queue.not_interested_next_index,
                queue.not_interested_assignment_count,
            )
            for queue in self.normal_queues
        ]

        leads = (
            self._create_solo_lead("Solo Rotation 1")
            | self._create_solo_lead("Solo Rotation 2")
        )

        self.assertEqual(set(leads.mapped("team_id").ids), {
            self.solo_team.id,
        })
        self.assertEqual(
            set(leads.mapped("user_id").ids),
            set(self.solo_agents.ids),
        )
        self.assertEqual(
            set(leads.mapped("assignment_type")),
            {"solo_campaign"},
        )
        self.assertEqual(
            self.solo_team.brokerage_solo_assignment_count,
            2,
        )
        self.normal_queues.invalidate_recordset()
        self.assertEqual([
            (
                queue.next_index,
                queue.assignment_count,
                queue.cross_team_next_index,
                queue.cross_team_assignment_count,
                queue.not_interested_next_index,
                queue.not_interested_assignment_count,
            )
            for queue in self.normal_queues
        ], queue_state)

    def test_solo_internal_assignment_uses_configured_agent_sequence(self):
        queue = self.env["brokerage.crm.round.robin"].create({
            "name": "Solo Sequence Queue",
            "team_id": self.solo_team.id,
            "member_ids": [(6, 0, self.solo_agents.ids)],
        })
        queue.agent_sequence_ids.filtered(
            lambda line: line.user_id == self.solo_agents[1]
        ).sequence = 10
        queue.agent_sequence_ids.filtered(
            lambda line: line.user_id == self.solo_agents[0]
        ).sequence = 20

        first_lead = self._create_solo_lead("Solo Sequence 1")
        second_lead = self._create_solo_lead("Solo Sequence 2")
        third_lead = self._create_solo_lead("Solo Sequence 3")

        self.assertEqual(first_lead.user_id, self.solo_agents[1])
        self.assertEqual(second_lead.user_id, self.solo_agents[0])
        self.assertEqual(third_lead.user_id, self.solo_agents[1])
        self.assertEqual(queue.next_index, 0)
        self.assertEqual(queue.assignment_count, 0)

    def test_solo_sla_reassignment_exhausts_sequence_including_leader(self):
        queue = self.env["brokerage.crm.round.robin"].create({
            "name": "Solo Same-team SLA Queue",
            "team_id": self.solo_team.id,
            "member_ids": [(6, 0, (
                self.solo_agents | self.solo_leader
            ).ids)],
        })
        sequence_by_user = {
            self.solo_agents[0].id: 10,
            self.solo_leader.id: 20,
            self.solo_agents[1].id: 30,
        }
        for line in queue.agent_sequence_ids:
            line.sequence = sequence_by_user[line.user_id.id]
        lead = self._create_solo_lead("Solo Same-team SLA")
        self.assertEqual(lead.user_id, self.solo_agents[0])

        first_reassignment = self.env[
            "crm.team"
        ].assign_brokerage_solo_cross_team(lead)
        self.assertEqual(first_reassignment, self.solo_leader)
        self.assertEqual(lead.team_id, self.solo_team)

        second_reassignment = self.env[
            "crm.team"
        ].assign_brokerage_solo_cross_team(lead)
        self.assertEqual(second_reassignment, self.solo_agents[1])
        self.assertEqual(lead.team_id, self.solo_team)

        final_reassignment = self.env[
            "crm.team"
        ].assign_brokerage_solo_cross_team(lead)
        self.assertIn(final_reassignment, self.normal_agents)
        self.assertIn(lead.team_id, self.normal_teams)

    def test_solo_assignment_alert_targets_only_assigned_user(self):
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param("brokerage_crm.ultramsg_enabled", "True")
        parameters.set_param(
            "brokerage_crm.ultramsg_instance_id", "instance123456"
        )
        parameters.set_param("brokerage_crm.ultramsg_token", "test-token")

        lead = self._create_solo_lead("Solo Assignment Alert")

        notifications = self.env[
            "brokerage.whatsapp.notification"
        ].search([("lead_id", "=", lead.id)])
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications.notification_type, "assignment")
        self.assertEqual(
            notifications.recipient_user_id,
            lead.user_id,
        )
        self.assertNotEqual(
            notifications.recipient_user_id,
            self.solo_leader,
        )

    def test_leader_only_solo_team_assigns_its_team_leader(self):
        lead = self._create_solo_lead(
            "Leader Only Solo Lead",
            team=self.leader_only_team,
        )

        self.assertEqual(lead.user_id, self.leader_only)
        self.assertEqual(lead.assignment_type, "solo_campaign")
        self.assertTrue(lead.sla_cycle_active)

    def test_global_round_robin_never_selects_solo_team(self):
        lead = self.env["crm.lead"].create({
            "name": "Normal Global Lead",
            "type": "opportunity",
            "assignment_type": "round_robin",
        })

        self.assertIn(lead.team_id, self.normal_teams)
        self.assertFalse(lead.team_id.brokerage_solo_campaign)

    def test_solo_sla_exit_uses_sequence_and_keeps_queues_isolated(self):
        lead = self._create_solo_lead("Solo SLA Exit")
        queue_state = [
            (
                queue.next_index,
                queue.assignment_count,
                queue.cross_team_next_index,
                queue.cross_team_assignment_count,
                queue.not_interested_next_index,
                queue.not_interested_assignment_count,
            )
            for queue in self.normal_queues
        ]

        same_team_user = self.env[
            "crm.team"
        ].assign_brokerage_solo_cross_team(lead)
        self.assertTrue(same_team_user)
        self.assertEqual(lead.team_id, self.solo_team)

        assigned_user = self.env[
            "crm.team"
        ].assign_brokerage_solo_cross_team(lead)

        self.assertTrue(assigned_user)
        self.assertIn(lead.team_id, self.normal_teams)
        self.assertIn(lead.user_id, self.normal_agents)
        self.assertEqual(lead.assignment_type, "reassignment")
        self.normal_queues.invalidate_recordset()
        self.assertEqual([
            (
                queue.next_index,
                queue.assignment_count,
                queue.cross_team_next_index,
                queue.cross_team_assignment_count,
                queue.not_interested_next_index,
                queue.not_interested_assignment_count,
            )
            for queue in self.normal_queues
        ], queue_state)
        self.assertEqual(
            sum(
                self.normal_teams.mapped(
                    "brokerage_solo_cross_assignment_count"
                )
            ),
            1,
        )

    def test_solo_sla_exit_ignores_assignment_counts(self):
        first_queue = self.normal_queues[0]
        second_queue = self.normal_queues[1]
        first_queue.sequence = 10
        second_queue.sequence = 20
        self.normal_teams[0].brokerage_solo_cross_assignment_count = 100
        self.normal_teams[1].brokerage_solo_cross_assignment_count = 0
        lead = self._create_solo_lead("Solo Exit Count Independence")

        same_team_user = self.env[
            "crm.team"
        ].assign_brokerage_solo_cross_team(lead)
        self.assertTrue(same_team_user)
        self.assertEqual(lead.team_id, self.solo_team)

        assigned_user = self.env[
            "crm.team"
        ].assign_brokerage_solo_cross_team(lead)

        self.assertEqual(assigned_user, self.normal_agents[0])
        self.assertEqual(lead.team_id, self.normal_teams[0])
        self.assertEqual(
            self.normal_teams[0].brokerage_solo_cross_assignment_count,
            101,
        )
        self.assertEqual(
            self.normal_teams[1].brokerage_solo_cross_assignment_count,
            0,
        )

    def test_solo_sla_exhausts_team_then_uses_solo_exit(self):
        rule = self.env["brokerage.crm.sla.rule"].create({
            "name": "Solo Campaign SLA",
            "rule_type": "first_contact",
            "team_id": self.solo_team.id,
            "duration_minutes": 75,
            "reminder_1_minutes": 0,
            "reminder_2_minutes": 0,
            "reminder_3_minutes": 0,
            "escalation_minutes": 60,
            "reassignment_minutes": 75,
            "activity_type_id": self.env.ref(
                "brokerage_crm.mail_activity_type_call_customer"
            ).id,
        })
        lead = self._create_solo_lead("Solo Full SLA Flow")
        original_user = lead.user_id
        original_assignment = (
            fields.Datetime.now() - timedelta(minutes=76)
        )
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({
            "assigned_datetime": original_assignment,
            "sla_cycle_active": True,
        })
        queue_state = [
            (
                queue.next_index,
                queue.assignment_count,
                queue.cross_team_next_index,
                queue.cross_team_assignment_count,
                queue.not_interested_next_index,
                queue.not_interested_assignment_count,
            )
            for queue in self.normal_queues
        ]

        self.env["crm.lead"]._cron_check_brokerage_sla()

        escalation = self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
            ("rule_id", "=", rule.id),
            ("event_type", "=", "team_leader_escalation"),
            ("assignment_datetime", "=", original_assignment),
        ])
        self.assertEqual(escalation.target_user_id, self.solo_leader)
        self.assertFalse(self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
            ("event_type", "=", "manager_escalation"),
        ]))
        self.assertEqual(lead.team_id, self.solo_team)
        self.assertIn(lead.user_id, self.solo_agents)
        self.assertNotEqual(lead.user_id, original_user)

        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({
            "assigned_datetime": (
                fields.Datetime.now() - timedelta(minutes=76)
            ),
            "sla_cycle_active": True,
        })
        self.env["crm.lead"]._cron_check_brokerage_sla()

        self.assertIn(lead.team_id, self.normal_teams)
        self.assertEqual(lead.assignment_type, "reassignment")
        self.normal_queues.invalidate_recordset()
        self.assertEqual([
            (
                queue.next_index,
                queue.assignment_count,
                queue.cross_team_next_index,
                queue.cross_team_assignment_count,
                queue.not_interested_next_index,
                queue.not_interested_assignment_count,
            )
            for queue in self.normal_queues
        ], queue_state)

    def test_solo_not_interested_does_not_use_not_interested_queue(self):
        lead = self._create_solo_lead("Solo Not Interested")
        original_user = lead.user_id
        not_interested_state = [
            (
                queue.not_interested_next_index,
                queue.not_interested_assignment_count,
            )
            for queue in self.normal_queues
        ]
        status = self.env.ref(
            "brokerage_crm.lead_status_not_interested"
        )
        wizard = self.env[
            "brokerage.crm.contact.attempt.wizard"
        ].create({
            "lead_id": lead.id,
            "method": "call",
            "status_id": status.id,
            "remarks": "Not interested in this solo campaign",
        })

        wizard.action_confirm()

        self.assertEqual(lead.team_id, self.solo_team)
        self.assertEqual(lead.user_id, original_user)
        self.assertEqual(lead.stage_id, self.not_interested_stage)
        self.assertFalse(lead.not_interested_reassignment_done)
        self.normal_queues.invalidate_recordset()
        self.assertEqual([
            (
                queue.not_interested_next_index,
                queue.not_interested_assignment_count,
            )
            for queue in self.normal_queues
        ], not_interested_state)

    def test_sla_minutes_pause_outside_team_working_hours(self):
        working_calendar = self.env["resource.calendar"].create({
            "name": "Dubai 9 to 6",
            "tz": "Asia/Dubai",
            "attendance_ids": [
                (0, 0, {
                    "name": "Working Day",
                    "dayofweek": str(day),
                    "hour_from": 9,
                    "hour_to": 18,
                })
                for day in range(5)
            ],
        })
        self.solo_team.brokerage_working_calendar_id = (
            working_calendar
        )
        lead = self._create_solo_lead("After Hours Solo Lead")
        assignment = datetime(2026, 7, 27, 15, 0, 0)  # 19:00 Dubai
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({
            "assigned_datetime": assignment,
            "sla_cycle_active": True,
        })

        self.assertEqual(
            lead._brokerage_sla_elapsed_minutes(
                datetime(2026, 7, 27, 17, 0, 0)
            ),
            0,
        )
        self.assertEqual(
            lead._brokerage_sla_elapsed_minutes(
                datetime(2026, 7, 28, 5, 30, 0)
            ),
            30,
        )
        self.assertEqual(
            fields.Datetime.to_string(
                lead._brokerage_sla_deadline(15)
            ),
            "2026-07-28 05:15:00",
        )
