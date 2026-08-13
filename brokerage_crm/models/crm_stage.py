from odoo import fields, models


class CrmStage(models.Model):
    _inherit = "crm.stage"

    brokerage_code = fields.Selection(
        selection=[
            ("new", "New Lead"),
            ("assigned", "Assigned"),
            ("contact_attempted", "Contact Attempted"),
            ("contacted", "Contacted"),
            ("not_interested", "Not Interested"),
            ("meeting_scheduled", "Meeting Scheduled"),
            ("meeting_completed", "Meeting Completed"),
            ("forecast", "Forecast"),
            ("hot", "Hot / Booking Expected"),
            ("won", "Closed Won"),
        ],
        string="Brokerage Workflow Code",
        index=True,
        copy=False,
    )
