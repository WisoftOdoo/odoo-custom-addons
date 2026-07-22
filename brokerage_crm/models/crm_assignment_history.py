from odoo import fields, models


class BrokerageCrmAssignmentHistory(models.Model):
    _name = "brokerage.crm.assignment.history"
    _description = "CRM Assignment History"
    _order = "assigned_datetime desc, id desc"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        string="Lead / Opportunity",
        required=True,
        ondelete="cascade",
        index=True,
    )

    source_id = fields.Many2one(
        comodel_name="utm.source",
        string="Lead Source",
        ondelete="set null",
        index=True,
    )

    previous_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Previous Salesperson",
        ondelete="set null",
    )

    new_user_id = fields.Many2one(
        comodel_name="res.users",
        string="New Salesperson",
        required=True,
        ondelete="restrict",
    )

    previous_team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Previous Sales Team",
        ondelete="set null",
    )

    new_team_id = fields.Many2one(
        comodel_name="crm.team",
        string="New Sales Team",
        required=True,
        ondelete="restrict",
    )

    assignment_type = fields.Selection(
        selection=[
            ("round_robin", "Round Robin"),
            ("manual", "Manual"),
            ("referral", "Referral"),
            ("walk_in", "Walk-in"),
            ("bulk", "Bulk Distribution"),
            ("reassignment", "Reassignment"),
            (
                "not_interested_reassignment",
                "Not Interested Reassignment",
            ),
        ],
        required=True,
        index=True,
    )

    assigned_datetime = fields.Datetime(
        string="Assigned Date/Time",
        required=True,
        default=fields.Datetime.now,
        index=True,
    )

    assigned_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Assigned By",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
    )

    reason = fields.Text()

    round_robin_id = fields.Many2one(
        comodel_name="brokerage.crm.round.robin",
        string="Round Robin Configuration",
        ondelete="set null",
    )

    round_robin_position = fields.Integer(
        string="Round Robin Position",
    )
