from markupsafe import Markup

from odoo import fields, models, _
from odoo.exceptions import ValidationError


class CrmContactAttemptWizard(models.TransientModel):
    _name = "brokerage.crm.contact.attempt.wizard"
    _description = "Record Contact Attempt"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        required=True,
        readonly=True,
    )

    attempt_datetime = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
    )

    method = fields.Selection(
        selection=[
            ("call", "Phone Call"),
            ("whatsapp", "WhatsApp"),
            ("email", "Email"),
            ("sms", "SMS"),
            ("other", "Other"),
        ],
        required=True,
        default="call",
    )

    status_id = fields.Many2one(
        comodel_name="brokerage.crm.lead.status",
        required=True,
        domain=(
            "['|', ('is_contact_attempt', '=', True), "
            "('code', '=', 'not_interested')]"
        ),
    )

    remarks = fields.Text()

    next_activity_type_id = fields.Many2one(
        comodel_name="mail.activity.type",
    )

    next_activity_date = fields.Date()

    def action_confirm(self):
        self.ensure_one()

        lead = self.lead_id

        if not lead.user_id:
            raise ValidationError(
                _("Assign a salesperson before recording an attempt.")
            )

        attempt = self.env["brokerage.crm.contact.attempt"].create({
            "lead_id": lead.id,
            "user_id": self.env.user.id,
            "attempt_datetime": self.attempt_datetime,
            "method": self.method,
            "status_id": self.status_id.id,
            "remarks": self.remarks,
            "next_activity_type_id": self.next_activity_type_id.id or False,
            "next_activity_date": self.next_activity_date or False,
        })

        activity = False

        if self.next_activity_type_id and self.next_activity_date:
            activity = self.env["mail.activity"].create({
                "res_model_id": self.env["ir.model"]._get_id("crm.lead"),
                "res_id": lead.id,
                "activity_type_id": self.next_activity_type_id.id,
                "user_id": lead.user_id.id,
                "date_deadline": self.next_activity_date,
                "summary": _("Customer follow-up"),
                "note": self.remarks or _("Follow up with the customer."),
            })

            attempt.activity_id = activity.id

        values = {
            "lead_status_id": self.status_id.id,
            "last_status_update": fields.Datetime.now(),
            "last_meaningful_update": fields.Datetime.now(),
        }

        if self.status_id.is_successful_contact:
            values["first_contact_datetime"] = (
                lead.first_contact_datetime or self.attempt_datetime
            )

        if self.status_id.code == "not_interested":
            reassigned_user = self.env[
                "brokerage.crm.round.robin"
            ].assign_lead_not_interested_once(
                lead,
                reason=_(
                    "One-time cross-team reassignment after the agent "
                    "recorded Not Interested"
                ),
            )
            if not reassigned_user:
                target_stage = lead._find_brokerage_stage(
                    "not_interested"
                )
                if not target_stage:
                    raise ValidationError(_(
                        "Configure a Not Interested CRM stage before using "
                        "this contact result."
                    ))
                values["stage_id"] = target_stage.id
                lead.with_context(
                    brokerage_workflow_action=True,
                ).write(values)
        else:
            target_code = (
                "contacted"
                if self.status_id.is_successful_contact
                else "contact_attempted"
            )
            target_stage = lead._find_brokerage_stage(target_code)
            if target_stage:
                values["stage_id"] = target_stage.id
            lead.with_context(
                brokerage_workflow_action=True,
            ).write(values)

        lead.message_post(
            body=Markup(_(
                "<b>Contact attempt recorded</b><br/>"
                "Method: %(method)s<br/>"
                "Status: %(status)s<br/>"
                "Remarks: %(remarks)s"
            )) % {
                "method": dict(
                    self._fields["method"].selection
                ).get(self.method),
                "status": self.status_id.display_name,
                "remarks": self.remarks or "-",
            },
            subtype_xmlid="mail.mt_note",
        )

        return {"type": "ir.actions.act_window_close"}
