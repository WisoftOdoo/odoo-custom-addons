from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestLeadQualityAging(TransactionCase):
    def setUp(self):
        super().setUp()
        parameters = self.env["ir.config_parameter"].sudo()
        parameters.set_param(
            "brokerage_crm.lead_quality_aging_enabled",
            "True",
        )
        parameters.set_param(
            "brokerage_crm.lead_quality_hot_days",
            "30",
        )
        parameters.set_param(
            "brokerage_crm.lead_quality_warm_days",
            "90",
        )
        self.hot = self.env.ref("brokerage_crm.lead_quality_hot")
        self.warm = self.env.ref("brokerage_crm.lead_quality_warm")
        self.cold = self.env.ref("brokerage_crm.lead_quality_cold")

    def _create_lead(self, name, **values):
        return self.env["crm.lead"].create({
            "name": name,
            "type": "opportunity",
            **values,
        })

    def _set_created_datetime(self, lead, created_datetime):
        self.env.cr.execute(
            "UPDATE crm_lead SET create_date = %s WHERE id = %s",
            [fields.Datetime.to_string(created_datetime), lead.id],
        )
        lead.invalidate_recordset(["create_date"])

    def test_new_active_open_lead_is_hot_immediately(self):
        lead = self._create_lead("New Hot Lead")

        self.assertEqual(lead.lead_quality_id, self.hot)

    def test_age_boundaries_assign_hot_warm_and_cold(self):
        evaluation_datetime = fields.Datetime.to_datetime(
            "2026-08-06 12:00:00"
        )
        leads = self.env["crm.lead"]
        expectations = {
            0: self.hot,
            30: self.hot,
            31: self.warm,
            90: self.warm,
            91: self.cold,
        }
        for age_days in expectations:
            lead = self._create_lead("Lead Age %s" % age_days)
            self._set_created_datetime(
                lead,
                evaluation_datetime - timedelta(days=age_days),
            )
            leads |= lead

        updated_count = leads._apply_brokerage_age_based_quality(
            evaluation_datetime=evaluation_datetime,
        )

        self.assertEqual(updated_count, 3)
        for lead, expected_quality in zip(leads, expectations.values()):
            self.assertEqual(lead.lead_quality_id, expected_quality)

    def test_cron_changes_only_quality_and_is_idempotent(self):
        evaluation_datetime = fields.Datetime.now()
        lead = self._create_lead("Old Assigned Lead")
        self._set_created_datetime(
            lead,
            evaluation_datetime - timedelta(days=91, minutes=1),
        )
        original_values = {
            "user_id": lead.user_id,
            "team_id": lead.team_id,
            "stage_id": lead.stage_id,
            "assignment_type": lead.assignment_type,
            "assigned_datetime": lead.assigned_datetime,
            "sla_cycle_active": lead.sla_cycle_active,
        }

        first_count = lead._apply_brokerage_age_based_quality(
            evaluation_datetime=evaluation_datetime,
        )
        second_count = lead._apply_brokerage_age_based_quality(
            evaluation_datetime=evaluation_datetime,
        )

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        self.assertEqual(lead.lead_quality_id, self.cold)
        for field_name, original_value in original_values.items():
            self.assertEqual(lead[field_name], original_value)

    def test_disabled_automation_does_not_classify(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "brokerage_crm.lead_quality_aging_enabled",
            "False",
        )

        lead = self._create_lead("No Automatic Quality")
        updated_count = self.env[
            "crm.lead"
        ]._cron_update_brokerage_lead_quality()

        self.assertFalse(lead.lead_quality_id)
        self.assertEqual(updated_count, 0)

    def test_final_records_are_not_changed(self):
        not_interested_stage = self.env["crm.stage"].create({
            "name": "Aging Final Not Interested",
            "brokerage_code": "not_interested",
        })
        invalid_status = self.env.ref(
            "brokerage_crm.lead_status_invalid_number"
        )
        won_stage = self.env["crm.stage"].create({
            "name": "Aging Closed Won",
            "is_won": True,
        })
        final_leads = self.env["crm.lead"]
        for name, values in [
            (
                "Archived Lead",
                {"active": False, "lead_quality_id": self.warm.id},
            ),
            (
                "Not Interested Lead",
                {
                    "stage_id": not_interested_stage.id,
                    "lead_quality_id": self.warm.id,
                },
            ),
            (
                "Invalid Lead",
                {
                    "lead_status_id": invalid_status.id,
                    "lead_quality_id": self.warm.id,
                },
            ),
            (
                "Won Lead",
                {
                    "stage_id": won_stage.id,
                    "lead_quality_id": self.warm.id,
                },
            ),
        ]:
            final_leads |= self._create_lead(name, **values)

        updated_count = final_leads._apply_brokerage_age_based_quality()

        self.assertEqual(updated_count, 0)
        self.assertTrue(all(
            lead.lead_quality_id == self.warm
            for lead in final_leads
        ))

    def test_settings_store_thresholds_and_validate_order(self):
        settings = self.env["res.config.settings"].create({
            "brokerage_lead_quality_aging_enabled": True,
            "brokerage_lead_quality_hot_days": 45,
            "brokerage_lead_quality_warm_days": 120,
        })
        settings.set_values()
        loaded = self.env["res.config.settings"].get_values()

        self.assertTrue(loaded["brokerage_lead_quality_aging_enabled"])
        self.assertEqual(loaded["brokerage_lead_quality_hot_days"], 45)
        self.assertEqual(loaded["brokerage_lead_quality_warm_days"], 120)

        invalid_settings = self.env["res.config.settings"].create({
            "brokerage_lead_quality_aging_enabled": True,
            "brokerage_lead_quality_hot_days": 90,
            "brokerage_lead_quality_warm_days": 30,
        })
        with self.assertRaises(ValidationError):
            invalid_settings.set_values()
