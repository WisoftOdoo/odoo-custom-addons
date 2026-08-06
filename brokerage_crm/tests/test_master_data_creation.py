from odoo.tests.common import TransactionCase


class TestMasterDataCreation(TransactionCase):
    def test_agent_can_create_business_dropdown_values(self):
        agent = self.env["res.users"].create({
            "name": "Master Data Creation Agent",
            "login": "master.data.creation.agent@test.invalid",
            "group_ids": [(6, 0, [
                self.env.ref(
                    "brokerage_crm.group_brokerage_crm_user"
                ).id,
            ])],
        })

        developer = self.env["brokerage.developer"].with_user(agent).create({
            "name": "Agent Created Developer",
        })
        project = self.env["brokerage.project"].with_user(agent).create({
            "name": "Agent Created Project",
            "developer_id": developer.id,
        })
        status = (
            self.env["brokerage.crm.lead.status"]
            .with_user(agent)
            .create({
                "name": "Agent Created Status",
                "code": "agent_created_status",
            })
        )
        quality = (
            self.env["brokerage.crm.lead.quality"]
            .with_user(agent)
            .create({
                "name": "Agent Created Quality",
                "code": "agent_created_quality",
            })
        )
        source = self.env["utm.source"].with_user(agent).create({
            "name": "Agent Created Source",
        })
        contact_method = (
            self.env["brokerage.crm.contact.method"]
            .with_user(agent)
            .create({"name": "Agent Created Contact Method"})
        )
        meeting_type = (
            self.env["brokerage.crm.meeting.type"]
            .with_user(agent)
            .create({
                "name": "Agent Created Meeting Type",
                "location_mode": "online",
            })
        )
        meeting_outcome = (
            self.env["brokerage.crm.meeting.outcome"]
            .with_user(agent)
            .create({"name": "Agent Created Meeting Outcome"})
        )
        requirement_options = self.env[
            "brokerage.crm.customer.requirement.option"
        ].with_user(agent).create([
            {
                "name": "Agent Requirement Type",
                "option_type": "requirement_type",
            },
            {
                "name": "Agent Property Category",
                "option_type": "property_category",
            },
            {
                "name": "Agent Bedroom Count",
                "option_type": "bedroom_count",
            },
            {
                "name": "Agent Purchase Timeline",
                "option_type": "purchase_timeline",
            },
            {
                "name": "Agent Buyer Type",
                "option_type": "buyer_type",
            },
            {
                "name": "Agent Purchase Mode",
                "option_type": "purchase_mode",
            },
        ])

        self.assertTrue(developer.exists())
        self.assertTrue(project.exists())
        self.assertTrue(status.exists())
        self.assertTrue(quality.exists())
        self.assertTrue(source.exists())
        self.assertTrue(contact_method.exists())
        self.assertTrue(meeting_type.exists())
        self.assertTrue(meeting_outcome.exists())
        self.assertEqual(len(requirement_options), 6)
        self.assertTrue(all(requirement_options.mapped("code")))
        self.assertEqual(
            contact_method.code,
            "agent_created_contact_method",
        )
        self.assertEqual(
            meeting_type.code,
            "agent_created_meeting_type",
        )
        self.assertEqual(
            meeting_outcome.code,
            "agent_created_meeting_outcome",
        )
