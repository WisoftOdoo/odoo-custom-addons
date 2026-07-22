from odoo import fields, models


class BrokerageProject(models.Model):
    _name = "brokerage.project"
    _description = "Off-plan Project"
    _order = "developer_id, name"

    name = fields.Char(required=True, index=True)
    code = fields.Char(index=True)
    active = fields.Boolean(default=True)

    developer_id = fields.Many2one(
        comodel_name="brokerage.developer",
        required=True,
        ondelete="restrict",
    )

    location = fields.Char()
    project_type = fields.Selection(
        selection=[
            ("apartment", "Apartment"),
            ("villa", "Villa"),
            ("townhouse", "Townhouse"),
            ("mixed", "Mixed Development"),
            ("other", "Other"),
        ]
    )

    expected_completion_date = fields.Date()
    notes = fields.Text()

    _project_developer_unique = models.Constraint(
        "UNIQUE(name, developer_id)",
        "The project must be unique for the selected developer.",
    )
