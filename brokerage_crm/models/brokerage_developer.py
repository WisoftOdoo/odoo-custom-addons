from odoo import fields, models


class BrokerageDeveloper(models.Model):
    _name = "brokerage.developer"
    _description = "Property Developer"
    _order = "name"

    name = fields.Char(required=True, index=True)
    code = fields.Char(index=True)
    active = fields.Boolean(default=True)

    rm_name = fields.Char(string="Primary RM Name")
    rm_mobile = fields.Char(string="Primary RM Mobile")
    rm_email = fields.Char(string="Primary RM Email")

    notes = fields.Text()

    project_ids = fields.One2many(
        comodel_name="brokerage.project",
        inverse_name="developer_id",
        string="Projects",
    )

    _developer_name_unique = models.Constraint(
        "UNIQUE(name)",
        "The developer name must be unique.",
    )
