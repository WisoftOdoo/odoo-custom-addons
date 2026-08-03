import json
from unittest.mock import Mock, patch

from odoo.tests import HttpCase, get_db_name, tagged
from odoo.tests.common import TransactionCase


class TestBrokerageTelephony(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["brokerage.crm.round.robin"].search([]).write({
            "active": False,
        })
        cls.env["brokerage.crm.sla.rule"].search([]).write({
            "active": False,
        })
        agent_group = cls.env.ref(
            "brokerage_crm.group_brokerage_crm_user"
        )
        cls.agent = cls.env["res.users"].create({
            "name": "Telephony Agent",
            "login": "telephony.agent@test.invalid",
            "group_ids": [(6, 0, [agent_group.id])],
            "telephony_extension": "123",
            "telephony_device_id": "mobile-device-1",
        })
        cls.other_agent = cls.env["res.users"].create({
            "name": "Other Telephony Agent",
            "login": "telephony.other@test.invalid",
            "group_ids": [(6, 0, [agent_group.id])],
            "telephony_extension": "124",
        })
        cls.team = cls.env["crm.team"].create({
            "name": "Telephony Team",
        })
        cls.stage = cls.env["crm.stage"].create({
            "name": "Telephony Assigned",
            "brokerage_code": "assigned",
            "team_ids": [(6, 0, [cls.team.id])],
        })
        cls.generic_provider = cls.env[
            "brokerage.telephony.provider"
        ].create({
            "name": "Generic PBX Bridge",
            "code": "generic-test",
            "company_id": cls.env.company.id,
            "adapter_type": "generic_http",
            "outbound_url": "https://pbx-bridge.test/calls",
            "outbound_auth_type": "bearer",
            "outbound_token": "test-outbound-token",
            "webhook_token": "test-webhook-token-at-least-24-characters",
        })
        cls.env.company.brokerage_telephony_provider_id = (
            cls.generic_provider
        )
        cls.lead = cls.env["crm.lead"].create({
            "name": "Telephony Lead",
            "type": "opportunity",
            "phone": "+971501234567",
            "team_id": cls.team.id,
            "user_id": cls.agent.id,
            "stage_id": cls.stage.id,
        })

    @staticmethod
    def _response(data, status=200):
        response = Mock(
            ok=200 <= status < 300,
            status_code=status,
            text="provider response",
        )
        response.json.return_value = data
        return response

    def _create_generic_call(self):
        response = self._response({
            "external_call_id": "PBX-CALL-001",
            "status": "ringing",
        })
        with patch(
            "odoo.addons.brokerage_crm.models.telephony_provider."
            "requests.request",
            return_value=response,
        ) as request_mock:
            call = self.env[
                "brokerage.telephony.call"
            ].create_outbound_for_lead(
                self.lead,
                self.agent,
                self.generic_provider.with_context(
                    allow_telephony_request=True
                ),
            )
        return call, request_mock

    def test_generic_click_to_call_does_not_change_crm_workflow(self):
        original_stage = self.lead.stage_id

        call, request_mock = self._create_generic_call()

        self.assertEqual(call.state, "ringing")
        self.assertEqual(call.external_call_id, "PBX-CALL-001")
        self.assertEqual(call.lead_id, self.lead)
        self.assertEqual(call.user_id, self.agent)
        self.assertEqual(self.lead.stage_id, original_stage)
        self.assertFalse(self.lead.contact_attempt_ids)
        request = request_mock.call_args
        self.assertEqual(request.args[:2], (
            "POST",
            "https://pbx-bridge.test/calls",
        ))
        self.assertEqual(
            request.kwargs["headers"]["Authorization"],
            "Bearer test-outbound-token",
        )
        payload = request.kwargs["json"]
        self.assertEqual(payload["request_id"], call.request_uid)
        self.assertEqual(payload["agent"]["extension"], "123")
        self.assertEqual(payload["agent"]["device_id"], "mobile-device-1")
        self.assertEqual(payload["customer"]["odoo_lead_id"], self.lead.id)
        self.assertEqual(payload["customer"]["phone"], "+971501234567")

    def test_completed_event_is_idempotent_and_tracks_exact_duration(self):
        call, _request_mock = self._create_generic_call()
        payload = {
            "event_id": "EVENT-COMPLETED-001",
            "request_id": call.request_uid,
            "external_call_id": "PBX-CALL-001",
            "status": "completed",
            "started_at": "2026-07-24T08:00:00Z",
            "answered_at": "2026-07-24T08:00:05Z",
            "ended_at": "2026-07-24T08:00:25Z",
            "termination_reason": "remote_hangup",
        }

        event, duplicate = self.env[
            "brokerage.telephony.event"
        ].process_payload(self.generic_provider, payload)
        second_event, second_duplicate = self.env[
            "brokerage.telephony.event"
        ].process_payload(self.generic_provider, payload)

        call.invalidate_recordset()
        self.assertFalse(duplicate)
        self.assertTrue(second_duplicate)
        self.assertEqual(second_event, event)
        self.assertEqual(call.state, "completed")
        self.assertEqual(call.ring_duration_seconds, 5)
        self.assertEqual(call.talk_duration_seconds, 20)
        self.assertEqual(call.total_duration_seconds, 25)
        self.assertEqual(call.termination_reason, "remote_hangup")
        self.assertEqual(len(call.event_ids), 1)
        self.assertFalse(self.lead.contact_attempt_ids)
        self.assertEqual(self.lead.stage_id, self.stage)

    def test_agents_only_see_their_own_call_history(self):
        own_call, _request_mock = self._create_generic_call()
        other_lead = self.env["crm.lead"].create({
            "name": "Other Agent Telephony Lead",
            "type": "opportunity",
            "phone": "+971509999999",
            "team_id": self.team.id,
            "user_id": self.other_agent.id,
            "stage_id": self.stage.id,
        })
        other_call = self.env["brokerage.telephony.call"].sudo().create({
            "provider_id": self.generic_provider.id,
            "lead_id": other_lead.id,
            "user_id": self.other_agent.id,
            "direction": "outgoing",
            "to_number": other_lead.phone,
            "agent_extension": self.other_agent.telephony_extension,
        })

        visible = self.env[
            "brokerage.telephony.call"
        ].with_user(self.agent).search([
            ("id", "in", [own_call.id, other_call.id]),
        ])

        self.assertEqual(visible, own_call)

    def test_three_cx_is_an_adapter_behind_the_same_call_model(self):
        provider = self.env[
            "brokerage.telephony.provider"
        ].create({
            "name": "3CX Test",
            "code": "three-cx-test",
            "company_id": self.env.company.id,
            "adapter_type": "three_cx",
            "base_url": "https://pbx.3cx.test",
            "client_id": "odoo-route-point",
            "client_secret": "three-cx-api-key",
            "webhook_token": "three-cx-webhook-token-24-characters",
        })
        call = self.env["brokerage.telephony.call"].sudo().create({
            "provider_id": provider.id,
            "lead_id": self.lead.id,
            "user_id": self.agent.id,
            "direction": "outgoing",
            "to_number": self.lead.phone,
            "agent_extension": "123",
            "agent_device_id": "mobile-device-1",
        })
        token_response = self._response({
            "access_token": "three-cx-access-token",
            "expires_in": 3600,
        })
        call_response = self._response({
            "finalstatus": "Accepted",
            "result": {
                "status": "Ringing",
                "callid": 4567,
            },
        }, status=202)

        with patch(
            "odoo.addons.brokerage_crm.models.telephony_provider."
            "requests.request",
            side_effect=[token_response, call_response],
        ) as request_mock:
            result = provider.with_context(
                allow_telephony_request=True
            ).initiate_call(call)

        self.assertEqual(result["external_call_id"], "4567")
        self.assertEqual(result["state"], "ringing")
        token_request, call_request = request_mock.call_args_list
        self.assertEqual(
            token_request.args[1],
            "https://pbx.3cx.test/connect/token",
        )
        self.assertEqual(
            call_request.args[1],
            "https://pbx.3cx.test/callcontrol/123/devices/"
            "mobile-device-1/makecall",
        )
        self.assertEqual(
            call_request.kwargs["headers"]["Authorization"],
            "Bearer three-cx-access-token",
        )
        self.assertEqual(
            call_request.kwargs["json"]["destination"],
            "+971501234567",
        )
        self.assertEqual(
            call_request.kwargs["json"]["attacheddata"][
                "odoo_request_id"
            ],
            call.request_uid,
        )


@tagged("post_install", "-at_install")
class TestBrokerageTelephonyApi(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["brokerage.crm.round.robin"].search([]).write({
            "active": False,
        })
        cls.env["brokerage.crm.sla.rule"].search([]).write({
            "active": False,
        })
        cls.agent = cls.env["res.users"].create({
            "name": "Telephony API Agent",
            "login": "telephony.api.agent@test.invalid",
            "telephony_extension": "220",
        })
        cls.provider = cls.env[
            "brokerage.telephony.provider"
        ].create({
            "name": "Telephony API Provider",
            "code": "telephony-api-test",
            "company_id": cls.env.company.id,
            "adapter_type": "generic_http",
            "outbound_url": "https://pbx-bridge.test/calls",
            "outbound_auth_type": "none",
            "webhook_token": "telephony-api-webhook-token-24-characters",
        })
        cls.call = cls.env["brokerage.telephony.call"].sudo().create({
            "provider_id": cls.provider.id,
            "external_call_id": "API-PBX-CALL-001",
            "user_id": cls.agent.id,
            "direction": "outgoing",
            "to_number": "+971501112222",
            "agent_extension": "220",
            "state": "ringing",
        })

    def _post_event(self, token, event_id="API-EVENT-001"):
        return self.url_open(
            "/brokerage/api/v1/telephony/events/telephony-api-test",
            data=json.dumps({
                "event_id": event_id,
                "external_call_id": "API-PBX-CALL-001",
                "status": "completed",
                "started_at": "2026-07-24T09:00:00Z",
                "answered_at": "2026-07-24T09:00:04Z",
                "ended_at": "2026-07-24T09:00:34Z",
            }),
            headers={
                "Content-Type": "application/json",
                "X-Odoo-Database": get_db_name(),
                "X-Brokerage-Telephony-Token": token,
            },
        )

    def test_webhook_auth_duration_and_idempotency(self):
        unauthorized = self._post_event("wrong-token", "UNAUTHORIZED")
        self.assertEqual(unauthorized.status_code, 401)
        self.assertFalse(unauthorized.json()["success"])

        response = self._post_event(self.provider.webhook_token)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(result["success"])
        self.assertFalse(result["duplicate"])
        self.assertEqual(result["call"]["state"], "completed")
        self.assertEqual(result["call"]["ring_duration_seconds"], 4)
        self.assertEqual(result["call"]["talk_duration_seconds"], 30)
        self.assertEqual(result["call"]["total_duration_seconds"], 34)

        duplicate = self._post_event(self.provider.webhook_token)
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertTrue(duplicate.json()["duplicate"])
        self.assertEqual(
            self.env["brokerage.telephony.event"].search_count([
                ("provider_id", "=", self.provider.id),
                ("event_id", "=", "API-EVENT-001"),
            ]),
            1,
        )
