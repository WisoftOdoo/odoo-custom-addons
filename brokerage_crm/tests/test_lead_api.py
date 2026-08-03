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
        team = cls.env["crm.team"].create({"name": "API Sales Team"})
        cls.env["brokerage.crm.round.robin"].search([]).write({"active": False})
        cls.env["brokerage.crm.round.robin"].create({
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
            "external_lead_id": "meta-test-001",
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

        duplicate_response = self._post(payload)
        self.assertEqual(duplicate_response.status_code, 200, duplicate_response.text)
        self.assertTrue(duplicate_response.json()["duplicate"])
        self.assertEqual(
            self.env["crm.lead"].search_count([
                ("external_lead_id", "=", "meta-test-001"),
            ]),
            1,
        )

    def test_required_fields(self):
        response = self._post({"source": "Meta"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])

    def test_round_robin_is_requested_by_assignment_type_not_source(self):
        response = self._post({
            "customer_name": "Campaign Customer",
            "phone": "+971500000002",
            "source": self.campaign_source.name,
            "assignment_type": "round_robin",
            "external_lead_id": "campaign-round-robin-001",
        })
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(result["lead"]["assignment_type"], "round_robin")
        self.assertTrue(result["lead"]["salesperson_id"])
        lead = self.env["crm.lead"].browse(result["lead"]["id"])
        self.assertEqual(lead.source_id, self.campaign_source)
        self.assertEqual(lead.assignment_type, "round_robin")
        self.assertEqual(lead.stage_id, self.assigned_stage)

    def test_missing_assignment_type_creates_manual_lead(self):
        response = self._post({
            "customer_name": "Manual API Customer",
            "phone": "+971500000003",
            "source": self.campaign_source.name,
            "external_lead_id": "campaign-manual-001",
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

    def test_invalid_assignment_type_is_rejected(self):
        response = self._post({
            "customer_name": "Invalid Type Customer",
            "phone": "+971500000004",
            "source": self.campaign_source.name,
            "assignment_type": "automatic",
        })
        self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(response.json()["success"])
