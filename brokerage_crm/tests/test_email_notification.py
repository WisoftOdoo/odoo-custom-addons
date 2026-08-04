from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestBrokerageEmailNotification(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["brokerage.crm.round.robin"].search([]).write({
            "active": False,
        })
        cls.env["brokerage.crm.sla.rule"].search([]).write({
            "active": False,
        })
        cls.always_open = cls.env["resource.calendar"].create({
            "name": "Email Tests 24/7",
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

    def _user(self, name, login, email):
        user = self.env["res.users"].create({
            "name": name,
            "login": login,
        })
        user.partner_id.email = email
        return user

    def test_assignment_email_is_queued_once(self):
        agent = self._user(
            "Email Assignment Agent",
            "email.assignment.agent@test.invalid",
            "assignment.agent@example.com",
        )
        team = self.env["crm.team"].create({
            "name": "Email Assignment Team",
        })
        lead = self.env["crm.lead"].with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
        ).create({"name": "Email Assignment Lead"})
        history = self.env[
            "brokerage.crm.assignment.history"
        ].create({
            "lead_id": lead.id,
            "new_user_id": agent.id,
            "new_team_id": team.id,
            "assignment_type": "round_robin",
            "reason": "Test assignment",
        })

        notification = self.env[
            "brokerage.crm.email.notification"
        ].search([("assignment_history_id", "=", history.id)])
        self.assertEqual(len(notification), 1)
        self.assertEqual(notification.state, "queued")
        self.assertEqual(notification.recipient_user_id, agent)
        self.assertEqual(
            notification.recipient_email,
            "assignment.agent@example.com",
        )
        self.assertTrue(notification.mail_id)
        self.assertEqual(
            notification.mail_id.email_to,
            "assignment.agent@example.com",
        )

        history._queue_new_assignee_email_once()
        self.assertEqual(
            self.env["brokerage.crm.email.notification"].search_count([
                ("assignment_history_id", "=", history.id),
            ]),
            1,
        )

    def test_missing_recipient_email_is_logged_as_skipped(self):
        agent = self._user(
            "Agent Without Email",
            "agent.without.email@test.invalid",
            False,
        )
        team = self.env["crm.team"].create({"name": "No Email Team"})
        lead = self.env["crm.lead"].with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
        ).create({"name": "No Email Lead"})
        history = self.env[
            "brokerage.crm.assignment.history"
        ].create({
            "lead_id": lead.id,
            "new_user_id": agent.id,
            "new_team_id": team.id,
            "assignment_type": "round_robin",
        })

        notification = self.env[
            "brokerage.crm.email.notification"
        ].search([("assignment_history_id", "=", history.id)])
        self.assertEqual(notification.state, "skipped")
        self.assertFalse(notification.mail_id)
        self.assertIn("no valid email", notification.failure_reason)

    def test_sla_reminder_and_escalation_emails_are_queued(self):
        agent = self._user(
            "Email SLA Agent",
            "email.sla.agent@test.invalid",
            "sla.agent@example.com",
        )
        leader = self._user(
            "Email SLA Leader",
            "email.sla.leader@test.invalid",
            "sla.leader@example.com",
        )
        team = self.env["crm.team"].create({
            "name": "Email SLA Team",
            "user_id": leader.id,
            "brokerage_working_calendar_id": self.always_open.id,
        })
        assigned_stage = self.env["crm.stage"].create({
            "name": "Assigned Email SLA",
            "brokerage_code": "assigned",
            "team_ids": [(6, 0, [team.id])],
        })
        rule = self.env["brokerage.crm.sla.rule"].create({
            "name": "Email SLA Rule",
            "rule_type": "first_contact",
            "team_id": team.id,
            "duration_minutes": 60,
            "reminder_1_minutes": 1,
            "reminder_2_minutes": 0,
            "reminder_3_minutes": 0,
            "escalation_minutes": 1,
            "reassignment_minutes": 0,
            "activity_type_id": self.env.ref(
                "brokerage_crm.mail_activity_type_call_customer"
            ).id,
        })
        lead = self.env["crm.lead"].with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
        ).create({
            "name": "Email SLA Lead",
            "team_id": team.id,
            "user_id": agent.id,
            "stage_id": assigned_stage.id,
        })
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
        ).write({
            "assignment_type": "round_robin",
            "assigned_datetime": (
                fields.Datetime.now() - timedelta(minutes=2)
            ),
            "sla_cycle_active": True,
        })

        self.env["crm.lead"]._cron_check_brokerage_sla()

        reminder = self.env[
            "brokerage.crm.email.notification"
        ].search([
            ("lead_id", "=", lead.id),
            ("notification_type", "=", "reminder_1"),
        ])
        escalation = self.env[
            "brokerage.crm.email.notification"
        ].search([
            ("lead_id", "=", lead.id),
            ("notification_type", "=", "team_leader_escalation"),
        ])
        self.assertEqual(reminder.recipient_user_id, agent)
        self.assertEqual(escalation.recipient_user_id, leader)
        self.assertEqual(reminder.state, "queued")
        self.assertEqual(escalation.state, "queued")
        self.assertEqual(reminder.sla_log_id.rule_id, rule)
