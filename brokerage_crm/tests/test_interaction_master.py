from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestInteractionMasterData(TransactionCase):
    def test_custom_contact_method_is_saved_on_attempt(self):
        method = self.env["brokerage.crm.contact.method"].create({
            "name": "Video Call",
        })
        status = self.env["brokerage.crm.lead.status"].create({
            "name": "Video Call Attempted",
            "code": "video_call_attempted",
            "is_contact_attempt": True,
        })
        lead = self.env["crm.lead"].create({
            "name": "Custom Contact Method Lead",
            "user_id": self.env.user.id,
        })

        attempt = self.env["brokerage.crm.contact.attempt"].create({
            "lead_id": lead.id,
            "user_id": self.env.user.id,
            "method_id": method.id,
            "status_id": status.id,
        })

        self.assertEqual(attempt.method_id, method)
        self.assertEqual(attempt.method, "other")

    def test_custom_meeting_type_controls_location_validation(self):
        no_location_type = self.env["brokerage.crm.meeting.type"].create({
            "name": "Internal Voice Conference",
            "location_mode": "none",
        })
        online_type = self.env["brokerage.crm.meeting.type"].create({
            "name": "Custom Online Conference",
            "location_mode": "online",
        })
        lead = self.env["crm.lead"].create({
            "name": "Custom Meeting Type Lead",
            "user_id": self.env.user.id,
        })
        start = fields.Datetime.now() + timedelta(hours=1)

        meeting = self.env["brokerage.crm.meeting"].create({
            "lead_id": lead.id,
            "name": "Voice Conference",
            "meeting_type_id": no_location_type.id,
            "scheduled_start": start,
            "scheduled_end": start + timedelta(hours=1),
        })
        self.assertEqual(meeting.meeting_type_id, no_location_type)
        self.assertEqual(meeting.meeting_type, "other")

        with self.assertRaises(ValidationError):
            self.env["brokerage.crm.meeting"].create({
                "lead_id": lead.id,
                "name": "Online Conference Without Link",
                "meeting_type_id": online_type.id,
                "scheduled_start": start,
                "scheduled_end": start + timedelta(hours=1),
            })

    def test_operational_wizards_use_configurable_relations(self):
        contact_field = self.env[
            "brokerage.crm.contact.attempt.wizard"
        ]._fields["method_id"]
        meeting_field = self.env[
            "brokerage.crm.schedule.meeting.wizard"
        ]._fields["meeting_type_id"]
        outcome_field = self.env[
            "brokerage.crm.complete.meeting.wizard"
        ]._fields["outcome_id"]

        self.assertEqual(
            contact_field.comodel_name,
            "brokerage.crm.contact.method",
        )
        self.assertEqual(
            meeting_field.comodel_name,
            "brokerage.crm.meeting.type",
        )
        self.assertEqual(
            outcome_field.comodel_name,
            "brokerage.crm.meeting.outcome",
        )

    def test_custom_meeting_outcome_is_saved_on_meeting(self):
        outcome = self.env["brokerage.crm.meeting.outcome"].create({
            "name": "Needs Spouse Approval",
        })
        lead = self.env["crm.lead"].create({
            "name": "Custom Meeting Outcome Lead",
            "user_id": self.env.user.id,
        })
        start = fields.Datetime.now() + timedelta(hours=1)
        meeting = self.env["brokerage.crm.meeting"].create({
            "lead_id": lead.id,
            "name": "Customer Discussion",
            "meeting_type_id": self.env.ref(
                "brokerage_crm.meeting_type_phone"
            ).id,
            "scheduled_start": start,
            "scheduled_end": start + timedelta(hours=1),
            "outcome_id": outcome.id,
        })

        self.assertEqual(meeting.outcome_id, outcome)
        self.assertEqual(meeting.outcome, "other")
