import hashlib
from unittest.mock import Mock, patch

from odoo.tests import TransactionCase


class TestMetaCrmEvent(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        parameters = cls.env["ir.config_parameter"].sudo()
        parameters.set_param(
            "brokerage_crm.meta_crm_feedback_enabled", "True"
        )
        parameters.set_param(
            "brokerage_crm.meta_crm_dataset_id", "988258467125920"
        )
        parameters.set_param(
            "brokerage_crm.meta_crm_access_token", "test-capi-token"
        )
        parameters.set_param(
            "brokerage_crm.meta_crm_graph_version", "v26.0"
        )
        parameters.set_param(
            "brokerage_crm.meta_crm_name", "Miraj Test Odoo CRM"
        )
        parameters.set_param(
            "brokerage_crm.meta_crm_test_event_code", "TEST12345"
        )
        cls.new_stage, cls.contacted_stage = cls.env["crm.stage"].create([
            {
                "name": "Meta Feedback New",
                "brokerage_code": "new",
                "sequence": -500,
            },
            {
                "name": "Meta Feedback Contacted",
                "brokerage_code": "contacted",
                "sequence": -490,
            },
        ])

    def _lead_and_webhook(self, suffix="1"):
        lead = self.env["crm.lead"].create({
            "name": "Meta Feedback Lead %s" % suffix,
            "contact_name": "Feedback Customer %s" % suffix,
            "email_from": "Feedback.%s@Example.com" % suffix,
            "phone": "+971 50 000 %s" % suffix.zfill(4),
            "assignment_type": "manual",
            "stage_id": self.new_stage.id,
            "type": "opportunity",
        })
        webhook = self.env["brokerage.meta.webhook.event"].create({
            "name": "Meta Lead META-FEEDBACK-%s" % suffix,
            "meta_lead_id": "META-FEEDBACK-%s" % suffix,
            "page_id": "997021276824485",
            "payload": "{}",
            "state": "processed",
            "processed_at": "2026-09-14 10:00:00",
            "lead_id": lead.id,
        })
        return lead, webhook

    def test_only_meta_linked_lead_stage_changes_are_queued_once(self):
        lead, _webhook = self._lead_and_webhook("1001")
        lead.with_context(brokerage_workflow_action=True).write({
            "stage_id": self.contacted_stage.id,
        })
        event = self.env["brokerage.meta.crm.event"].search([
            ("lead_id", "=", lead.id),
        ])
        self.assertEqual(len(event), 1)
        self.assertEqual(event.event_name, "Contact")

        lead.with_context(brokerage_workflow_action=True).write({
            "stage_id": self.contacted_stage.id,
        })
        self.assertEqual(
            self.env["brokerage.meta.crm.event"].search_count([
                ("lead_id", "=", lead.id),
            ]),
            1,
        )

        manual_lead = self.env["crm.lead"].create({
            "name": "Non-Meta Lead",
            "email_from": "non.meta@example.com",
            "phone": "+971500009999",
            "assignment_type": "manual",
            "stage_id": self.new_stage.id,
            "type": "opportunity",
        })
        manual_lead.with_context(brokerage_workflow_action=True).write({
            "stage_id": self.contacted_stage.id,
        })
        self.assertFalse(self.env["brokerage.meta.crm.event"].search([
            ("lead_id", "=", manual_lead.id),
        ]))

    def test_payload_uses_meta_lead_id_and_hashed_contact_data(self):
        lead, webhook = self._lead_and_webhook("1002")
        event = self.env["brokerage.meta.crm.event"].enqueue_for_lead(
            lead,
            "Lead",
            webhook_event=webhook,
            event_time="2026-09-14 10:05:00",
        )
        payload = event._build_payload()
        item = payload["data"][0]
        self.assertEqual(item["event_name"], "Lead")
        self.assertEqual(item["action_source"], "system_generated")
        self.assertEqual(item["user_data"]["lead_id"], "META-FEEDBACK-1002")
        self.assertEqual(
            item["user_data"]["em"],
            [hashlib.sha256(b"feedback.1002@example.com").hexdigest()],
        )
        self.assertEqual(
            item["user_data"]["ph"],
            [hashlib.sha256(b"971500001002").hexdigest()],
        )
        self.assertEqual(item["custom_data"]["event_source"], "crm")
        self.assertEqual(
            item["custom_data"]["lead_event_source"],
            "Miraj Test Odoo CRM",
        )
        self.assertEqual(payload["test_event_code"], "TEST12345")

        repeated = self.env["brokerage.meta.crm.event"].enqueue_for_lead(
            lead,
            "Lead",
            webhook_event=webhook,
        )
        self.assertEqual(repeated, event)

    def test_successful_delivery_uses_separate_dataset_credentials(self):
        lead, webhook = self._lead_and_webhook("1003")
        event = self.env["brokerage.meta.crm.event"].enqueue_for_lead(
            lead,
            "QualifiedLead",
            webhook_event=webhook,
        )
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.text = ""
        response.json.return_value = {"events_received": 1}
        request_path = (
            "odoo.addons.brokerage_crm.models.meta_crm_event.requests.post"
        )
        with patch(request_path, return_value=response) as mocked_post:
            event.with_context(allow_meta_crm_request=True)._send()

        mocked_post.assert_called_once()
        args, kwargs = mocked_post.call_args
        self.assertEqual(
            args[0],
            "https://graph.facebook.com/v26.0/988258467125920/events",
        )
        self.assertEqual(kwargs["params"]["access_token"], "test-capi-token")
        self.assertEqual(event.state, "sent")
        self.assertEqual(event.http_status, 200)
        self.assertNotIn("test-capi-token", event.request_payload)

    def test_lost_meta_lead_queues_negative_event(self):
        lead, _webhook = self._lead_and_webhook("1004")
        lead.with_context(brokerage_workflow_action=True).write({
            "active": False,
            "probability": 0,
        })
        event = self.env["brokerage.meta.crm.event"].search([
            ("lead_id", "=", lead.id),
        ])
        self.assertEqual(event.event_name, "LostLead")
