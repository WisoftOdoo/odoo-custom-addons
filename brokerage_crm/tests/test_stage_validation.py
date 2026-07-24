from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestLeadValidation(TransactionCase):
    def test_agent_cannot_drag_lead_backward(self):
        agent = self.env["res.users"].create({
            "name": "Backward Move Agent",
            "login": "backward.move.agent@test.invalid",
            "group_ids": [(6, 0, [
                self.env.ref(
                    "brokerage_crm.group_brokerage_crm_user"
                ).id,
            ])],
        })
        assigned_stage, forecast_stage = self.env["crm.stage"].create([
            {
                "name": "Backward Assigned",
                "sequence": 20,
                "brokerage_code": "assigned",
            },
            {
                "name": "Backward Forecast",
                "sequence": 70,
                "brokerage_code": "forecast",
            },
        ])
        lead = self.env["crm.lead"].create({
            "name": "Backward Move Protected",
            "user_id": agent.id,
            "stage_id": forecast_stage.id,
            "assigned_datetime": fields.Datetime.now()
            - timedelta(hours=2),
        })
        lead.with_context(
            skip_round_robin=True,
            skip_assignment_history=True,
        ).write({
            "assignment_type": "round_robin",
            "sla_cycle_active": False,
        })

        with self.assertRaisesRegex(
            ValidationError,
            "cannot be moved backward",
        ):
            lead.with_user(agent).write({
                "stage_id": assigned_stage.id,
            })

        self.assertEqual(lead.stage_id, forecast_stage)

    def test_manager_stage_correction_does_not_restart_sla(self):
        manager = self.env["res.users"].create({
            "name": "Stage Correction Manager",
            "login": "stage.correction.manager@test.invalid",
            "group_ids": [(6, 0, [
                self.env.ref(
                    "brokerage_crm.group_brokerage_sales_manager"
                ).id,
            ])],
        })
        agent = self.env["res.users"].create({
            "name": "Correction Lead Agent",
            "login": "correction.lead.agent@test.invalid",
        })
        assigned_stage, forecast_stage = self.env["crm.stage"].create([
            {
                "name": "Correction Assigned",
                "sequence": 20,
                "brokerage_code": "assigned",
            },
            {
                "name": "Correction Forecast",
                "sequence": 70,
                "brokerage_code": "forecast",
            },
        ])
        lead = self.env["crm.lead"].create({
            "name": "Audited Stage Correction",
            "user_id": agent.id,
            "stage_id": forecast_stage.id,
            "assigned_datetime": fields.Datetime.now()
            - timedelta(days=1),
        })
        lead.with_context(
            skip_round_robin=True,
            skip_assignment_history=True,
        ).write({
            "assignment_type": "round_robin",
            "sla_cycle_active": False,
        })

        wizard = self.env[
            "brokerage.crm.stage.correction.wizard"
        ].with_user(manager).create({
            "lead_id": lead.id,
            "target_stage_id": assigned_stage.id,
            "reason": "Correcting an accidental pipeline drag.",
        })
        wizard.action_confirm()

        self.assertEqual(lead.stage_id, assigned_stage)
        self.assertEqual(lead.user_id, agent)
        self.assertFalse(lead.sla_cycle_active)
        self.assertTrue(lead.message_ids.filtered(
            lambda message: "Stage corrected by" in (
                message.body or ""
            )
        ))

    def test_lead_sources_action_opens_list_first(self):
        action = self.env.ref(
            "brokerage_crm.action_utm_source_brokerage"
        )

        self.assertEqual(action.views[0][1], "list")
        self.assertEqual(
            action.views[0][0],
            self.env.ref(
                "brokerage_crm.view_utm_source_brokerage_list"
            ).id,
        )

    def test_agent_can_create_developer_and_project(self):
        agent = self.env["res.users"].create({
            "name": "Master Data Agent",
            "login": "master.data.agent@test.invalid",
            "group_ids": [(6, 0, [
                self.env.ref(
                    "brokerage_crm.group_brokerage_crm_user"
                ).id,
            ])],
        })
        developer = self.env["brokerage.developer"].with_user(agent).create({
            "name": "Agent-created Developer",
        })
        project = self.env["brokerage.project"].with_user(agent).create({
            "name": "Agent-created Project",
            "developer_id": developer.id,
        })
        self.assertEqual(project.developer_id, developer)

    def test_project_must_match_developer(self):
        developer_a = self.env["brokerage.developer"].create({"name": "A"})
        developer_b = self.env["brokerage.developer"].create({"name": "B"})
        project = self.env["brokerage.project"].create({"name": "A Project", "developer_id": developer_a.id})
        with self.assertRaises(ValidationError):
            self.env["crm.lead"].create({
                "name": "Lead", "preferred_developer_id": developer_b.id,
                "preferred_project_id": project.id,
            })

    def test_contact_stage_requires_attempt_log(self):
        stage = self.env["crm.stage"].create({
            "name": "Contact Attempted Test",
            "brokerage_code": "contact_attempted",
        })
        lead = self.env["crm.lead"].create({"name": "Lead"})
        with self.assertRaises(ValidationError):
            lead.write({"stage_id": stage.id})

    def test_reassignment_requires_current_salesperson_evidence(self):
        agent_group = self.env.ref(
            "brokerage_crm.group_brokerage_crm_user"
        )
        old_agent, new_agent = self.env["res.users"].create([
            {
                "name": "Previous Cycle Agent",
                "login": "previous.cycle.agent@test.invalid",
                "group_ids": [(6, 0, [agent_group.id])],
            },
            {
                "name": "Current Cycle Agent",
                "login": "current.cycle.agent@test.invalid",
                "group_ids": [(6, 0, [agent_group.id])],
            },
        ])
        stages = self.env["crm.stage"].create([
            {"name": "Cycle Assigned", "brokerage_code": "assigned"},
            {"name": "Cycle Contacted", "brokerage_code": "contacted"},
            {
                "name": "Cycle Meeting Scheduled",
                "brokerage_code": "meeting_scheduled",
            },
            {
                "name": "Cycle Meeting Completed",
                "brokerage_code": "meeting_completed",
            },
        ])
        successful_status = self.env[
            "brokerage.crm.lead.status"
        ].create({
            "name": "Successful Cycle Contact",
            "code": "successful_cycle_contact",
            "is_contact_attempt": True,
            "is_successful_contact": True,
        })
        developer = self.env["brokerage.developer"].create({
            "name": "Cycle Developer",
        })
        project = self.env["brokerage.project"].create({
            "name": "Cycle Project",
            "developer_id": developer.id,
        })
        lead = self.env["crm.lead"].create({
            "name": "Reassigned Validation Cycle",
            "user_id": old_agent.id,
            "stage_id": stages[0].id,
        })
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
        ).write({"assignment_type": "round_robin"})
        old_attempt_time = fields.Datetime.now() - timedelta(minutes=10)
        self.env["brokerage.crm.contact.attempt"].create({
            "lead_id": lead.id,
            "user_id": old_agent.id,
            "attempt_datetime": old_attempt_time,
            "method": "call",
            "status_id": successful_status.id,
        })
        old_meeting = self.env[
            "brokerage.crm.meeting"
        ].with_user(old_agent).create({
            "lead_id": lead.id,
            "name": "Previous Agent Meeting",
            "state": "completed",
            "meeting_type": "phone",
            "scheduled_start": old_attempt_time,
            "scheduled_end": old_attempt_time + timedelta(minutes=30),
            "actual_start": old_attempt_time,
            "actual_end": old_attempt_time + timedelta(minutes=20),
            "outcome": "interested",
            "developer_id": developer.id,
            "project_id": project.id,
            "agent_remarks": "Previous agent meeting",
            "next_action": "Previous follow-up",
            "next_follow_up_date": fields.Date.today(),
        })
        reassigned_at = fields.Datetime.now()
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({
            "user_id": new_agent.id,
            "assignment_type": "reassignment",
            "assigned_datetime": reassigned_at,
            "sla_cycle_active": True,
            "first_contact_datetime": False,
            "stage_id": stages[0].id,
        })

        current_lead = lead.with_user(new_agent)
        with self.assertRaises(ValidationError):
            current_lead.write({"stage_id": stages[1].id})
        current_attempt = self.env[
            "brokerage.crm.contact.attempt"
        ].with_user(
            new_agent
        ).create({
            "lead_id": lead.id,
            "user_id": new_agent.id,
            "method": "call",
            "status_id": successful_status.id,
        })
        self.assertTrue(current_attempt.successful_contact)
        self.assertIn(
            current_attempt,
            current_lead._current_assignment_contact_attempts(),
        )
        current_lead.write({"stage_id": stages[1].id})

        with self.assertRaises(ValidationError):
            current_lead.write({"stage_id": stages[2].id})
        new_meeting = self.env[
            "brokerage.crm.meeting"
        ].with_user(new_agent).create({
            "lead_id": lead.id,
            "name": "Current Agent Meeting",
            "state": "scheduled",
            "meeting_type": "phone",
            "scheduled_start": fields.Datetime.now()
            + timedelta(hours=1),
            "scheduled_end": fields.Datetime.now()
            + timedelta(hours=2),
        })
        current_lead.write({"stage_id": stages[2].id})

        with self.assertRaises(ValidationError):
            current_lead.write({"stage_id": stages[3].id})
        completion_start = fields.Datetime.now()
        new_meeting.with_user(new_agent).write({
            "state": "completed",
            "actual_start": completion_start,
            "actual_end": completion_start + timedelta(minutes=20),
            "outcome": "interested",
            "developer_id": developer.id,
            "project_id": project.id,
            "agent_remarks": "Current agent meeting",
            "next_action": "Current follow-up",
            "next_follow_up_date": fields.Date.today(),
        })
        current_lead.write({"stage_id": stages[3].id})
        self.assertNotEqual(new_meeting.id, old_meeting.id)
