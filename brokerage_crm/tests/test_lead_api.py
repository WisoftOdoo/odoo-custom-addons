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
        cls.assigned_stage = cls.env["crm.stage"].search([
            ("brokerage_code", "=", "assigned"),
        ], limit=1)
        if not cls.assigned_stage:
            cls.assigned_stage = cls.env["crm.stage"].create({
                "name": "Assigned API",
                "brokerage_code": "assigned",
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
