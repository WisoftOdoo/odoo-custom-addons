from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestCustomerRequirementOptions(TransactionCase):
    def test_six_lead_fields_use_configurable_master_model(self):
        lead_fields = self.env["crm.lead"]._fields
        for field_name in (
            "requirement_type_id",
            "property_category_id",
            "bedroom_count_id",
            "purchase_timeline_id",
            "buyer_type_id",
            "purchase_mode_id",
        ):
            self.assertEqual(
                lead_fields[field_name].comodel_name,
                "brokerage.crm.customer.requirement.option",
            )

    def test_custom_options_are_saved_on_customer_requirement(self):
        option_model = self.env[
            "brokerage.crm.customer.requirement.option"
        ]
        values = {}
        mapping = {
            "requirement_type_id": "requirement_type",
            "property_category_id": "property_category",
            "bedroom_count_id": "bedroom_count",
            "purchase_timeline_id": "purchase_timeline",
            "buyer_type_id": "buyer_type",
            "purchase_mode_id": "purchase_mode",
        }
        for field_name, option_type in mapping.items():
            option = option_model.with_context(
                default_option_type=option_type,
            ).create({"name": "Custom %s" % option_type})
            values[field_name] = option.id
            self.assertEqual(option.option_type, option_type)
            self.assertTrue(option.code.startswith("custom_"))

        lead = self.env["crm.lead"].create({
            "name": "Configurable Customer Requirement",
            **values,
        })

        for field_name, option_id in values.items():
            self.assertEqual(lead[field_name].id, option_id)

    def test_builtin_option_keeps_legacy_field_compatible(self):
        lead = self.env["crm.lead"].create({
            "name": "Compatible Requirement",
            "property_category_id": self.env.ref(
                "brokerage_crm.property_category_villa"
            ).id,
            "purchase_mode_id": self.env.ref(
                "brokerage_crm.purchase_mode_finance"
            ).id,
        })

        self.assertEqual(lead.property_category, "villa")
        self.assertEqual(lead.purchase_mode, "finance")

    def test_wrong_option_type_is_rejected(self):
        lead = self.env["crm.lead"].create({"name": "Wrong Option Type"})
        property_option = self.env.ref(
            "brokerage_crm.property_category_apartment"
        )

        with self.assertRaises(ValidationError):
            lead.write({"purchase_mode_id": property_option.id})

    def test_upgrade_migration_maps_existing_selection_values(self):
        lead = self.env["crm.lead"].create({"name": "Legacy Requirement"})
        self.env.cr.execute(
            """
                UPDATE crm_lead
                   SET requirement_type = %s,
                       requirement_type_id = NULL
                 WHERE id = %s
            """,
            ["investment", lead.id],
        )
        lead.invalidate_recordset([
            "requirement_type",
            "requirement_type_id",
        ])

        self.env[
            "crm.lead"
        ]._brokerage_migrate_customer_requirement_options()

        self.assertEqual(
            lead.requirement_type_id,
            self.env.ref("brokerage_crm.requirement_type_investment"),
        )

    def test_legacy_other_is_retained_but_not_offered(self):
        legacy_other = self.env.ref(
            "brokerage_crm.property_category_other_legacy"
        )

        self.assertFalse(legacy_other.active)
        self.assertNotIn(
            legacy_other,
            self.env[
                "brokerage.crm.customer.requirement.option"
            ].search([("option_type", "=", "property_category")]),
        )
