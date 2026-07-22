from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestLeadValidation(TransactionCase):
    def test_agent_can_create_developer_and_project(self):
        agent = self.env["res.users"].create({
            "name": "Master Data Agent",
            "login": "master.data.agent@test.invalid",
            "group_ids": [(6, 0, [
                self.env.ref(
                    "brokerage_crm.group_brokerage_crm_user"
                ).id,
            ])],
        })
        developer = self.env["brokerage.developer"].with_user(agent).create({
            "name": "Agent-created Developer",
        })
        project = self.env["brokerage.project"].with_user(agent).create({
            "name": "Agent-created Project",
            "developer_id": developer.id,
        })
        self.assertEqual(project.developer_id, developer)

    def test_project_must_match_developer(self):
        developer_a = self.env["brokerage.developer"].create({"name": "A"})
        developer_b = self.env["brokerage.developer"].create({"name": "B"})
        project = self.env["brokerage.project"].create({"name": "A Project", "developer_id": developer_a.id})
        with self.assertRaises(ValidationError):
            self.env["crm.lead"].create({
                "name": "Lead", "preferred_developer_id": developer_b.id,
                "preferred_project_id": project.id,
            })

    def test_contact_stage_requires_attempt_log(self):
        stage = self.env["crm.stage"].create({
            "name": "Contact Attempted Test",
            "brokerage_code": "contact_attempted",
        })
        lead = self.env["crm.lead"].create({"name": "Lead"})
        with self.assertRaises(ValidationError):
            lead.write({"stage_id": stage.id})
