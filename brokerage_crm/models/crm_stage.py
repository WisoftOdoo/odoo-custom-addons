from odoo import api, fields, models


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
            ("kyc", "KYC in Progress"),
            ("booking", "Booking / Documentation"),
            ("won", "Closed Won"),
        ],
        string="Brokerage Workflow Code",
        index=True,
        copy=False,
    )

    @api.model
    def _brokerage_place_kyc_before_booking(self):
        """Keep the approved KYC stage immediately before Booking.

        Existing customer stages are updated in place so their identifiers,
        team restrictions and lead links remain untouched.
        """
        kyc_stage = self.env.ref(
            "brokerage_crm.crm_stage_kyc_in_progress",
            raise_if_not_found=False,
        )
        if not kyc_stage:
            return True

        booking_stage = self.search([
            ("brokerage_code", "=", "booking"),
        ], order="sequence, id", limit=1)
        won_stage = self.search([
            ("brokerage_code", "=", "won"),
        ], order="sequence, id", limit=1)

        if booking_stage and booking_stage.sequence <= kyc_stage.sequence:
            booking_stage.sequence = kyc_stage.sequence + 1
        if (
            won_stage
            and booking_stage
            and won_stage.sequence <= booking_stage.sequence
        ):
            won_stage.sequence = booking_stage.sequence + 1
        return True
