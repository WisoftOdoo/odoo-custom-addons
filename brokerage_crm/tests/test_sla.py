from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestSla(TransactionCase):
    def test_cron_creates_sla_log(self):
        activity_type = self.env.ref("brokerage_crm.mail_activity_type_call_customer")
        rule = self.env["brokerage.crm.sla.rule"].create({
            "name": "15 Minutes", "rule_type": "first_contact",
            "duration_minutes": 60, "reminder_1_minutes": 15,
            "reminder_2_minutes": 0, "reminder_3_minutes": 0,
            "escalation_minutes": 15, "reassignment_minutes": 0,
            "activity_type_id": activity_type.id,
        })
        salesperson = self.env["res.users"].create({
            "name": "SLA Salesperson",
            "login": "sla.salesperson@test.invalid",
        })
        team = self.env["crm.team"].create({
            "name": "SLA Team", "user_id": self.env.user.id,
        })
        assigned_stage = self.env["crm.stage"].create({
            "name": "Assigned SLA", "brokerage_code": "assigned",
        })
        lead = self.env["crm.lead"].create({
            "name": "SLA Lead", "team_id": team.id,
            "user_id": salesperson.id, "stage_id": assigned_stage.id,
        })
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
        ).write({
            "assignment_type": "round_robin",
            "assigned_datetime": fields.Datetime.now() - timedelta(minutes=16),
            "sla_cycle_active": True,
        })
        self.env["crm.lead"]._cron_check_brokerage_sla()
        log = self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id), ("rule_id", "=", rule.id),
            ("event_type", "=", "reminder_1"),
        ])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.state, "breached")
        escalation_activity = self.env["mail.activity"].search([
            ("res_model", "=", "crm.lead"),
            ("res_id", "=", lead.id),
            ("summary", "ilike", "SLA Escalation"),
        ])
        self.assertEqual(escalation_activity.user_id, self.env.user)

        contact_attempted_stage = self.env["crm.stage"].create({
            "name": "Contact Attempted SLA",
            "brokerage_code": "contact_attempted",
        })
        lead.with_context(brokerage_workflow_action=True).write({
            "stage_id": contact_attempted_stage.id,
        })
        self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
        ]).unlink()
        self.env["crm.lead"]._cron_check_brokerage_sla()
        self.assertFalse(self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
        ]))

        contacted_stage = self.env["crm.stage"].create({
            "name": "Contacted SLA", "brokerage_code": "contacted",
        })
        lead.with_context(brokerage_workflow_action=True).write({
            "stage_id": contacted_stage.id,
        })
        self.env["crm.lead"]._cron_check_brokerage_sla()
        self.assertFalse(self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
        ]))

    def test_cross_team_reassignment_preserves_normal_queue(self):
        self.env["brokerage.crm.sla.rule"].search([]).write({
            "active": False,
        })
        self.env["brokerage.crm.round.robin"].search([]).write({
            "active": False,
        })

        agents = self.env["res.users"].create([
            {"name": "Original Agent", "login": "original@test.invalid"},
            {"name": "Cross-team Agent", "login": "cross@test.invalid"},
        ])
        teams = self.env["crm.team"].create([
            {"name": "Original Team", "user_id": self.env.user.id},
            {"name": "Cross Team", "user_id": self.env.user.id},
        ])
        assigned_stage = self.env["crm.stage"].create({
            "name": "Assigned Cross-team",
            "brokerage_code": "assigned",
            "team_ids": [(6, 0, teams.ids)],
        })
        configurations = self.env[
            "brokerage.crm.round.robin"
        ].create([
            {
                "name": "Original Queue",
                "team_id": teams[0].id,
                "member_ids": [(6, 0, [agents[0].id])],
            },
            {
                "name": "Cross Queue",
                "team_id": teams[1].id,
                "member_ids": [(6, 0, [agents[1].id])],
            },
        ])
        rule = self.env["brokerage.crm.sla.rule"].create({
            "name": "Cross-team after escalation",
            "rule_type": "first_contact",
            "team_id": teams[0].id,
            "duration_minutes": 60,
            "reminder_1_minutes": 0,
            "reminder_2_minutes": 0,
            "reminder_3_minutes": 0,
            "escalation_minutes": 60,
            "reassignment_minutes": 90,
            "activity_type_id": self.env.ref(
                "brokerage_crm.mail_activity_type_call_customer"
            ).id,
        })
        lead = self.env["crm.lead"].create({
            "name": "Cross-team SLA Lead",
            "type": "opportunity",
            "team_id": teams[0].id,
            "user_id": agents[0].id,
            "stage_id": assigned_stage.id,
        })
        original_assignment = (
            fields.Datetime.now() - timedelta(minutes=91)
        )
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
        ).write({
            "assignment_type": "round_robin",
            "assigned_datetime": original_assignment,
            "sla_cycle_active": True,
        })
        normal_positions = [
            (configuration.next_index, configuration.assignment_count)
            for configuration in configurations
        ]

        self.env["crm.lead"]._cron_check_brokerage_sla()

        self.assertEqual(lead.team_id, teams[1])
        self.assertEqual(lead.user_id, agents[1])
        self.assertEqual(lead.stage_id, assigned_stage)
        self.assertEqual(lead.assignment_type, "reassignment")
        configurations.invalidate_recordset()
        self.assertEqual(
            [
                (configuration.next_index, configuration.assignment_count)
                for configuration in configurations
            ],
            normal_positions,
        )
        self.assertEqual(configurations[1].cross_team_assignment_count, 1)
        self.assertEqual(configurations[1].cross_team_next_index, 0)
        reassignment_log = self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
            ("rule_id", "=", rule.id),
            ("event_type", "=", "reassignment"),
            ("assignment_datetime", "=", original_assignment),
        ])
        self.assertEqual(len(reassignment_log), 1)
        self.assertEqual(
            lead.assignment_history_ids.sorted("id")[-1].assignment_type,
            "reassignment",
        )

    def test_sla_ignores_non_round_robin_assignment(self):
        self.env["brokerage.crm.sla.rule"].search([]).write({
            "active": False,
        })
        rule = self.env["brokerage.crm.sla.rule"].create({
            "name": "Round Robin Only",
            "rule_type": "first_contact",
            "duration_minutes": 60,
            "reminder_1_minutes": 1,
            "reminder_2_minutes": 0,
            "reminder_3_minutes": 0,
            "escalation_minutes": 0,
            "reassignment_minutes": 0,
            "activity_type_id": self.env.ref(
                "brokerage_crm.mail_activity_type_call_customer"
            ).id,
        })
        assigned_stage = self.env["crm.stage"].create({
            "name": "Assigned Manual SLA",
            "brokerage_code": "assigned",
        })
        lead = self.env["crm.lead"].create({
            "name": "Manual SLA Lead",
            "user_id": self.env.user.id,
            "stage_id": assigned_stage.id,
            "assignment_type": "manual",
        })
        lead.with_context(skip_assignment_history=True).write({
            "assigned_datetime": fields.Datetime.now()
            - timedelta(minutes=2),
        })

        self.env["crm.lead"]._cron_check_brokerage_sla()

        self.assertFalse(self.env["brokerage.crm.sla.log"].search([
            ("lead_id", "=", lead.id),
            ("rule_id", "=", rule.id),
        ]))

    def test_sla_restarts_for_cross_team_assignment_types(self):
        self.env["brokerage.crm.sla.rule"].search([]).write({
            "active": False,
        })
        rule = self.env["brokerage.crm.sla.rule"].create({
            "name": "Reassigned Lead SLA",
            "rule_type": "first_contact",
            "duration_minutes": 60,
            "reminder_1_minutes": 1,
            "reminder_2_minutes": 0,
            "reminder_3_minutes": 0,
            "escalation_minutes": 0,
            "reassignment_minutes": 0,
            "activity_type_id": self.env.ref(
                "brokerage_crm.mail_activity_type_call_customer"
            ).id,
        })
        assigned_stage = self.env["crm.stage"].create({
            "name": "Assigned Reassignment SLA",
            "brokerage_code": "assigned",
        })
        salesperson = self.env["res.users"].create({
            "name": "Reassigned SLA Agent",
            "login": "reassigned.sla.agent@test.invalid",
        })
        leads = self.env["crm.lead"].create([
            {
                "name": "SLA Cross-Team Reassignment",
                "user_id": salesperson.id,
                "stage_id": assigned_stage.id,
                "assignment_type": "reassignment",
            },
            {
                "name": "SLA Not Interested Reassignment",
                "user_id": salesperson.id,
                "stage_id": assigned_stage.id,
                "assignment_type": "not_interested_reassignment",
            },
        ])
        leads.with_context(skip_assignment_history=True).write({
            "assigned_datetime": fields.Datetime.now()
            - timedelta(minutes=2),
            "sla_cycle_active": True,
        })

        self.env["crm.lead"]._cron_check_brokerage_sla()

        for lead in leads:
            self.assertEqual(
                self.env["brokerage.crm.sla.log"].search_count([
                    ("lead_id", "=", lead.id),
                    ("rule_id", "=", rule.id),
                    ("event_type", "=", "reminder_1"),
                    (
                        "assignment_datetime",
                        "=",
                        lead.assigned_datetime,
                    ),
                ]),
                1,
            )

    def test_crm_settings_update_default_sla_timings(self):
        settings = self.env["res.config.settings"].create({
            "brokerage_sla_enabled": True,
            "brokerage_sla_reminder_1_minutes": 10,
            "brokerage_sla_reminder_2_minutes": 20,
            "brokerage_sla_reminder_3_minutes": 30,
            "brokerage_sla_escalation_minutes": 40,
            "brokerage_sla_reassignment_minutes": 70,
        })

        settings.set_values()

        rule = self.env.ref(
            "brokerage_crm.sla_rule_first_contact_default"
        )
        self.assertTrue(rule.active)
        self.assertEqual(rule.reminder_1_minutes, 10)
        self.assertEqual(rule.reminder_2_minutes, 20)
        self.assertEqual(rule.reminder_3_minutes, 30)
        self.assertEqual(rule.escalation_minutes, 40)
        self.assertEqual(rule.reassignment_minutes, 70)

        loaded = self.env["res.config.settings"].get_values()
        self.assertEqual(loaded["brokerage_sla_reminder_1_minutes"], 10)
        self.assertEqual(loaded["brokerage_sla_reassignment_minutes"], 70)

    def test_system_administrator_can_load_sla_settings(self):
        administrator = self.env["res.users"].create({
            "name": "Settings Administrator",
            "login": "settings.administrator@test.invalid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_system").id,
            ])],
        })

        values = self.env[
            "res.config.settings"
        ].with_user(administrator).get_values()

        self.assertIn("brokerage_sla_enabled", values)
        self.assertEqual(
            values["brokerage_sla_reminder_1_minutes"],
            self.env.ref(
                "brokerage_crm.sla_rule_first_contact_default"
            ).reminder_1_minutes,
        )
