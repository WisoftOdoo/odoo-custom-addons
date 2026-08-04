from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestBrokerageHierarchy(TransactionCase):
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
        cls.always_open_calendar = cls.env[
            "resource.calendar"
        ].create({
            "name": "Hierarchy 24/7",
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

        leader_group = cls.env.ref(
            "brokerage_crm.group_brokerage_team_leader"
        )
        agent_group = cls.env.ref(
            "brokerage_crm.group_brokerage_crm_user"
        )
        cls.team_leader = cls.env["res.users"].create({
            "name": "Hierarchy Team Leader",
            "login": "hierarchy.leader@test.invalid",
            "group_ids": [(6, 0, [leader_group.id])],
        })
        cls.agent = cls.env["res.users"].create({
            "name": "Hierarchy Agent",
            "login": "hierarchy.agent@test.invalid",
            "group_ids": [(6, 0, [agent_group.id])],
        })
        cls.target_agent = cls.env["res.users"].create({
            "name": "Hierarchy Target Agent",
            "login": "hierarchy.target.agent@test.invalid",
            "group_ids": [(6, 0, [agent_group.id])],
        })
        cls.team = cls.env["crm.team"].create({
            "name": "Hierarchy Team",
            "user_id": cls.team_leader.id,
            "member_ids": [(6, 0, [cls.agent.id])],
            "brokerage_working_calendar_id": (
                cls.always_open_calendar.id
            ),
        })
        cls.target_team = cls.env["crm.team"].create({
            "name": "Hierarchy Target Team",
            "member_ids": [(6, 0, [cls.target_agent.id])],
            "brokerage_working_calendar_id": (
                cls.always_open_calendar.id
            ),
        })
        cls.leader_queue = cls.env[
            "brokerage.crm.round.robin"
        ].create({
            "name": "Team-Leader-Only Queue",
            "team_id": cls.team.id,
            "member_ids": [(6, 0, [cls.team_leader.id])],
        })
        cls.target_queue = cls.env[
            "brokerage.crm.round.robin"
        ].create({
            "name": "Hierarchy Target Queue",
            "team_id": cls.target_team.id,
            "member_ids": [(6, 0, [cls.target_agent.id])],
        })
        cls.assigned_stage = cls.env["crm.stage"].create({
            "name": "Assigned Hierarchy",
            "brokerage_code": "assigned",
            "team_ids": [(6, 0, [
                cls.team.id,
                cls.target_team.id,
            ])],
        })
        cls.rule = cls.env["brokerage.crm.sla.rule"].create({
            "name": "Hierarchy SLA",
            "rule_type": "first_contact",
            "team_id": cls.team.id,
            "duration_minutes": 5,
            "reminder_1_minutes": 0,
            "reminder_2_minutes": 0,
            "reminder_3_minutes": 0,
            "escalation_minutes": 1,
            "reassignment_minutes": 10,
            "activity_type_id": cls.env.ref(
                "brokerage_crm.mail_activity_type_call_customer"
            ).id,
        })

    def _assigned_lead(self, elapsed_minutes, user=None):
        user = user or self.agent
        lead = self.env["crm.lead"].create({
            "name": "Hierarchy SLA Lead",
            "type": "opportunity",
            "team_id": self.team.id,
            "user_id": user.id,
            "stage_id": self.assigned_stage.id,
        })
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({
            "stage_id": self.assigned_stage.id,
            "assignment_type": "round_robin",
            "assigned_datetime": (
                fields.Datetime.now()
                - timedelta(minutes=elapsed_minutes)
            ),
            "sla_cycle_active": True,
        })
        return lead

    def test_agent_escalates_to_team_leader_only(self):
        lead = self._assigned_lead(2)

        self.env["crm.lead"]._cron_check_brokerage_sla()

        escalation = self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
            ("rule_id", "=", self.rule.id),
            ("event_type", "=", "team_leader_escalation"),
        ])
        self.assertEqual(escalation.target_user_id, self.team_leader)
        self.assertFalse(self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
            ("event_type", "=", "manager_escalation"),
        ]))
        activity = self.env["mail.activity"].search([
            ("res_model", "=", "crm.lead"),
            ("res_id", "=", lead.id),
            ("summary", "ilike", "Team Leader Escalation"),
        ])
        self.assertEqual(activity.user_id, self.team_leader)

    def test_team_leader_can_be_the_only_eligible_salesperson(self):
        self.assertEqual(
            self.leader_queue._get_eligible_users(),
            self.team_leader,
        )
        selected_user, index, total_users = (
            self.leader_queue.get_next_user()
        )
        self.assertEqual(selected_user, self.team_leader)
        self.assertEqual(index, 0)
        self.assertEqual(total_users, 1)

    def test_team_leader_owner_skips_escalation_and_reassigns(self):
        self.rule.write({
            "reminder_1_minutes": 1,
            "reminder_2_minutes": 2,
            "reminder_3_minutes": 3,
            "escalation_minutes": 4,
            "reassignment_minutes": 10,
        })
        lead = self._assigned_lead(5, user=self.team_leader)
        assignment_datetime = lead.assigned_datetime

        self.env["crm.lead"]._cron_check_brokerage_sla()

        lead.invalidate_recordset()
        self.assertEqual(lead.team_id, self.target_team)
        self.assertEqual(lead.user_id, self.target_agent)
        reminder_logs = self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
            ("rule_id", "=", self.rule.id),
            ("event_type", "in", [
                "reminder_1",
                "reminder_2",
                "reminder_3",
            ]),
            ("assignment_datetime", "=", assignment_datetime),
        ])
        self.assertEqual(
            set(reminder_logs.mapped("event_type")),
            {"reminder_1", "reminder_2", "reminder_3"},
        )
        self.assertFalse(self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
            ("rule_id", "=", self.rule.id),
            ("event_type", "=", "team_leader_escalation"),
            ("assignment_datetime", "=", assignment_datetime),
        ]))
        reassignment = self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
            ("rule_id", "=", self.rule.id),
            ("event_type", "=", "reassignment"),
            ("assignment_datetime", "=", assignment_datetime),
        ])
        self.assertEqual(len(reassignment), 1)

    def test_sla_exhausts_current_team_before_cross_team(self):
        self.leader_queue.member_ids = (
            self.team_leader | self.agent
        )
        for line in self.leader_queue.agent_sequence_ids:
            line.sequence = (
                10 if line.user_id == self.team_leader else 20
            )
        self.rule.write({
            "reminder_1_minutes": 1,
            "reminder_2_minutes": 2,
            "reminder_3_minutes": 3,
            "escalation_minutes": 4,
            "reassignment_minutes": 10,
        })
        lead = self._assigned_lead(5, user=self.team_leader)
        cross_count = self.target_queue.cross_team_assignment_count

        self.env["crm.lead"]._cron_check_brokerage_sla()

        lead.invalidate_recordset()
        self.target_queue.invalidate_recordset()
        self.assertEqual(lead.team_id, self.team)
        self.assertEqual(lead.user_id, self.agent)
        self.assertTrue(lead.sla_cycle_active)
        self.assertEqual(
            self.target_queue.cross_team_assignment_count,
            cross_count,
        )

        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({
            "assigned_datetime": (
                fields.Datetime.now() - timedelta(minutes=11)
            ),
        })
        self.env["crm.lead"]._cron_check_brokerage_sla()

        lead.invalidate_recordset()
        self.target_queue.invalidate_recordset()
        self.assertEqual(lead.team_id, self.target_team)
        self.assertEqual(lead.user_id, self.target_agent)
        self.assertEqual(
            self.target_queue.cross_team_assignment_count,
            cross_count + 1,
        )
        handoffs = lead.assignment_history_ids.filtered(
            lambda history: history.assignment_type == "reassignment"
        ).sorted(key=lambda history: history.assigned_datetime)
        self.assertEqual(handoffs.mapped("new_user_id"), (
            self.agent | self.target_agent
        ))

    def test_team_leader_can_read_team_agent_lead(self):
        lead = self._assigned_lead(0)

        values = lead.with_user(self.team_leader).read(["name"])

        self.assertEqual(values[0]["name"], lead.name)
