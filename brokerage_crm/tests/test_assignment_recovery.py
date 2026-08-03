from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestAssignmentRecovery(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["brokerage.crm.round.robin"].search([]).write({
            "active": False,
        })
        cls.env["ir.config_parameter"].sudo().set_param(
            "brokerage_crm.ultramsg_enabled", "False"
        )

        manager_group = cls.env.ref(
            "brokerage_crm.group_brokerage_sales_manager"
        )
        cls.manager = cls.env["res.users"].create({
            "name": "Recovery Manager",
            "login": "recovery.manager@test.invalid",
            "group_ids": [(6, 0, [manager_group.id])],
        })
        cls.agent_a, cls.agent_b = cls.env["res.users"].create([
            {
                "name": "Recovery Agent A",
                "login": "recovery.agent.a@test.invalid",
            },
            {
                "name": "Recovery Agent B",
                "login": "recovery.agent.b@test.invalid",
            },
        ])
        cls.team_a, cls.team_b = cls.env["crm.team"].create([
            {"name": "Recovery Team A", "user_id": cls.manager.id},
            {"name": "Recovery Team B", "user_id": cls.manager.id},
        ])
        cls.assigned_stage = cls.env["crm.stage"].create({
            "name": "Assigned Recovery",
            "sequence": 20,
            "brokerage_code": "assigned",
            "team_ids": [(6, 0, [cls.team_a.id, cls.team_b.id])],
        })
        cls.forecast_stage = cls.env["crm.stage"].create({
            "name": "Forecast Recovery",
            "sequence": 80,
            "brokerage_code": "forecast",
            "team_ids": [(6, 0, [cls.team_a.id, cls.team_b.id])],
        })
        cls.rule_a, cls.rule_b = cls.env[
            "brokerage.crm.round.robin"
        ].create([
            {
                "name": "Recovery Queue A",
                "team_id": cls.team_a.id,
                "member_ids": [(6, 0, [cls.agent_a.id])],
            },
            {
                "name": "Recovery Queue B",
                "team_id": cls.team_b.id,
                "member_ids": [(6, 0, [cls.agent_b.id])],
            },
        ])
        cls.developer = cls.env["brokerage.developer"].create({
            "name": "Recovery Developer",
        })
        cls.project = cls.env["brokerage.project"].create({
            "name": "Recovery Project",
            "developer_id": cls.developer.id,
        })
        cls.forecast_status = cls.env[
            "brokerage.crm.lead.status"
        ].create({
            "name": "Recovery Forecast Status",
            "code": "recovery_forecast_status",
        })

    def test_latest_cross_team_assignment_can_restore_full_snapshot(self):
        original_assignment = (
            fields.Datetime.now() - timedelta(hours=2)
        )
        lead = self.env["crm.lead"].with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).create({
            "name": "Recover Reassigned Lead",
            "type": "opportunity",
            "team_id": self.team_a.id,
            "user_id": self.agent_a.id,
            "stage_id": self.forecast_stage.id,
            "lead_status_id": self.forecast_status.id,
            "forecast_remarks": "Original forecast evidence",
            "final_developer_id": self.developer.id,
            "final_project_id": self.project.id,
            "final_unit_type": "2BR",
            "estimated_property_value": 1850000,
            "expected_booking_date": fields.Date.today(),
        })
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({
            "stage_id": self.forecast_stage.id,
            "assignment_type": "round_robin",
            "assigned_datetime": original_assignment,
            "sla_cycle_active": False,
        })

        self.env[
            "brokerage.crm.round.robin"
        ].assign_lead_cross_team(
            lead,
            preferred_team=self.team_b,
            reason="Test SLA handoff",
        )
        lead.invalidate_recordset()
        history = lead.assignment_history_ids.sorted(
            key=lambda record: (record.assigned_datetime, record.id),
            reverse=True,
        )[:1]
        queue_count_after_reassignment = (
            self.rule_b.cross_team_assignment_count
        )

        self.assertEqual(lead.user_id, self.agent_b)
        self.assertEqual(lead.stage_id, self.assigned_stage)
        self.assertFalse(lead.forecast_remarks)
        self.assertTrue(history.before_snapshot)
        self.assertEqual(history.previous_stage_id, self.forecast_stage)
        self.assertEqual(history.new_stage_id, self.assigned_stage)

        history.with_user(self.manager).action_recover_assignment(
            "The automatic handoff was raised in error."
        )
        lead.invalidate_recordset()
        history.invalidate_recordset()
        self.rule_b.invalidate_recordset()

        self.assertEqual(lead.user_id, self.agent_a)
        self.assertEqual(lead.team_id, self.team_a)
        self.assertEqual(lead.stage_id, self.forecast_stage)
        self.assertEqual(lead.assignment_type, "round_robin")
        self.assertEqual(lead.assigned_datetime, original_assignment)
        self.assertFalse(lead.sla_cycle_active)
        self.assertEqual(lead.lead_status_id, self.forecast_status)
        self.assertEqual(
            lead.forecast_remarks, "Original forecast evidence"
        )
        self.assertEqual(lead.final_developer_id, self.developer)
        self.assertEqual(lead.final_project_id, self.project)
        self.assertEqual(lead.final_unit_type, "2BR")
        self.assertEqual(lead.estimated_property_value, 1850000)
        self.assertTrue(history.is_recovered)
        self.assertEqual(
            self.rule_b.cross_team_assignment_count,
            queue_count_after_reassignment,
        )
        recovery_entry = lead.assignment_history_ids.filtered(
            lambda record: record.assignment_type == "recovery"
        )
        self.assertEqual(len(recovery_entry), 1)
        self.assertEqual(history.recovery_history_id, recovery_entry)
