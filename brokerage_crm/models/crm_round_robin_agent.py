from odoo import fields, models


class CrmRoundRobinAgent(models.Model):
    _name = "brokerage.crm.round.robin.agent"
    _description = "CRM Round Robin Agent Rotation"
    _order = "sequence, user_id, id"
    _rec_name = "user_id"

    round_robin_id = fields.Many2one(
        comodel_name="brokerage.crm.round.robin",
        string="Round Robin Configuration",
        required=True,
        ondelete="cascade",
        index=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Salesperson",
        required=True,
        ondelete="restrict",
        index=True,
    )
    sequence = fields.Integer(
        default=10,
        required=True,
        index=True,
        help="Lower values receive leads earlier in the rotation.",
    )
    available_for_crm_assignment = fields.Boolean(
        related="user_id.available_for_crm_assignment",
        string="Available",
        readonly=True,
    )
    user_active = fields.Boolean(
        related="user_id.active",
        string="Active User",
        readonly=True,
    )

    _configuration_user_unique = models.Constraint(
        "UNIQUE(round_robin_id, user_id)",
        "A salesperson can appear only once in a Round Robin rotation.",
    )
    _sequence_non_negative = models.Constraint(
        "CHECK(sequence >= 0)",
        "Agent rotation sequence cannot be negative.",
    )
