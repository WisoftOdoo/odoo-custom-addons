from odoo import fields, models


class CrmSlaLog(models.Model):
    _name = "brokerage.crm.sla.log"
    _description = "CRM SLA Log"
    _order = "deadline desc"

    lead_id = fields.Many2one("crm.lead", required=True, ondelete="cascade", index=True)
    rule_id = fields.Many2one("brokerage.crm.sla.rule", required=True, ondelete="restrict")
    deadline = fields.Datetime(required=True, index=True)
    assignment_datetime = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    state = fields.Selection([("pending", "Pending"), ("met", "Met"), ("breached", "Breached")], default="pending", required=True)
    completed_at = fields.Datetime()
    event_type = fields.Selection(
        [
            ("reminder_1", "Reminder 1"),
            ("reminder_2", "Reminder 2"),
            ("reminder_3", "Reminder 3"),
            ("escalation", "Escalation"),
            ("reassignment", "Reassignment"),
        ],
        required=True,
        default="reminder_1",
        index=True,
    )

    _lead_rule_event_unique = models.Constraint(
        "UNIQUE(lead_id, rule_id, event_type, assignment_datetime)",
        "This SLA event has already been processed for this assignment.",
    )
