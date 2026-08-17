import hashlib
import hmac
import json
from unittest.mock import Mock, patch

from odoo.tests import HttpCase, TransactionCase, get_db_name, tagged


class TestMetaWebhookProcessing(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["brokerage.crm.round.robin"].search([]).write({
            "active": False,
        })
        cls.salesperson = cls.env["res.users"].create({
            "name": "Meta Webhook Salesperson",
            "login": "meta.webhook.salesperson@test.invalid",
        })
        cls.team = cls.env["crm.team"].create({
            "name": "Meta Webhook Sales Team",
        })
        cls.round_robin = cls.env["brokerage.crm.round.robin"].create({
            "name": "Meta Webhook Round Robin",
            "team_id": cls.team.id,
            "member_ids": [(6, 0, [cls.salesperson.id])],
        })
        cls.assigned_stage = cls.env["crm.stage"].create({
            "name": "Meta Webhook Assigned",
            "brokerage_code": "assigned",
            "sequence": -200,
            "team_ids": [(6, 0, [cls.team.id])],
        })
        cls.source = cls.env.ref("brokerage_crm.lead_source_meta")
        parameters = cls.env["ir.config_parameter"].sudo()
        parameters.set_param("brokerage_crm.meta_enabled", "True")
        parameters.set_param("brokerage_crm.meta_app_secret", "test-secret")
        parameters.set_param(
            "brokerage_crm.meta_page_access_token",
            "test-page-token",
        )
        parameters.set_param("brokerage_crm.meta_page_id", "123456")
        parameters.set_param("brokerage_crm.meta_graph_version", "v24.0")
        parameters.set_param("brokerage_crm.meta_source_id", cls.source.id)

    def test_process_meta_lead_uses_existing_round_robin_workflow(self):
        event = self.env["brokerage.meta.webhook.event"].enqueue_payload({
            "object": "page",
            "entry": [{
                "id": "123456",
                "changes": [{
                    "field": "leadgen",
                    "value": {
                        "leadgen_id": "META-LEAD-1001",
                        "form_id": "FORM-10",
                        "ad_id": "AD-20",
                    },
                }],
            }],
        })
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.text = ""
        response.json.return_value = {
            "id": "META-LEAD-1001",
            "created_time": "2026-08-14T10:00:00+0000",
            "form_id": "FORM-10",
            "ad_id": "AD-20",
            "ad_name": "Dubai Apartments Ad",
            "campaign_id": "CAMPAIGN-30",
            "campaign_name": "Dubai Apartments Campaign",
            "platform": "instagram",
            "field_data": [
                {"name": "full_name", "values": ["Meta Customer"]},
                {"name": "email", "values": ["meta.customer@example.com"]},
                {"name": "phone_number", "values": ["+971500001234"]},
                {"name": "preferred_location", "values": ["Dubai Marina"]},
            ],
        }
        request_path = (
            "odoo.addons.brokerage_crm.models.meta_webhook_event.requests.get"
        )
        with patch(request_path, return_value=response) as mocked_get:
            lead = event.with_context(allow_meta_request=True)._process_event()

        mocked_get.assert_called_once()
        self.assertEqual(event.state, "processed")
        self.assertEqual(event.lead_id, lead)
        self.assertFalse(event.duplicate)
        self.assertEqual(lead.contact_name, "Meta Customer")
        self.assertEqual(lead.assignment_type, "round_robin")
        self.assertEqual(lead.user_id, self.salesperson)
        self.assertEqual(lead.team_id, self.team)
        self.assertEqual(lead.stage_id, self.assigned_stage)
        self.assertEqual(lead.source_id, self.source)
        self.assertEqual(lead.campaign_id.name, "Dubai Apartments Campaign")
        self.assertIn("Preferred Location: Dubai Marina", lead.description)


@tagged("post_install", "-at_install")
class TestMetaWebhookController(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        parameters = cls.env["ir.config_parameter"].sudo()
        parameters.set_param("brokerage_crm.meta_enabled", "True")
        parameters.set_param("brokerage_crm.meta_verify_token", "verify-123")
        parameters.set_param("brokerage_crm.meta_app_secret", "secret-123")
        parameters.set_param("brokerage_crm.meta_page_id", "987654")

    def test_verification_and_signed_event_delivery(self):
        verification = self.url_open(
            "/brokerage/api/v1/meta/webhook"
            "?hub.mode=subscribe&hub.verify_token=verify-123"
            "&hub.challenge=24680",
            headers={"X-Odoo-Database": get_db_name()},
        )
        self.assertEqual(verification.status_code, 200)
        self.assertEqual(verification.text, "24680")

        payload = {
            "object": "page",
            "entry": [{
                "id": "987654",
                "changes": [{
                    "field": "leadgen",
                    "value": {
                        "leadgen_id": "META-CONTROLLER-1001",
                        "form_id": "FORM-CONTROLLER",
                    },
                }],
            }],
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = "sha256=%s" % hmac.new(
            b"secret-123",
            body,
            hashlib.sha256,
        ).hexdigest()
        rejected = self.url_open(
            "/brokerage/api/v1/meta/webhook",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalid",
                "X-Odoo-Database": get_db_name(),
            },
        )
        self.assertEqual(rejected.status_code, 403)
        self.assertFalse(
            self.env["brokerage.meta.webhook.event"].search([
                ("meta_lead_id", "=", "META-CONTROLLER-1001"),
            ])
        )

        response = self.url_open(
            "/brokerage/api/v1/meta/webhook",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
                "X-Odoo-Database": get_db_name(),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.text, "EVENT_RECEIVED")
        self.assertEqual(
            self.env["brokerage.meta.webhook.event"].search_count([
                ("meta_lead_id", "=", "META-CONTROLLER-1001"),
            ]),
            1,
        )
        repeated = self.url_open(
            "/brokerage/api/v1/meta/webhook",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
                "X-Odoo-Database": get_db_name(),
            },
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(
            self.env["brokerage.meta.webhook.event"].search_count([
                ("meta_lead_id", "=", "META-CONTROLLER-1001"),
            ]),
            1,
        )
