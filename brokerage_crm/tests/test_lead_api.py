import json

from odoo.tests import HttpCase, get_db_name, tagged


@tagged("post_install", "-at_install")
class TestBrokerageLeadApi(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        salesperson = cls.env["res.users"].create({
            "name": "API Salesperson",
            "login": "api.salesperson@test.invalid",
        })
        cls.salesperson = salesperson
        team = cls.env["crm.team"].create({"name": "API Sales Team"})
        cls.team = team
        cls.env["brokerage.crm.round.robin"].search([]).write({"active": False})
        cls.round_robin = cls.env["brokerage.crm.round.robin"].create({
            "name": "API Round Robin",
            "team_id": team.id,
            "member_ids": [(6, 0, [salesperson.id])],
        })
        cls.campaign_source = cls.env["utm.source"].create({
            "name": "API Campaign Source",
            "brokerage_category": "marketing",
        })
        cls.assigned_stage = cls.env["crm.stage"].search([
            ("brokerage_code", "=", "assigned"),
        ], limit=1)
        if not cls.assigned_stage:
            cls.assigned_stage = cls.env["crm.stage"].create({
                "name": "Assigned API",
                "brokerage_code": "assigned",
            })
        cls.assigned_stage.write({"team_ids": [(4, team.id)]})
        cls.new_stage = cls.env["crm.stage"].search([
            ("brokerage_code", "=", "new"),
        ], order="sequence, id", limit=1)
        if not cls.new_stage:
            cls.new_stage = cls.env["crm.stage"].create({
                "name": "New Lead API",
                "brokerage_code": "new",
                "sequence": 1,
            })

    def _post(self, payload):
        return self.url_open(
            "/brokerage/api/v1/leads",
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "X-Odoo-Database": get_db_name(),
            },
        )

    def test_create_and_deduplicate_public_lead(self):
        payload = {
            "customer_name": "API Customer",
            "phone": "+971500000001",
            "email": "api.customer@example.com",
            "source": "Meta",
            "assignment_type": "round_robin",
            "campaign": "API Summer Campaign",
            "medium": "API Social",
        }
        response = self._post(payload)
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertTrue(result["success"])
        self.assertFalse(result["duplicate"])
        self.assertEqual(result["lead"]["type"], "opportunity")
        self.assertTrue(result["lead"]["salesperson_id"])
        self.assertEqual(result["lead"]["stage_id"], self.assigned_stage.id)
        self.assertTrue(result["lead"]["assigned_datetime"])
        lead = self.env["crm.lead"].browse(result["lead"]["id"])
        self.assertEqual(lead.type, "opportunity")
        self.assertEqual(lead.assignment_type, "round_robin")
        self.assertEqual(lead.stage_id, self.assigned_stage)
        original_user = lead.user_id
        original_team = lead.team_id
        original_stage = lead.stage_id
        original_assigned_datetime = lead.assigned_datetime
        original_assignment_count = self.round_robin.assignment_count
        self.assertFalse(self.env["mail.activity"].search([
            ("res_model", "=", "crm.lead"),
            ("res_id", "=", lead.id),
            (
                "activity_type_id",
                "=",
                self.env.ref(
                    "brokerage_crm.mail_activity_type_call_customer"
                ).id,
            ),
        ]))

        duplicate_response = self._post({
            **payload,
            "customer_name": "Completely Different Customer Name",
            "email": "API.CUSTOMER@EXAMPLE.COM",
            "phone": "00971 50 000 0001",
            # Identity deduplication is intentionally independent of UTM.
            "source": self.campaign_source.name,
            "campaign": "A Different Campaign",
        })
        self.assertEqual(duplicate_response.status_code, 200, duplicate_response.text)
        self.assertTrue(duplicate_response.json()["duplicate"])
        self.assertEqual(
            duplicate_response.json()["duplicate_action"],
            "active_duplicate",
        )
        self.assertEqual(duplicate_response.json()["lead"]["id"], lead.id)
        lead.invalidate_recordset()
        self.round_robin.invalidate_recordset()
        self.assertEqual(lead.user_id, original_user)
        self.assertEqual(lead.team_id, original_team)
        self.assertEqual(lead.stage_id, original_stage)
        self.assertEqual(lead.assigned_datetime, original_assigned_datetime)
        self.assertEqual(lead.repeat_enquiry_count, 1)
        self.assertEqual(
            self.round_robin.assignment_count,
            original_assignment_count,
        )
        self.assertEqual(
            self.env["crm.lead"].search_count([
                (
                    "brokerage_deduplication_key",
                    "=",
                    lead.brokerage_deduplication_key,
                ),
            ]),
            1,
        )
        self.assertEqual(lead.source_id.name, "Meta")
        self.assertEqual(lead.campaign_id.name, "API Summer Campaign")
        self.assertEqual(lead.medium_id.name, "API Social")

    def test_lost_duplicate_reopens_for_previous_eligible_owner(self):
        payload = {
            "customer_name": "Returning Lost Customer",
            "phone": "+971500000011",
            "email": "returning.lost@example.com",
            "source": self.campaign_source.name,
            "assignment_type": "round_robin",
        }
        created = self._post(payload)
        self.assertEqual(created.status_code, 201, created.text)
        lead = self.env["crm.lead"].browse(created.json()["lead"]["id"])
        previous_user = lead.user_id
        previous_team = lead.team_id
        assignment_count = self.round_robin.assignment_count
        lead.action_set_lost()

        repeated = self._post({
            **payload,
            "customer_name": "A New Spelling Of The Customer",
            "campaign": "Returning Customer Campaign",
        })
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(
            repeated.json()["duplicate_action"],
            "reopened_previous_user",
        )
        lead.invalidate_recordset()
        self.round_robin.invalidate_recordset()
        self.assertTrue(lead.active)
        self.assertEqual(lead.user_id, previous_user)
        self.assertEqual(lead.team_id, previous_team)
        self.assertEqual(lead.stage_id, self.assigned_stage)
        self.assertEqual(lead.assignment_type, "reassignment")
        self.assertTrue(lead.sla_cycle_active)
        self.assertEqual(lead.repeat_enquiry_count, 1)
        self.assertEqual(
            self.round_robin.assignment_count,
            assignment_count,
        )
        latest_history = lead.assignment_history_ids.sorted(
            key=lambda history: (history.assigned_datetime, history.id),
            reverse=True,
        )[:1]
        self.assertEqual(latest_history.previous_user_id, previous_user)
        self.assertEqual(latest_history.new_user_id, previous_user)
        self.assertIn("Repeat enquiry", latest_history.reason)

    def test_not_interested_duplicate_reopens_instead_of_invalid_review(self):
        payload = {
            "customer_name": "Returning Not Interested Customer",
            "phone": "+971500000013",
            "email": "returning.not.interested@example.com",
            "source": self.campaign_source.name,
            "assignment_type": "round_robin",
        }
        created = self._post(payload)
        self.assertEqual(created.status_code, 201, created.text)
        lead = self.env["crm.lead"].browse(created.json()["lead"]["id"])
        previous_user = lead.user_id
        not_interested_stage = self.env.ref(
            "brokerage_crm.crm_stage_not_interested"
        )
        not_interested_status = self.env.ref(
            "brokerage_crm.lead_status_not_interested"
        )
        lead.with_context(brokerage_workflow_action=True).write({
            "stage_id": not_interested_stage.id,
            "lead_status_id": not_interested_status.id,
            "sla_cycle_active": False,
        })

        repeated = self._post(payload)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(
            repeated.json()["duplicate_action"],
            "reopened_previous_user",
        )
        lead.invalidate_recordset()
        self.assertTrue(lead.active)
        self.assertEqual(lead.user_id, previous_user)
        self.assertEqual(lead.stage_id, self.assigned_stage)
        self.assertEqual(lead.assignment_type, "reassignment")
        self.assertTrue(lead.sla_cycle_active)
        self.assertFalse(lead.not_interested_reassignment_done)

    def test_lost_duplicate_uses_normal_round_robin_if_owner_unavailable(self):
        payload = {
            "customer_name": "Fallback Customer",
            "phone": "+971500000012",
            "email": "fallback.customer@example.com",
            "source": self.campaign_source.name,
            "assignment_type": "round_robin",
        }
        created = self._post(payload)
        self.assertEqual(created.status_code, 201, created.text)
        lead = self.env["crm.lead"].browse(created.json()["lead"]["id"])
        previous_user = lead.user_id
        lead.action_set_lost()
        previous_user.available_for_crm_assignment = False

        fallback_user = self.env["res.users"].create({
            "name": "API Fallback Salesperson",
            "login": "api.fallback.salesperson@test.invalid",
        })
        fallback_team = self.env["crm.team"].create({
            "name": "API Fallback Team",
        })
        fallback_rule = self.env["brokerage.crm.round.robin"].create({
            "name": "API Fallback Round Robin",
            "team_id": fallback_team.id,
            "sequence": self.round_robin.sequence + 1,
            "member_ids": [(6, 0, [fallback_user.id])],
        })
        self.assigned_stage.write({"team_ids": [(4, fallback_team.id)]})

        repeated = self._post(payload)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(
            repeated.json()["duplicate_action"],
            "reopened_round_robin",
        )
        lead.invalidate_recordset()
        fallback_rule.invalidate_recordset()
        self.assertTrue(lead.active)
        self.assertEqual(lead.user_id, fallback_user)
        self.assertEqual(lead.team_id, fallback_team)
        self.assertEqual(lead.stage_id, self.assigned_stage)
        self.assertTrue(lead.sla_cycle_active)
        self.assertEqual(fallback_rule.assignment_count, 1)

    def test_required_fields(self):
        response = self._post({"source": "Meta"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])

    def test_round_robin_is_requested_by_assignment_type_not_source(self):
        response = self._post({
            "customer_name": "Campaign Customer",
            "phone": "+971500000002",
            "email": "campaign.customer@example.com",
            "source": self.campaign_source.name,
            "assignment_type": "round_robin",
            "utm_campaign": "Meta Launch 2026",
            "utm_medium": "Paid Social",
        })
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(result["lead"]["assignment_type"], "round_robin")
        self.assertTrue(result["lead"]["salesperson_id"])
        lead = self.env["crm.lead"].browse(result["lead"]["id"])
        self.assertEqual(lead.source_id, self.campaign_source)
        self.assertEqual(lead.assignment_type, "round_robin")
        self.assertEqual(lead.stage_id, self.assigned_stage)
        self.assertEqual(lead.campaign_id.name, "Meta Launch 2026")
        self.assertEqual(lead.medium_id.name, "Paid Social")
        self.assertEqual(result["lead"]["campaign"], "Meta Launch 2026")
        self.assertEqual(result["lead"]["medium"], "Paid Social")

    def test_manual_assignment_creates_unassigned_lead(self):
        response = self._post({
            "name": "Manual API Customer",
            "mobile": "+971500000003",
            "email": "manual.api.customer@example.com",
            "source": self.campaign_source.name,
            "assignment_type": "manual",
        })
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(result["lead"]["assignment_type"], "manual")
        self.assertIsNone(result["lead"]["salesperson_id"])
        self.assertIsNone(result["lead"]["team_id"])
        self.assertEqual(result["lead"]["stage_id"], self.new_stage.id)
        lead = self.env["crm.lead"].browse(result["lead"]["id"])
        self.assertEqual(lead.assignment_type, "manual")
        self.assertFalse(lead.user_id)
        self.assertFalse(lead.team_id)
        self.assertEqual(lead.stage_id, self.new_stage)
        self.assertFalse(lead.sla_cycle_active)
        self.assertFalse(lead.assignment_history_ids.filtered(
            lambda history: history.assignment_type == "round_robin"
        ))

    def test_missing_assignment_type_is_rejected(self):
        response = self._post({
            "name": "Missing Assignment Type Customer",
            "phone": "+971500000005",
            "email": "missing.assignment@example.com",
            "source": self.campaign_source.name,
        })
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(
            response.json()["error"]["message"],
            "assignment_type is required.",
        )

    def test_invalid_assignment_type_is_rejected(self):
        response = self._post({
            "customer_name": "Invalid Type Customer",
            "phone": "+971500000004",
            "email": "invalid.type@example.com",
            "source": self.campaign_source.name,
            "assignment_type": "automatic",
        })
        self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(response.json()["success"])
