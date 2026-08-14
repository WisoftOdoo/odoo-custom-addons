import base64
from datetime import timedelta
from unittest import skip

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestLeadValidation(TransactionCase):
    def test_crm_creation_requires_phone_or_email(self):
        crm_leads = self.env["crm.lead"].with_context(
            default_type="opportunity"
        )
        with self.assertRaisesRegex(ValidationError, "Phone or Email"):
            crm_leads.create({"name": "Missing Contact Details"})

        phone_lead = crm_leads.create({
            "name": "Phone Contact",
            "phone": "+971500009991",
        })
        email_lead = crm_leads.create({
            "name": "Email Contact",
            "email_from": "contact.validation@example.com",
        })
        self.assertTrue(phone_lead)
        self.assertTrue(email_lead)

    def test_manual_crm_creation_warns_and_blocks_duplicate_contact(self):
        crm_leads = self.env["crm.lead"].with_context(
            default_type="opportunity"
        )
        existing = crm_leads.create({
            "name": "Original Manual Enquiry",
            "contact_name": "Original Customer Name",
            "email_from": "manual.duplicate@example.com",
            "phone": "+971500008831",
        })

        draft = crm_leads.new({
            "name": "Repeat Manual Enquiry",
            "contact_name": "Different Customer Spelling",
            "email_from": "MANUAL.DUPLICATE@example.com",
            "phone": "+971500008831",
        })
        warning = draft._onchange_brokerage_duplicate_contact()
        self.assertEqual(warning["warning"]["title"], "Duplicate Lead Found")
        self.assertIn(existing.display_name, warning["warning"]["message"])

        with self.assertRaisesRegex(
            ValidationError,
            "A lead already exists for this phone/email",
        ):
            crm_leads.create({
                "name": "Repeat Manual Enquiry",
                "contact_name": "Different Customer Spelling",
                "email_from": "MANUAL.DUPLICATE@example.com",
                "phone": "+971500008831",
            })

        self.assertEqual(
            self.env["crm.lead"].search_count([
                ("brokerage_deduplication_key", "=", (
                    existing.brokerage_deduplication_key
                )),
            ]),
            1,
        )

    def test_team_leader_can_create_owned_lead_with_system_audit(self):
        team_leader = self.env["res.users"].create({
            "name": "Lead Creation Team Leader",
            "login": "lead.creation.team.leader@test.invalid",
            "group_ids": [(6, 0, [
                self.env.ref(
                    "brokerage_crm.group_brokerage_team_leader"
                ).id,
            ])],
        })
        team = self.env["crm.team"].create({
            "name": "Team Leader Creation Team",
            "user_id": team_leader.id,
            "member_ids": [(6, 0, [team_leader.id])],
        })
        new_stage, assigned_stage = self.env["crm.stage"].create([
            {
                "name": "Team Leader Creation New",
                "sequence": -120,
                "brokerage_code": "new",
                "team_ids": [(6, 0, [team.id])],
            },
            {
                "name": "Team Leader Creation Assigned",
                "sequence": -110,
                "brokerage_code": "assigned",
                "team_ids": [(6, 0, [team.id])],
            },
        ])

        lead = self.env["crm.lead"].with_user(team_leader).with_context(
            default_user_id=team_leader.id,
            default_team_id=team.id,
        ).create({
            "name": "Team Leader Created Lead",
            "type": "opportunity",
            "assignment_type": "manual",
            "stage_id": new_stage.id,
        })

        self.assertEqual(lead.user_id, team_leader)
        self.assertEqual(lead.stage_id, assigned_stage)
        history = lead.sudo().assignment_history_ids
        self.assertEqual(len(history), 1)
        self.assertEqual(history.new_user_id, team_leader)
        self.assertEqual(history.assigned_by_id, team_leader)

    def test_salesperson_assignment_moves_only_new_leads_to_assigned(self):
        salesperson = self.env["res.users"].create({
            "name": "Initial Assignment Agent",
            "login": "initial.assignment.agent@test.invalid",
        })
        team = self.env["crm.team"].create({
            "name": "Initial Assignment Team",
            "member_ids": [(6, 0, [salesperson.id])],
        })
        new_stage, assigned_stage, contacted_stage = self.env[
            "crm.stage"
        ].create([
            {
                "name": "Initial Assignment New",
                "sequence": -100,
                "brokerage_code": "new",
                "team_ids": [(6, 0, [team.id])],
            },
            {
                "name": "Initial Assignment Assigned",
                "sequence": -90,
                "brokerage_code": "assigned",
                "team_ids": [(6, 0, [team.id])],
            },
            {
                "name": "Initial Assignment Contacted",
                "sequence": -80,
                "brokerage_code": "contacted",
                "team_ids": [(6, 0, [team.id])],
            },
        ])

        owned_at_creation = self.env["crm.lead"].create({
            "name": "Owned At Creation",
            "type": "opportunity",
            "assignment_type": "manual",
            "team_id": team.id,
            "user_id": salesperson.id,
            "stage_id": new_stage.id,
        })
        self.assertEqual(owned_at_creation.stage_id, assigned_stage)
        self.assertFalse(owned_at_creation.sla_cycle_active)

        defaulted_at_creation = self.env["crm.lead"].with_context(
            default_user_id=salesperson.id,
            default_team_id=team.id,
        ).create({
            "name": "Owned Through Default Context",
            "type": "opportunity",
            "assignment_type": "manual",
            "stage_id": new_stage.id,
        })
        self.assertEqual(defaulted_at_creation.user_id, salesperson)
        self.assertEqual(defaulted_at_creation.team_id, team)
        self.assertEqual(defaulted_at_creation.stage_id, assigned_stage)
        self.assertFalse(defaulted_at_creation.sla_cycle_active)

        assigned_later = self.env["crm.lead"].create({
            "name": "Assigned Later",
            "type": "opportunity",
            "assignment_type": "manual",
            "team_id": team.id,
            "user_id": False,
            "stage_id": new_stage.id,
        })
        assigned_later.user_id = salesperson
        self.assertEqual(assigned_later.stage_id, assigned_stage)
        self.assertFalse(assigned_later.sla_cycle_active)

        progressed_lead = self.env["crm.lead"].create({
            "name": "Already Progressed",
            "type": "opportunity",
            "assignment_type": "manual",
            "team_id": team.id,
            "user_id": False,
            "stage_id": contacted_stage.id,
        })
        progressed_lead.user_id = salesperson
        self.assertEqual(progressed_lead.stage_id, contacted_stage)

    def test_next_action_follows_brokerage_stage_hierarchy(self):
        stages = self.env["crm.stage"].create([
            {
                "name": "Hint Assigned",
                "brokerage_code": "assigned",
            },
            {
                "name": "Hint Contact Attempted",
                "brokerage_code": "contact_attempted",
            },
            {
                "name": "Hint Contacted",
                "brokerage_code": "contacted",
            },
            {
                "name": "Hint Meeting Scheduled",
                "brokerage_code": "meeting_scheduled",
            },
            {
                "name": "Hint Forecast",
                "brokerage_code": "forecast",
            },
        ])
        lead = self.env["crm.lead"].create({
            "name": "Next Step Guidance",
            "type": "opportunity",
            "stage_id": stages[0].id,
        })

        self.assertEqual(lead.brokerage_next_action, "contact_attempt")
        lead.with_context(brokerage_workflow_action=True).stage_id = stages[1]
        self.assertEqual(lead.brokerage_next_action, "contact_attempt")
        lead.with_context(brokerage_workflow_action=True).stage_id = stages[2]
        self.assertEqual(lead.brokerage_next_action, "schedule_meeting")
        lead.with_context(brokerage_workflow_action=True).stage_id = stages[3]
        self.assertEqual(lead.brokerage_next_action, "complete_meeting")
        lead.with_context(brokerage_workflow_action=True).stage_id = stages[4]
        self.assertFalse(lead.brokerage_next_action)

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

    def test_closed_won_follows_hot_without_kyc_or_booking(self):
        hot_stage, won_stage, assigned_stage = self.env["crm.stage"].create([
            {
                "name": "Direct Won Test Hot",
                "sequence": 80,
                "brokerage_code": "hot",
            },
            {
                "name": "Direct Won Test Closed Won",
                "sequence": 90,
                "brokerage_code": "won",
                "is_won": True,
            },
            {
                "name": "Direct Won Test Assigned",
                "sequence": 20,
                "brokerage_code": "assigned",
            },
        ])
        hot_lead = self.env["crm.lead"].create({
            "name": "Hot Lead Ready To Win",
            "stage_id": hot_stage.id,
        })
        hot_lead.write({"stage_id": won_stage.id})
        self.assertEqual(hot_lead.stage_id, won_stage)

        early_lead = self.env["crm.lead"].create({
            "name": "Lead Not Yet Hot",
            "stage_id": assigned_stage.id,
        })
        with self.assertRaisesRegex(ValidationError, "must reach Hot"):
            early_lead.write({"stage_id": won_stage.id})

    @skip("KYC and Booking / Documentation were retired in 19.0.1.30.0")
    def test_booking_requires_complete_verified_kyc(self):
        agent = self.env["res.users"].create({
            "name": "Booking KYC Agent",
            "login": "booking.kyc.agent@test.invalid",
            "group_ids": [(6, 0, [
                self.env.ref(
                    "brokerage_crm.group_brokerage_crm_user"
                ).id,
            ])],
        })
        (
            assigned_stage,
            hot_stage,
            kyc_stage,
            booking_stage,
            won_stage,
        ) = self.env[
            "crm.stage"
        ].create([
            {
                "name": "KYC Test Assigned",
                "sequence": 20,
                "brokerage_code": "assigned",
            },
            {
                "name": "KYC Test Hot",
                "sequence": 80,
                "brokerage_code": "hot",
            },
            {
                "name": "KYC Test In Progress",
                "sequence": 90,
                "brokerage_code": "kyc",
            },
            {
                "name": "KYC Test Booking",
                "sequence": 100,
                "brokerage_code": "booking",
            },
            {
                "name": "KYC Test Closed Won",
                "sequence": 110,
                "brokerage_code": "won",
                "is_won": True,
            },
        ])
        developer = self.env["brokerage.developer"].create({
            "name": "KYC Test Developer",
        })
        project = self.env["brokerage.project"].create({
            "name": "KYC Test Project",
            "developer_id": developer.id,
        })
        successful_status = self.env[
            "brokerage.crm.lead.status"
        ].create({
            "name": "KYC Successful Contact",
            "code": "kyc_successful_contact",
            "is_contact_attempt": True,
            "is_successful_contact": True,
        })
        lead = self.env["crm.lead"].create({
            "name": "Booking KYC Validation",
            "user_id": agent.id,
            "stage_id": assigned_stage.id,
        })
        self.env["brokerage.crm.contact.attempt"].with_user(agent).create({
            "lead_id": lead.id,
            "user_id": agent.id,
            "method": "call",
            "status_id": successful_status.id,
        })
        meeting_start = fields.Datetime.now()
        self.env["brokerage.crm.meeting"].with_user(agent).create({
            "lead_id": lead.id,
            "name": "KYC Completed Meeting",
            "state": "completed",
            "meeting_type": "phone",
            "scheduled_start": meeting_start,
            "scheduled_end": meeting_start + timedelta(minutes=30),
            "actual_start": meeting_start,
            "actual_end": meeting_start + timedelta(minutes=20),
            "outcome": "interested",
            "developer_id": developer.id,
            "project_id": project.id,
            "agent_remarks": "Customer is proceeding with KYC.",
            "next_action": "Collect identity documents.",
            "next_follow_up_date": fields.Date.today(),
        })
        lead.with_user(agent).write({
            "final_developer_id": developer.id,
            "final_project_id": project.id,
            "final_unit_type": "2 Bedroom",
            "expected_booking_date": fields.Date.today()
            + timedelta(days=7),
        })

        with self.assertRaisesRegex(ValidationError, "KYC owner"):
            lead.with_user(agent).write({"stage_id": hot_stage.id})

        lead.with_user(agent).write({"kyc_owner_id": agent.id})
        lead.with_user(agent).write({"stage_id": hot_stage.id})
        lead.with_user(agent).write({"stage_id": kyc_stage.id})
        self.assertEqual(lead.kyc_status, "in_progress")

        with self.assertRaisesRegex(ValidationError, "marked as Verified"):
            lead.with_user(agent).write({"stage_id": booking_stage.id})

        with self.assertRaisesRegex(ValidationError, "Complete these KYC"):
            lead.with_user(agent).write({"kyc_status": "verified"})

        attachment = self.env["ir.attachment"].with_user(agent).create({
            "name": "identity-document.pdf",
            "datas": base64.b64encode(b"test identity document"),
            "mimetype": "application/pdf",
            "res_model": "crm.lead",
            "res_id": lead.id,
        })
        lead.with_user(agent).write({
            "kyc_identity_type": "passport",
            "kyc_identity_number": "P1234567",
            "kyc_identity_expiry_date": fields.Date.today()
            + timedelta(days=365),
            "kyc_nationality_id": self.env.ref("base.ae").id,
            "kyc_source_of_funds": "salary",
            "kyc_document_ids": [(6, 0, attachment.ids)],
            "kyc_status": "verified",
        })
        self.assertEqual(lead.kyc_verified_by_id, agent)
        self.assertTrue(lead.kyc_verified_datetime)

        with self.assertRaisesRegex(
            ValidationError,
            "Booking / Documentation details",
        ):
            lead.with_user(agent).write({"stage_id": booking_stage.id})

        payment_method = self.env[
            "brokerage.crm.booking.payment.method"
        ].create({
            "name": "KYC Test Bank Transfer",
        })
        pending_status = self.env[
            "brokerage.crm.booking.documentation.status"
        ].create({
            "name": "KYC Test Documentation Pending",
        })
        complete_status = self.env[
            "brokerage.crm.booking.documentation.status"
        ].create({
            "name": "KYC Test Documentation Complete",
            "allows_closing": True,
        })
        lead.with_user(agent).write({
            "booking_unit_reference": "TOWER-A-1204",
            "estimated_property_value": 1_000_000,
            "booking_amount": 100_000,
            "booking_date": fields.Date.today(),
            "booking_payment_method_id": payment_method.id,
            "booking_documentation_status_id": pending_status.id,
            "booking_documentation_owner_id": agent.id,
        })
        lead.with_user(agent).write({"stage_id": booking_stage.id})
        self.assertEqual(lead.stage_id, booking_stage)

        with self.assertRaisesRegex(
            ValidationError,
            "attach the booking documents",
        ):
            lead.with_user(agent).write({"stage_id": won_stage.id})

        with self.assertRaisesRegex(
            ValidationError,
            "Attach at least one Booking Document",
        ):
            lead.with_user(agent).write({
                "booking_documentation_status_id": complete_status.id,
            })

        booking_attachment = self.env["ir.attachment"].with_user(agent).create({
            "name": "booking-form.pdf",
            "datas": base64.b64encode(b"test booking form"),
            "mimetype": "application/pdf",
            "res_model": "crm.lead",
            "res_id": lead.id,
        })
        lead.with_user(agent).write({
            "booking_document_ids": [(6, 0, booking_attachment.ids)],
            "booking_documentation_status_id": complete_status.id,
        })
        self.assertEqual(
            lead.booking_documentation_completed_by_id,
            agent,
        )
        self.assertTrue(lead.booking_documentation_completed_datetime)

        lead.with_user(agent).write({"stage_id": won_stage.id})
        self.assertEqual(lead.stage_id, won_stage)
