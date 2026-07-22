from odoo import fields, models


class CrmSlaRule(models.Model):
    _name = "brokerage.crm.sla.rule"
    _description = "CRM SLA Rule"
    _order = "sequence, name, id"

    name = fields.Char(
        required=True,
        index=True,
    )

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    rule_type = fields.Selection(
        selection=[
            ("first_contact", "First Contact"),
            ("lead_update", "Lead Update / Inactivity"),
            ("meeting_follow_up", "Meeting Follow-up"),
        ],
        required=True,
        index=True,
    )

    source_category = fields.Selection(
        selection=[
            ("marketing", "Marketing"),
            ("manual", "Manual"),
            ("referral", "Referral"),
            ("walk_in", "Walk-in"),
            ("bulk", "Bulk Upload"),
            ("developer", "Developer Referral"),
            ("other", "Other"),
        ],
        string="Source Category",
        index=True,
    )

    team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Sales Team",
        ondelete="cascade",
        index=True,
    )

    quality_id = fields.Many2one(
        comodel_name="brokerage.crm.lead.quality",
        string="Lead Quality",
        ondelete="set null",
    )

    duration_minutes = fields.Integer(
        string="Due After (Minutes)",
        required=True,
        default=30,
    )

    reminder_1_minutes = fields.Integer(
        string="Reminder 1 After",
        default=15,
    )

    reminder_2_minutes = fields.Integer(
        string="Reminder 2 After",
        default=20,
    )

    reminder_3_minutes = fields.Integer(
        string="Reminder 3 After",
        default=25,
    )

    escalation_minutes = fields.Integer(
        string="Escalate After",
        default=30,
    )

    reassignment_minutes = fields.Integer(
        string="Reassign After",
        default=45,
    )

    activity_type_id = fields.Many2one(
        comodel_name="mail.activity.type",
        string="Reminder Activity Type",
        required=True,
        ondelete="restrict",
    )

    escalation_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Escalation User",
        ondelete="set null",
    )

    reassignment_team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Reassignment Team",
        ondelete="set null",
    )

    penalty_applicable = fields.Boolean(
        string="Penalty Applicable",
        default=True,
    )

    _duration_positive = models.Constraint(
        "CHECK(duration_minutes > 0)",
        "SLA duration must be greater than zero.",
    )

    _timings_non_negative = models.Constraint(
        """
        CHECK(
            reminder_1_minutes >= 0
            AND reminder_2_minutes >= 0
            AND reminder_3_minutes >= 0
            AND escalation_minutes >= 0
            AND reassignment_minutes >= 0
        )
        """,
        "SLA reminder and escalation timings cannot be negative.",
    )

    _rule_scope_unique = models.Constraint(
        """
        UNIQUE(
            rule_type,
            source_category,
            team_id,
            quality_id
        )
        """,
        "An SLA rule already exists for this type and scope.",
    )
