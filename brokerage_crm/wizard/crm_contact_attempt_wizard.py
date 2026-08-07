from markupsafe import Markup

from odoo import api, fields, models, _
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

    method_id = fields.Many2one(
        comodel_name="brokerage.crm.contact.method",
        string="Method",
        required=True,
        default=lambda self: self.env.ref(
            "brokerage_crm.contact_method_phone_call",
            raise_if_not_found=False,
        ),
        ondelete="restrict",
    )

    method = fields.Selection(
        selection=[
            ("call", "Phone Call"),
            ("whatsapp", "WhatsApp"),
            ("email", "Email"),
            ("sms", "SMS"),
            ("other", "Other"),
        ],
        string="Legacy Method",
        help="Compatibility input for older integrations.",
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

    next_activity_date = fields.Datetime(
        string="Next Activity Date & Time",
        help=(
            "Select the exact date and time for the customer follow-up and "
            "its Odoo reminder."
        ),
    )
    @api.model_create_multi
    def create(self, vals_list):
        method_model = self.env["brokerage.crm.contact.method"]
        for vals in vals_list:
            if vals.get("method") and not vals.get("method_id"):
                method = method_model.search([
                    ("code", "=", vals["method"]),
                ], limit=1)
                if method:
                    vals["method_id"] = method.id
        return super().create(vals_list)

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
            "method_id": self.method_id.id,
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
                "brokerage_reminder_datetime": self.next_activity_date,
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

        reassigned_user = False
        if self.status_id.code == "not_interested":
            # A solo campaign never participates in the independent Not
            # Interested queue. It remains in the final bucket instead.
            if not lead.team_id.brokerage_solo_campaign:
                reassigned_user = self.env[
                    "brokerage.crm.round.robin"
                ].assign_lead_not_interested_once(
                    lead,
                    reason=_(
                        "One-time reassignment after the agent "
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
                lead._validate_brokerage_stage_move(target_stage)
                values["stage_id"] = target_stage.id
            lead.with_context(
                brokerage_workflow_action=True,
            ).write(values)

        lead.sudo().message_post(
            body=Markup(_(
                "<b>Contact attempt recorded</b><br/>"
                "Method: %(method)s<br/>"
                "Status: %(status)s<br/>"
                "Remarks: %(remarks)s"
            )) % {
                "method": self.method_id.display_name,
                "status": self.status_id.display_name,
                "remarks": self.remarks or "-",
            },
            subtype_xmlid="mail.mt_note",
            author_id=self.env.user.partner_id.id,
        )

        if reassigned_user:
            # The former salesperson loses read access as soon as the lead is
            # handed to another team. Returning "close" makes the web client
            # refresh the now-inaccessible lead form and display an Access
            # Error even though the reassignment succeeded. Replace the form
            # with the user's pipeline instead.
            action = self.env["ir.actions.actions"]._for_xml_id(
                "crm.crm_lead_action_pipeline"
            )
            action["target"] = "current"
            return action

        return {"type": "ir.actions.act_window_close"}
