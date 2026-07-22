from odoo import fields, models


class BrokerageCrmLeadQuality(models.Model):
    _name = "brokerage.crm.lead.quality"
    _description = "Brokerage CRM Lead Quality"
    _order = "sequence, name, id"

    name = fields.Char(
        required=True,
        translate=True,
    )

    code = fields.Char(
        required=True,
        index=True,
        copy=False,
    )

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer()

    default_probability = fields.Float(
        string="Default Probability",
        default=0.0,
    )

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The lead quality code must be unique.",
    )

    _probability_range = models.Constraint(
        """
        CHECK(
            default_probability >= 0
            AND default_probability <= 100
        )
        """,
        "Default Probability must be between 0 and 100.",
    )
