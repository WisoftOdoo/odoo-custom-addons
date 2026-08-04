import hashlib
import logging
import re

from markupsafe import Markup
from odoo import api, fields, models, tools, _
from odoo.addons.phone_validation.tools import phone_validation
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = "crm.lead"

    brokerage_deduplication_key = fields.Char(
        string="API Duplicate Key",
        compute="_compute_brokerage_deduplication_key",
        store=True,
        copy=False,
        index=True,
        readonly=True,
    )

    @api.model
    def _brokerage_build_deduplication_key(
        self,
        customer_name,
        email,
        phone,
        company=None,
    ):
        raw_email = str(email or "").strip()
        normalized_email = (
            tools.email_normalize(raw_email)
            or raw_email.casefold()
        )
        company = company or self.env.company
        country = company.country_id
        formatted_phone = phone_validation.phone_format(
            str(phone or "").strip(),
            country.code if country else False,
            country.phone_code if country else False,
            force_format="E164",
            raise_exception=False,
        )
        normalized_phone = re.sub(r"\D", "", formatted_phone or "")
        if normalized_phone.startswith("00"):
            normalized_phone = normalized_phone[2:]
        if not all((normalized_email, normalized_phone)):
            return False
        # Email + phone is the stable customer identity. The API still
        # requires a customer name, but a spelling/name change must not create
        # a second CRM lead for the same email and phone combination.
        identity = "\x1f".join((normalized_email, normalized_phone))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @api.depends(
        "email_from",
        "phone",
        "company_id",
        "company_id.country_id",
    )
    def _compute_brokerage_deduplication_key(self):
        for lead in self:
            lead.brokerage_deduplication_key = (
                lead._brokerage_build_deduplication_key(
                    lead.contact_name,
                    lead.email_from,
                    lead.phone,
                    lead.company_id,
                )
            )

    repeat_enquiry_count = fields.Integer(
        string="Repeat Enquiries",
        readonly=True,
        copy=False,
        default=0,
    )
    last_repeat_enquiry_datetime = fields.Datetime(
        string="Last Repeat Enquiry",
        readonly=True,
        copy=False,
    )
    last_repeat_enquiry_source_id = fields.Many2one(
        comodel_name="utm.source",
        string="Last Repeat Enquiry Source",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    last_repeat_enquiry_campaign_id = fields.Many2one(
        comodel_name="utm.campaign",
        string="Last Repeat Enquiry Campaign",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    last_repeat_enquiry_medium_id = fields.Many2one(
        comodel_name="utm.medium",
        string="Last Repeat Enquiry Medium",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    '''Source and classification fields'''
    lead_status_id = fields.Many2one(
        comodel_name="brokerage.crm.lead.status",
        string="Lead Status",
        tracking=True,
        index=True,
    )

    lead_quality_id = fields.Many2one(
        comodel_name="brokerage.crm.lead.quality",
        string="Lead Quality",
        tracking=True,
        index=True,
    )

    source_category = fields.Selection(
        related="source_id.brokerage_category",
        string="Source Category",
        store=True,
        index=True,
    )

    '''Assignment fields'''
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
            ("solo_campaign", "Solo Campaign"),
        ],
        tracking=True,
        index=True,
    )

    assigned_datetime = fields.Datetime(
        string="Assigned Date/Time",
        tracking=True,
        readonly=True,
        copy=False,
    )

    sla_cycle_active = fields.Boolean(
        string="SLA Cycle Active",
        default=False,
        readonly=True,
        copy=False,
        index=True,
        help=(
            "Technical flag activated only by a real assignment cycle. "
            "Moving a progressed lead back to Assigned does not reactivate "
            "an old SLA timer."
        ),
    )

    can_recover_last_assignment = fields.Boolean(
        string="Can Recover Last Assignment",
        compute="_compute_can_recover_last_assignment",
    )

    first_contact_datetime = fields.Datetime(
        string="First Contact Date/Time",
        tracking=True,
        readonly=True,
        copy=False,
    )

    last_status_update = fields.Datetime(
        string="Last Status Update",
        readonly=True,
        copy=False,
    )

    last_meaningful_update = fields.Datetime(
        string="Last Meaningful Update",
        readonly=True,
        copy=False,
    )

    not_interested_reassignment_done = fields.Boolean(
        string="Not Interested Reassignment Completed",
        readonly=True,
        copy=False,
        default=False,
        index=True,
    )

    contact_attempt_count = fields.Integer(
        compute="_compute_brokerage_counts",
    )

    meeting_count = fields.Integer(
        compute="_compute_brokerage_counts",
    )

    assignment_history_count = fields.Integer(
        compute="_compute_brokerage_counts",
    )

    brokerage_next_action = fields.Selection(
        selection=[
            ("contact_attempt", "Record Contact Attempt"),
            ("schedule_meeting", "Schedule Meeting"),
            ("complete_meeting", "Complete Meeting"),
        ],
        compute="_compute_brokerage_next_action",
        string="Next Workflow Action",
    )

    # Retained as a non-stored compatibility field so databases upgrading
    # from 19.0.1.14.3 can validate the previous inherited view before that
    # view is replaced later in the same module upgrade. It is intentionally
    # absent from the final form view.
    brokerage_next_step_hint = fields.Char(
        string="Next Workflow Step",
        compute="_compute_brokerage_next_step_hint",
    )

    '''Customer qualification fields'''
    requirement_type = fields.Selection(
        selection=[
            ("investment", "Investment"),
            ("end_use", "End Use"),
            ("both", "Investment and End Use"),
        ],
        tracking=True,
    )

    company_currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="company_id.currency_id",
        string="Company Currency",
        readonly=True,
    )

    budget_from = fields.Monetary(
        currency_field="company_currency_id",
        tracking=True,
    )

    budget_to = fields.Monetary(
        currency_field="company_currency_id",
        tracking=True,
    )

    preferred_location = fields.Char(tracking=True)

    property_category = fields.Selection(
        selection=[
            ("apartment", "Apartment"),
            ("villa", "Villa"),
            ("townhouse", "Townhouse"),
            ("penthouse", "Penthouse"),
            ("plot", "Plot"),
            ("commercial", "Commercial"),
            ("other", "Other"),
        ],
        tracking=True,
    )

    unit_preference = fields.Char(tracking=True)

    bedroom_count = fields.Selection(
        selection=[
            ("studio", "Studio"),
            ("1", "1 Bedroom"),
            ("2", "2 Bedrooms"),
            ("3", "3 Bedrooms"),
            ("4", "4 Bedrooms"),
            ("5_plus", "5+ Bedrooms"),
        ],
        tracking=True,
    )

    purchase_timeline = fields.Selection(
        selection=[
            ("immediate", "Immediate"),
            ("one_month", "Within 1 Month"),
            ("three_months", "Within 3 Months"),
            ("six_months", "Within 6 Months"),
            ("later", "More Than 6 Months"),
            ("unknown", "Not Confirmed"),
        ],
        tracking=True,
    )

    buyer_type = fields.Selection(
        selection=[
            ("resident", "UAE Resident"),
            ("non_resident", "Non-resident"),
            ("investor", "Investor"),
            ("end_user", "End User"),
        ],
        tracking=True,
    )

    purchase_mode = fields.Selection(
        selection=[
            ("cash", "Cash"),
            ("finance", "Finance"),
            ("undecided", "Not Confirmed"),
        ],
        tracking=True,
    )

    preferred_developer_id = fields.Many2one(
        comodel_name="brokerage.developer",
        tracking=True,
    )

    preferred_project_id = fields.Many2one(
        comodel_name="brokerage.project",
        tracking=True,
        domain="[('developer_id', '=', preferred_developer_id)]",
    )

    customer_requirement_notes = fields.Text(tracking=True)

    '''Forecast and Hot fields'''
    forecast_remarks = fields.Text(tracking=True)

    final_developer_id = fields.Many2one(
        comodel_name="brokerage.developer",
        tracking=True,
    )

    final_project_id = fields.Many2one(
        comodel_name="brokerage.project",
        tracking=True,
        domain="[('developer_id', '=', final_developer_id)]",
    )

    final_unit_type = fields.Char(tracking=True)

    estimated_property_value = fields.Monetary(
        currency_field="company_currency_id",
        tracking=True,
    )

    expected_booking_date = fields.Date(tracking=True)

    '''KYC fields'''
    kyc_owner_id = fields.Many2one(
        comodel_name="res.users",
        string="KYC Owner",
        domain=[("share", "=", False)],
        tracking=True,
    )

    kyc_status = fields.Selection(
        selection=[
            ("not_started", "Not Started"),
            ("in_progress", "In Progress"),
            ("verified", "Verified"),
            ("rejected", "Rejected"),
        ],
        string="KYC Status",
        default="not_started",
        required=True,
        tracking=True,
        index=True,
    )

    kyc_identity_type = fields.Selection(
        selection=[
            ("passport", "Passport"),
            ("emirates_id", "Emirates ID"),
            ("national_id", "National ID"),
            ("trade_license", "Trade License"),
            ("other", "Other Identification"),
        ],
        string="Identity Document Type",
        tracking=True,
    )

    kyc_identity_number = fields.Char(
        string="Identity Document Number",
        tracking=True,
        copy=False,
    )

    kyc_identity_expiry_date = fields.Date(
        string="Identity Document Expiry",
        tracking=True,
        copy=False,
    )

    kyc_nationality_id = fields.Many2one(
        comodel_name="res.country",
        string="Country / Nationality",
        tracking=True,
    )

    kyc_source_of_funds = fields.Selection(
        selection=[
            ("salary", "Salary / Employment Income"),
            ("business", "Business Income"),
            ("investment", "Investment Income"),
            ("savings", "Savings"),
            ("inheritance", "Inheritance"),
            ("other", "Other"),
        ],
        string="Source of Funds",
        tracking=True,
    )

    kyc_document_ids = fields.Many2many(
        comodel_name="ir.attachment",
        relation="crm_lead_kyc_attachment_rel",
        column1="lead_id",
        column2="attachment_id",
        string="KYC Documents",
        copy=False,
    )

    kyc_notes = fields.Text(
        string="KYC Verification Notes",
        tracking=True,
    )

    kyc_verified_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Verified By",
        readonly=True,
        copy=False,
        tracking=True,
    )

    kyc_verified_datetime = fields.Datetime(
        string="Verified Date/Time",
        readonly=True,
        copy=False,
        tracking=True,
    )

    '''Booking and documentation fields'''
    booking_unit_reference = fields.Char(
        string="Unit / Property Reference",
        tracking=True,
    )

    booking_amount = fields.Monetary(
        string="Booking Amount",
        currency_field="company_currency_id",
        tracking=True,
    )

    booking_date = fields.Date(
        string="Booking Date",
        tracking=True,
    )

    booking_payment_method_id = fields.Many2one(
        comodel_name="brokerage.crm.booking.payment.method",
        string="Payment Method",
        tracking=True,
    )

    booking_documentation_status_id = fields.Many2one(
        comodel_name="brokerage.crm.booking.documentation.status",
        string="Documentation Status",
        default=lambda self: self.env.ref(
            "brokerage_crm.booking_documentation_status_pending",
            raise_if_not_found=False,
        ),
        tracking=True,
    )

    booking_documentation_owner_id = fields.Many2one(
        comodel_name="res.users",
        string="Documentation Owner",
        domain=[("share", "=", False)],
        tracking=True,
    )

    booking_document_ids = fields.Many2many(
        comodel_name="ir.attachment",
        relation="crm_lead_booking_attachment_rel",
        column1="lead_id",
        column2="attachment_id",
        string="Booking Documents",
        copy=False,
    )

    booking_notes = fields.Text(
        string="Booking / Documentation Notes",
        tracking=True,
    )

    booking_documentation_completed_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Documentation Completed By",
        readonly=True,
        copy=False,
        tracking=True,
    )

    booking_documentation_completed_datetime = fields.Datetime(
        string="Documentation Completed Date/Time",
        readonly=True,
        copy=False,
        tracking=True,
    )

    '''Related Records'''
    contact_attempt_ids = fields.One2many(
        comodel_name="brokerage.crm.contact.attempt",
        inverse_name="lead_id",
    )

    brokerage_meeting_ids = fields.One2many(
        comodel_name="brokerage.crm.meeting",
        inverse_name="lead_id",
    )

    assignment_history_ids = fields.One2many(
        comodel_name="brokerage.crm.assignment.history",
        inverse_name="lead_id",
    )

    _brokerage_assignment_snapshot_fields = (
        "user_id",
        "team_id",
        "stage_id",
        "assignment_type",
        "assigned_datetime",
        "sla_cycle_active",
        "first_contact_datetime",
        "last_status_update",
        "last_meaningful_update",
        "lead_status_id",
        "forecast_remarks",
        "final_developer_id",
        "final_project_id",
        "final_unit_type",
        "estimated_property_value",
        "expected_booking_date",
        "not_interested_reassignment_done",
    )

    @api.model_create_multi
    def create(self, vals_list):
        round_robin_flags = []
        direct_assignment_flags = []
        explicit_team_flags = []
        for vals in vals_list:
            if vals.get("kyc_status") == "verified":
                vals.setdefault("kyc_verified_by_id", self.env.user.id)
                vals.setdefault(
                    "kyc_verified_datetime",
                    fields.Datetime.now(),
                )
            documentation_status = self.env[
                "brokerage.crm.booking.documentation.status"
            ].browse(vals.get("booking_documentation_status_id"))
            if documentation_status.allows_closing:
                vals.setdefault(
                    "booking_documentation_completed_by_id",
                    self.env.user.id,
                )
                vals.setdefault(
                    "booking_documentation_completed_datetime",
                    fields.Datetime.now(),
                )
            round_robin_flags.append(vals.get("assignment_type") == "round_robin")
            direct_assignment_flags.append(bool(vals.get("user_id")))
            explicit_team_flags.append(bool(vals.get("team_id")))
            if vals.get("user_id"):
                vals.setdefault("assigned_datetime", fields.Datetime.now())

        leads = super().create(vals_list)
        for lead, use_round_robin, is_direct, has_explicit_team in zip(
            leads,
            round_robin_flags,
            direct_assignment_flags,
            explicit_team_flags,
        ):
            if use_round_robin:
                lead.with_context(
                    force_global_round_robin=not has_explicit_team
                )._apply_round_robin_assignment()
            elif is_direct and lead.user_id:
                lead._record_direct_assignment(False, lead.user_id)
        return leads

    def write(self, vals):
        if "kyc_status" in vals:
            vals = dict(vals)
            if vals.get("kyc_status") == "verified":
                vals.setdefault("kyc_verified_by_id", self.env.user.id)
                vals.setdefault(
                    "kyc_verified_datetime",
                    fields.Datetime.now(),
                )
            else:
                vals["kyc_verified_by_id"] = False
                vals["kyc_verified_datetime"] = False
        if "booking_documentation_status_id" in vals:
            vals = dict(vals)
            documentation_status = self.env[
                "brokerage.crm.booking.documentation.status"
            ].browse(vals.get("booking_documentation_status_id"))
            if documentation_status.allows_closing:
                vals.setdefault(
                    "booking_documentation_completed_by_id",
                    self.env.user.id,
                )
                vals.setdefault(
                    "booking_documentation_completed_datetime",
                    fields.Datetime.now(),
                )
            else:
                vals["booking_documentation_completed_by_id"] = False
                vals["booking_documentation_completed_datetime"] = False
        previous = {
            lead.id: (
                lead.user_id,
                lead.team_id,
                lead.assignment_type,
                lead._brokerage_assignment_snapshot(),
            )
            for lead in self
        }
        stage = self.env["crm.stage"].browse(vals.get("stage_id"))
        if stage and not self.env.context.get("brokerage_workflow_action"):
            for lead in self:
                lead._validate_brokerage_stage_move(stage)

        if stage and self._stage_code(stage) != "assigned":
            vals = dict(vals)
            vals["sla_cycle_active"] = False

        trigger_round_robin = (
            vals.get("assignment_type") == "round_robin"
            and not self.env.context.get("skip_round_robin")
        )
        if trigger_round_robin:
            # Let the requested type be stored, then assign atomically using the
            # configured queue. Any user_id supplied in the same write is ignored.
            vals = dict(vals)
            vals.pop("user_id", None)

        result = super().write(vals)

        if stage and self._stage_code(stage) == "kyc":
            kyc_to_start = self.filtered(
                lambda lead: lead.kyc_status == "not_started"
            )
            if kyc_to_start:
                super(CrmLead, kyc_to_start).write({
                    "kyc_status": "in_progress",
                })

        if stage and self._stage_code(stage) in (
            "contact_attempted", "contacted", "not_interested"
        ):
            self._clear_open_brokerage_sla_activities()

        if trigger_round_robin:
            for lead in self:
                lead._apply_round_robin_assignment()
            return result

        if "user_id" in vals and not self.env.context.get("skip_assignment_history"):
            now = fields.Datetime.now()
            for lead in self:
                old_user, old_team, old_type, old_snapshot = previous[lead.id]
                if lead.user_id != old_user:
                    lead.with_context(skip_assignment_history=True).write({
                        "assigned_datetime": now if lead.user_id else False,
                        "first_contact_datetime": False,
                        "last_meaningful_update": now if lead.user_id else False,
                    })
                    if lead.user_id:
                        lead._record_direct_assignment(
                            old_user,
                            lead.user_id,
                            old_team,
                            before_snapshot=old_snapshot,
                        )
        return result

    def _record_direct_assignment(
        self,
        previous_user,
        new_user,
        previous_team=False,
        before_snapshot=False,
    ):
        self.ensure_one()
        if not self.team_id:
            return
        self.env["brokerage.crm.assignment.history"].create({
            "lead_id": self.id,
            "source_id": self.source_id.id or False,
            "previous_user_id": previous_user.id if previous_user else False,
            "new_user_id": new_user.id,
            "previous_team_id": previous_team.id if previous_team else False,
            "new_team_id": self.team_id.id or False,
            "assignment_type": self.assignment_type or "manual",
            "assigned_datetime": self.assigned_datetime or fields.Datetime.now(),
            "assigned_by_id": self.env.user.id,
            "reason": _("Direct assignment"),
            "previous_stage_id": (
                before_snapshot.get("stage_id")
                if before_snapshot
                else False
            ),
            "new_stage_id": self.stage_id.id or False,
            "before_snapshot": before_snapshot or False,
            "after_snapshot": self._brokerage_assignment_snapshot(),
        })
        self._queue_brokerage_whatsapp_assignment(
            new_user,
            _("Direct assignment"),
        )

    def _queue_brokerage_whatsapp_assignment(self, user, reason=None):
        self.ensure_one()
        if not user:
            return self.env["brokerage.whatsapp.notification"]
        try:
            return self.env[
                "brokerage.whatsapp.notification"
            ].sudo().queue_assignment(
                self.sudo(),
                user.sudo(),
                reason=reason,
            )
        except Exception:
            _logger.exception(
                "Could not queue assignment WhatsApp for CRM lead %s",
                self.id,
            )
            return self.env["brokerage.whatsapp.notification"]

    def _queue_brokerage_whatsapp_sla(
        self,
        user,
        event_type,
        minutes,
        rule,
        assignment_datetime,
    ):
        self.ensure_one()
        if not user:
            return self.env["brokerage.whatsapp.notification"]
        try:
            return self.env[
                "brokerage.whatsapp.notification"
            ].sudo().queue_sla(
                self.sudo(),
                user.sudo(),
                event_type,
                minutes,
                rule.sudo(),
                assignment_datetime,
            )
        except Exception:
            _logger.exception(
                "Could not queue SLA WhatsApp for CRM lead %s event %s",
                self.id,
                event_type,
            )
            return self.env["brokerage.whatsapp.notification"]

    def _queue_brokerage_email_sla(self, sla_log, user, minutes):
        self.ensure_one()
        if not sla_log or not user:
            return self.env["brokerage.crm.email.notification"]
        try:
            return self.env[
                "brokerage.crm.email.notification"
            ].sudo().queue_sla(
                sla_log.sudo(),
                user.sudo(),
                minutes,
            )
        except Exception:
            # SLA processing must continue even when an email cannot queue.
            _logger.exception(
                "Could not queue SLA email for CRM lead %s event %s",
                self.id,
                sla_log.event_type,
            )
            return self.env["brokerage.crm.email.notification"]

    def _brokerage_repeat_enquiry_recipient(self):
        self.ensure_one()
        candidates = self.user_id | self.team_id.user_id
        return candidates.filtered(
            lambda user: user.active and not user.share
        )[:1]

    def _brokerage_previous_owner_is_eligible(self):
        """Return whether the current owner can receive a reopened enquiry."""
        self.ensure_one()
        user = self.user_id
        team = self.team_id
        if (
            not user
            or not team
            or not user.active
            or user.share
            or not user.available_for_crm_assignment
        ):
            return False
        if team.brokerage_solo_campaign:
            return user in team.sudo()._brokerage_solo_agents()
        rule = self.env["brokerage.crm.round.robin"].sudo().search([
            ("team_id", "=", team.id),
            ("active", "=", True),
        ], limit=1)
        return bool(rule and user in rule._get_eligible_users())

    def _notify_brokerage_repeat_enquiry(self, user, event_number, action):
        """Notify one responsible user without changing the assignment."""
        self.ensure_one()
        if not user or not user.active or user.share:
            return False
        label = _("Repeat CRM Enquiry")
        action_text = {
            "active_duplicate": _(
                ""            ),
            "manual_review": _(
                "Automatic reopening was blocked. Please review the "
                "existing lead manually."
            ),
            "reopened_manual": _(
                "The lead was reopened for manual assignment."
            ),
        }.get(action, _("Please review the repeat enquiry."))
        self.message_notify(
            partner_ids=user.partner_id.ids,
            author_id=self.env.user.partner_id.id,
            body=Markup(
                "<p><b>%(heading)s</b></p>"
                "<p>%(lead_label)s: %(lead)s<br/>"
                "%(customer_label)s: %(customer)s<br/>"
                "%(instruction)s</p>"
            ) % {
                "heading": label,
                "lead_label": _("Lead"),
                "lead": self.display_name,
                "customer_label": _("Customer"),
                "customer": self.contact_name or self.partner_name or "-",
                "instruction": action_text,
            },
            subject="%s: %s" % (label, self.display_name),
            model_description=_("CRM Lead"),
            force_record_name=self.display_name,
            notify_skip_followers=True,
            skip_existing=True,
        )
        event_key = "repeat-enquiry:%s:%s:%s" % (
            self.id,
            event_number,
            user.id,
        )
        try:
            self.env["brokerage.whatsapp.notification"].sudo().queue_repeat_enquiry(
                self.sudo(), user.sudo(), event_key, action_text
            )
        except Exception:
            _logger.exception(
                "Could not queue repeat-enquiry WhatsApp for lead %s",
                self.id,
            )
        try:
            self.env["brokerage.crm.email.notification"].sudo().queue_repeat_enquiry(
                self.sudo(), user.sudo(), event_key, action_text
            )
        except Exception:
            _logger.exception(
                "Could not queue repeat-enquiry email for lead %s",
                self.id,
            )
        return True

    def _brokerage_record_repeat_enquiry(
        self,
        source,
        campaign,
        medium,
        incoming_name,
        incoming_email,
        incoming_phone,
        requested_assignment_type,
        action,
        previous_stage,
        previous_user,
        previous_team,
    ):
        self.ensure_one()
        now = fields.Datetime.now()
        event_number = self.repeat_enquiry_count + 1
        self.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({
            "repeat_enquiry_count": event_number,
            "last_repeat_enquiry_datetime": now,
            "last_repeat_enquiry_source_id": source.id or False,
            "last_repeat_enquiry_campaign_id": campaign.id or False,
            "last_repeat_enquiry_medium_id": medium.id or False,
        })
        action_labels = {
            "active_duplicate": _("Kept with the existing owner and stage"),
            "reopened_previous_user": _("Reopened for the previous eligible salesperson"),
            "reopened_round_robin": _("Reopened through the normal Round Robin"),
            "reopened_manual": _("Reopened for manual assignment"),
            "manual_review": _("Held for manual review"),
        }
        self.message_post(
            body=Markup(
                "<p><b>%(title)s</b></p>"
                "<p>%(received)s: %(date)s<br/>"
                "%(incoming_customer)s: %(customer)s<br/>"
                "%(incoming_email_label)s: %(email)s<br/>"
                "%(incoming_phone_label)s: %(phone)s<br/>"
                "%(source_label)s: %(source)s<br/>"
                "%(campaign_label)s: %(campaign)s<br/>"
                "%(medium_label)s: %(medium)s<br/>"
                "%(requested_type)s: %(assignment_type)s<br/>"
                "%(previous_owner)s: %(user)s / %(team)s / %(stage)s<br/>"
                "%(result_label)s: %(result)s</p>"
            ) % {
                "title": _("Repeat enquiry received"),
                "received": _("Received"),
                "date": fields.Datetime.to_string(now),
                "incoming_customer": _("Incoming customer name"),
                "customer": incoming_name or "-",
                "incoming_email_label": _("Incoming email"),
                "email": incoming_email or "-",
                "incoming_phone_label": _("Incoming phone"),
                "phone": incoming_phone or "-",
                "source_label": _("Incoming source"),
                "source": source.display_name or "-",
                "campaign_label": _("Incoming campaign"),
                "campaign": campaign.display_name or "-",
                "medium_label": _("Incoming medium"),
                "medium": medium.display_name or "-",
                "requested_type": _("Requested assignment type"),
                "assignment_type": requested_assignment_type,
                "previous_owner": _("Previous owner context"),
                "user": previous_user.display_name or "-",
                "team": previous_team.display_name or "-",
                "stage": previous_stage.display_name or "-",
                "result_label": _("Result"),
                "result": action_labels[action],
            },
            subtype_xmlid="mail.mt_note",
        )
        return event_number

    def _brokerage_reopen_for_previous_owner(
        self, source, campaign, medium, requested_assignment_type
    ):
        self.ensure_one()
        previous_user = self.user_id
        previous_team = self.team_id
        before_snapshot = self._brokerage_assignment_snapshot()
        assigned_stage = self._find_brokerage_stage(
            "assigned", team=previous_team
        )
        if not assigned_stage:
            raise ValidationError(_(
                "Configure an Assigned CRM stage for Sales Team %s."
            ) % previous_team.display_name)
        now = fields.Datetime.now()
        history_type = (
            "reassignment"
            if requested_assignment_type == "round_robin"
            else "manual"
        )
        values = {
            "active": True,
            "lost_reason_id": False,
            "source_id": source.id,
            "campaign_id": campaign.id or False,
            "medium_id": medium.id or False,
            "stage_id": assigned_stage.id,
            "user_id": previous_user.id,
            "team_id": previous_team.id,
            "not_interested_reassignment_done": False,
        }
        values.update(
            self._prepare_brokerage_assignment_cycle_values(history_type, now)
        )
        if requested_assignment_type != "round_robin":
            values["sla_cycle_active"] = False
        self._clear_open_brokerage_sla_activities()
        self.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write(values)
        reason = _("Repeat enquiry reopened for the previous salesperson")
        self.env["brokerage.crm.assignment.history"].sudo().create({
            "lead_id": self.id,
            "source_id": source.id,
            "previous_user_id": previous_user.id,
            "new_user_id": previous_user.id,
            "previous_team_id": previous_team.id,
            "new_team_id": previous_team.id,
            "assignment_type": history_type,
            "assigned_datetime": now,
            "assigned_by_id": self.env.user.id,
            "reason": reason,
            "previous_stage_id": before_snapshot.get("stage_id") or False,
            "new_stage_id": self.stage_id.id,
            "before_snapshot": before_snapshot,
            "after_snapshot": self._brokerage_assignment_snapshot(),
        })
        self._queue_brokerage_whatsapp_assignment(previous_user, reason)
        return "reopened_previous_user"

    def _brokerage_handle_duplicate_enquiry(
        self,
        source,
        campaign,
        medium,
        incoming_name,
        incoming_email,
        incoming_phone,
        requested_assignment_type,
    ):
        """Apply the approved active/closed duplicate-enquiry workflows."""
        self.ensure_one()
        lead = self.sudo()
        previous_stage = lead.stage_id
        previous_user = lead.user_id
        previous_team = lead.team_id
        stage_code = lead._stage_code(previous_stage)
        status_code = lead.lead_status_id.code
        is_not_interested = (
            stage_code == "not_interested"
            or status_code == "not_interested"
        )
        is_lost = not lead.active or lead.won_status == "lost"
        is_invalid = (
            (lead.lead_status_id.is_invalid and not is_not_interested)
            or lead.phone_sanitized_blacklisted
            or lead.partner_is_blacklisted
        )

        if is_invalid or lead.won_status == "won":
            action = "manual_review"
        elif is_not_interested or is_lost:
            if lead._brokerage_previous_owner_is_eligible():
                action = lead._brokerage_reopen_for_previous_owner(
                    source,
                    campaign,
                    medium,
                    requested_assignment_type,
                )
            elif requested_assignment_type == "round_robin":
                lead._clear_open_brokerage_sla_activities()
                lead.with_context(
                    skip_assignment_history=True,
                    skip_round_robin=True,
                    brokerage_workflow_action=True,
                ).write({
                    "active": True,
                    "lost_reason_id": False,
                    "source_id": source.id,
                    "campaign_id": campaign.id or False,
                    "medium_id": medium.id or False,
                    "not_interested_reassignment_done": False,
                })
                self.env[
                    "brokerage.crm.round.robin"
                ].sudo().assign_lead_by_normal_sequence(
                    lead,
                    reason=_(
                        "Repeat enquiry reassigned because the previous "
                        "salesperson is unavailable"
                    ),
                )
                action = "reopened_round_robin"
            else:
                new_stage = self.env["crm.stage"].sudo().search([
                    ("brokerage_code", "=", "new"),
                ], order="sequence, id", limit=1)
                if not new_stage:
                    raise ValidationError(_(
                        "Configure a New Lead CRM stage before reopening "
                        "manual enquiries."
                    ))
                lead._clear_open_brokerage_sla_activities()
                lead.with_context(
                    skip_assignment_history=True,
                    skip_round_robin=True,
                    brokerage_workflow_action=True,
                ).write({
                    "active": True,
                    "lost_reason_id": False,
                    "source_id": source.id,
                    "campaign_id": campaign.id or False,
                    "medium_id": medium.id or False,
                    "assignment_type": "manual",
                    "stage_id": new_stage.id,
                    "user_id": False,
                    "team_id": False,
                    "assigned_datetime": False,
                    "sla_cycle_active": False,
                    "first_contact_datetime": False,
                    "last_meaningful_update": fields.Datetime.now(),
                    "not_interested_reassignment_done": False,
                })
                action = "reopened_manual"
        else:
            action = "active_duplicate"

        event_number = lead._brokerage_record_repeat_enquiry(
            source,
            campaign,
            medium,
            incoming_name,
            incoming_email,
            incoming_phone,
            requested_assignment_type,
            action,
            previous_stage,
            previous_user,
            previous_team,
        )
        # Reopened assigned leads already receive exactly one assignment alert
        # from their assignment-history event. Other outcomes need a targeted
        # repeat-enquiry alert instead.
        if action in (
            "active_duplicate",
            "manual_review",
            "reopened_manual",
        ):
            recipient = lead._brokerage_repeat_enquiry_recipient()
            if not recipient and previous_team:
                recipient = previous_team.user_id.filtered(
                    lambda user: user.active and not user.share
                )[:1]
            lead._notify_brokerage_repeat_enquiry(
                recipient,
                event_number,
                action,
            )
        return action

    def _apply_round_robin_assignment(self):
        for lead in self:
            source_team = lead.source_id.default_team_id
            # Odoo may inject its normal default team during create even when
            # the API caller did not send team_id. An explicitly configured
            # solo source must win over that implicit default.
            routed_team = (
                source_team
                if (
                    self.env.context.get("force_global_round_robin")
                    and source_team.brokerage_solo_campaign
                )
                else (lead.team_id or source_team)
            )
            if routed_team and routed_team.brokerage_solo_campaign:
                routed_team.sudo().assign_brokerage_solo_lead(
                    lead.sudo(),
                    reason=_("Solo campaign lead assignment"),
                )
                continue
            team = (
                False
                if self.env.context.get("force_global_round_robin")
                else routed_team
            )
            round_robin = self.env["brokerage.crm.round.robin"].sudo()
            if team:
                rule = round_robin.search([
                    ("team_id", "=", team.id), ("active", "=", True)
                ], limit=1)
            else:
                # New external leads rotate through teams by configured
                # sequence. Assignment totals remain reporting values only.
                round_robin.assign_lead_by_normal_sequence(lead.sudo())
                continue
            if not rule:
                scope = team.display_name if team else _("any Sales Team")
                raise ValidationError(_(
                    "No active Round Robin configuration with eligible agents "
                    "exists for %s."
                ) % scope)
            # Configuration and assignment history are intentionally elevated:
            # agents/integration users may create leads but must not receive
            # permission to edit the Round Robin setup itself.
            rule.assign_lead(lead.sudo())

    def _stage_code(self, stage):
        if stage.brokerage_code:
            return stage.brokerage_code
        normalized = (stage.name or "").strip().lower().replace("/", " ")
        normalized = "_".join(normalized.split())
        aliases = {
            "new_lead": "new", "assigned": "assigned",
            "contact_attempted": "contact_attempted", "contacted": "contacted",
            "meeting_scheduled": "meeting_scheduled",
            "meeting_completed": "meeting_completed", "forecast": "forecast",
            "hot_booking_expected": "hot", "kyc_in_progress": "kyc",
            "booking_documentation": "booking",
            "not_interested": "not_interested",
        }
        return aliases.get(normalized)

    @api.depends(
        "active",
        "type",
        "won_status",
        "stage_id",
        "stage_id.brokerage_code",
        "user_id",
    )
    def _compute_brokerage_next_action(self):
        action_by_stage = {
            "assigned": "contact_attempt",
            "contact_attempted": "contact_attempt",
            "contacted": "schedule_meeting",
            "meeting_scheduled": "complete_meeting",
        }
        for lead in self:
            is_open_opportunity = (
                lead.type == "opportunity"
                and lead.active
                and lead.won_status == "pending"
            )
            lead.brokerage_next_action = (
                action_by_stage.get(lead._stage_code(lead.stage_id))
                if is_open_opportunity
                else False
            )

    @api.depends("brokerage_next_action")
    def _compute_brokerage_next_step_hint(self):
        compatibility_labels = {
            "contact_attempt": _("Next: Record Contact Attempt"),
            "schedule_meeting": _("Next: Schedule Meeting"),
            "complete_meeting": _("Next: Complete Meeting"),
        }
        for lead in self:
            lead.brokerage_next_step_hint = compatibility_labels.get(
                lead.brokerage_next_action,
                False,
            )

    def _find_brokerage_stage(self, code, team=False):
        self.ensure_one()
        target_team = team or self.team_id
        stage = self.env["crm.stage"].search([
            ("brokerage_code", "=", code),
            "|", ("team_ids", "=", False), ("team_ids", "in", target_team.ids),
        ], order="sequence, id", limit=1)
        if stage:
            return stage
        names = {
            "contact_attempted": "Contact Attempted",
            "contacted": "Contacted",
            "not_interested": "Not Interested",
            "meeting_scheduled": "Meeting Scheduled",
            "meeting_completed": "Meeting Completed",
        }
        return self.env["crm.stage"].search([
            ("name", "=ilike", names.get(code, code)),
            "|", ("team_ids", "=", False), ("team_ids", "in", target_team.ids),
        ], order="sequence, id", limit=1)

    def _prepare_brokerage_assignment_cycle_values(
        self, assignment_type, assigned_datetime=None
    ):
        """Reset transient workflow evidence for a new salesperson cycle."""
        self.ensure_one()
        assigned_datetime = assigned_datetime or fields.Datetime.now()
        assigned_status = self.env[
            "brokerage.crm.lead.status"
        ].sudo().search([("code", "=", "assigned")], limit=1)
        return {
            "assignment_type": assignment_type,
            "assigned_datetime": assigned_datetime,
            "sla_cycle_active": True,
            "first_contact_datetime": False,
            "last_status_update": assigned_datetime,
            "last_meaningful_update": assigned_datetime,
            "lead_status_id": assigned_status.id or False,
            "forecast_remarks": False,
            "final_developer_id": False,
            "final_project_id": False,
            "final_unit_type": False,
            "estimated_property_value": 0,
            "expected_booking_date": False,
        }

    def _brokerage_assignment_snapshot(self):
        """Return a JSON-safe snapshot of fields changed by assignment."""
        self.ensure_one()
        snapshot = {}
        for field_name in self._brokerage_assignment_snapshot_fields:
            field = self._fields[field_name]
            value = self[field_name]
            if field.type == "many2one":
                snapshot[field_name] = value.id or False
            elif field.type == "datetime":
                snapshot[field_name] = (
                    fields.Datetime.to_string(value) if value else False
                )
            elif field.type == "date":
                snapshot[field_name] = (
                    fields.Date.to_string(value) if value else False
                )
            else:
                snapshot[field_name] = value
        return snapshot

    def _brokerage_assignment_snapshot_values(self, snapshot):
        """Convert a stored assignment snapshot back to ORM write values."""
        self.ensure_one()
        values = {}
        snapshot = snapshot or {}
        for field_name in self._brokerage_assignment_snapshot_fields:
            if field_name not in snapshot:
                continue
            field = self._fields[field_name]
            value = snapshot[field_name]
            if field.type == "many2one":
                record = (
                    self.env[field.comodel_name].browse(value).exists()
                    if value
                    else self.env[field.comodel_name]
                )
                values[field_name] = record.id or False
            else:
                values[field_name] = value
        return values

    def _current_assignment_contact_attempts(self):
        self.ensure_one()
        domain = [("lead_id", "=", self.id)]
        if self.assigned_datetime:
            domain.append((
                "attempt_datetime",
                ">=",
                self.assigned_datetime,
            ))
        if self.user_id:
            domain.append(("user_id", "=", self.user_id.id))
        return self.env["brokerage.crm.contact.attempt"].search(domain)

    def _current_assignment_meetings(self):
        self.ensure_one()
        domain = [("lead_id", "=", self.id)]
        if self.assigned_datetime:
            domain.extend([
                "|",
                ("recorded_datetime", ">=", self.assigned_datetime),
                "&",
                ("recorded_datetime", "=", False),
                ("create_date", ">=", self.assigned_datetime),
            ])
        if self.user_id:
            domain.append(("create_uid", "=", self.user_id.id))
        return self.env["brokerage.crm.meeting"].search(domain)

    def _validate_brokerage_stage_move(self, target_stage):
        self.ensure_one()
        code = self._stage_code(target_stage)
        current_code = self._stage_code(self.stage_id)
        if (
            current_code
            and code
            and target_stage.sequence < self.stage_id.sequence
        ):
            raise ValidationError(_(
                "Leads cannot be moved backward from %(current)s to "
                "%(target)s by dragging the pipeline card. Ask a Sales "
                "Manager to use Correct Stage when a genuine correction "
                "is required."
            ) % {
                "current": self.stage_id.display_name,
                "target": target_stage.display_name,
            })

        attempts = self._current_assignment_contact_attempts()
        successful_attempts = attempts.filtered("successful_contact")
        meetings = self._current_assignment_meetings()
        if code == "contact_attempted" and not attempts:
            raise ValidationError(
                _(
                    "The current salesperson must record a Contact Attempt "
                    "after this assignment before moving to Contact Attempted."
                )
            )
        if code == "contacted" and not successful_attempts:
            raise ValidationError(
                _(
                    "The current salesperson must record a successful contact "
                    "after this assignment before moving to Contacted."
                )
            )
        if code in (
            "meeting_scheduled", "meeting_completed", "forecast", "hot",
            "kyc", "booking",
        ) and not successful_attempts:
            raise ValidationError(_(
                "The current salesperson must record a successful contact "
                "before progressing to meeting and later stages."
            ))
        if code == "meeting_scheduled" and not meetings.filtered(
            lambda meeting: meeting.state in ("scheduled", "rescheduled", "completed")
        ):
            raise ValidationError(
                _(
                    "The current salesperson must schedule and log a meeting "
                    "after this assignment before moving to Meeting Scheduled."
                )
            )
        if code in (
            "meeting_completed", "forecast", "hot", "kyc", "booking"
        ) and not meetings.filtered(
            lambda meeting: meeting.state == "completed"
        ):
            raise ValidationError(
                _(
                    "The current salesperson must complete a meeting created "
                    "after this assignment before moving forward."
                )
            )
        if code in ("hot", "kyc", "booking") and not all((
            self.final_developer_id, self.final_project_id,
            self.final_unit_type, self.expected_booking_date,
            self.kyc_owner_id,
        )):
            raise ValidationError(
                _(
                    "Final developer, project, unit type, expected booking "
                    "date and KYC owner are required before progressing to "
                    "Hot / Booking Expected and later stages."
                )
            )
        if code == "booking" and self.kyc_status != "verified":
            raise ValidationError(_(
                "KYC must be completed and marked as Verified before moving "
                "the lead to Booking / Documentation."
            ))
        if code == "booking":
            missing = [
                label
                for value, label in (
                    (self.booking_unit_reference, _("Unit / Property Reference")),
                    (self.estimated_property_value, _("Property Value")),
                    (self.booking_amount, _("Booking Amount")),
                    (self.booking_date, _("Booking Date")),
                    (self.booking_payment_method_id, _("Payment Method")),
                    (
                        self.booking_documentation_status_id,
                        _("Documentation Status"),
                    ),
                    (
                        self.booking_documentation_owner_id,
                        _("Documentation Owner"),
                    ),
                )
                if not value
            ]
            if missing:
                raise ValidationError(_(
                    "Complete these Booking / Documentation details before "
                    "moving the lead to this stage: %s"
                ) % ", ".join(missing))
        if code == "won":
            if current_code != "booking":
                raise ValidationError(_(
                    "The lead must pass through Booking / Documentation "
                    "before it can be marked Closed Won."
                ))
            if not (
                self.booking_documentation_status_id.allows_closing
                and self.booking_document_ids
            ):
                raise ValidationError(_(
                    "Complete the booking documentation and attach the "
                    "booking documents before marking the lead Closed Won."
                ))

    @api.constrains(
        "kyc_status",
        "kyc_owner_id",
        "kyc_identity_type",
        "kyc_identity_number",
        "kyc_identity_expiry_date",
        "kyc_nationality_id",
        "kyc_source_of_funds",
        "kyc_document_ids",
    )
    def _check_verified_kyc_details(self):
        required_fields = (
            ("kyc_owner_id", _("KYC Owner")),
            ("kyc_identity_type", _("Identity Document Type")),
            ("kyc_identity_number", _("Identity Document Number")),
            ("kyc_identity_expiry_date", _("Identity Document Expiry")),
            ("kyc_nationality_id", _("Country / Nationality")),
            ("kyc_source_of_funds", _("Source of Funds")),
            ("kyc_document_ids", _("KYC Documents")),
        )
        today = fields.Date.context_today(self)
        for lead in self.filtered(lambda item: item.kyc_status == "verified"):
            missing = [
                label
                for field_name, label in required_fields
                if not lead[field_name]
            ]
            if missing:
                raise ValidationError(_(
                    "Complete these KYC details before marking the KYC as "
                    "Verified: %s"
                ) % ", ".join(missing))
            if lead.kyc_identity_expiry_date < today:
                raise ValidationError(_(
                    "The identity document is expired. Enter a valid document "
                    "before marking the KYC as Verified."
                ))

    @api.constrains(
        "booking_amount",
        "estimated_property_value",
    )
    def _check_booking_amount(self):
        for lead in self:
            if lead.booking_amount < 0:
                raise ValidationError(
                    _("Booking Amount cannot be negative.")
                )
            if (
                lead.booking_amount
                and lead.estimated_property_value
                and lead.booking_amount > lead.estimated_property_value
            ):
                raise ValidationError(_(
                    "Booking Amount cannot exceed the Property Value."
                ))

    @api.constrains(
        "booking_documentation_status_id",
        "booking_document_ids",
    )
    def _check_completed_booking_documentation(self):
        for lead in self.filtered(
            lambda item: item.booking_documentation_status_id.allows_closing
        ):
            if not lead.booking_document_ids:
                raise ValidationError(_(
                    "Attach at least one Booking Document before marking "
                    "the documentation as complete."
                ))

    @api.model
    def _cron_check_brokerage_sla(self):
        now = fields.Datetime.now()
        rules = self.env["brokerage.crm.sla.rule"].search([
            ("active", "=", True),
            ("rule_type", "=", "first_contact"),
        ])
        for rule in rules:
            domain = [
                ("active", "=", True),
                ("user_id", "!=", False),
                ("assigned_datetime", "!=", False),
                ("sla_cycle_active", "=", True),
                (
                    "assignment_type",
                    "in",
                    [
                        "round_robin",
                        "reassignment",
                        "not_interested_reassignment",
                        "solo_campaign",
                    ],
                ),
            ]
            if rule.team_id:
                domain.append(("team_id", "=", rule.team_id.id))
            if rule.source_category:
                domain.append(("source_category", "=", rule.source_category))
            if rule.quality_id:
                domain.append(("lead_quality_id", "=", rule.quality_id.id))
            for lead in self.search(domain):
                if lead.source_id and not lead.source_id.sla_applicable:
                    continue
                if lead._stage_code(lead.stage_id) != "assigned":
                    continue
                lead._process_sla_rule(rule, now)
        return True

    def _process_sla_rule(self, rule, now):
        self.ensure_one()
        assignment_datetime = self.assigned_datetime
        elapsed = self._brokerage_sla_elapsed_minutes(now)
        assigned_to_team_leader = (
            self.team_id
            and self.user_id
            and self.user_id == self.team_id._brokerage_team_leader()
        )
        events = [
            ("reminder_1", rule.reminder_1_minutes),
            ("reminder_2", rule.reminder_2_minutes),
            ("reminder_3", rule.reminder_3_minutes),
        ]
        if assigned_to_team_leader:
            # Escalating a Team-Leader-owned lead back to the same Team
            # Leader is redundant. Replace that hierarchy step with the
            # same-team-first reassignment.
            events.append((
                "reassignment",
                rule.escalation_minutes or rule.reassignment_minutes,
            ))
        else:
            events.extend([
                ("team_leader_escalation", rule.escalation_minutes),
                ("reassignment", rule.reassignment_minutes),
            ])
        for event_type, minutes in events:
            if not minutes or elapsed < minutes:
                continue
            deadline = self._brokerage_sla_deadline(minutes)
            existing = self.env["brokerage.crm.sla.log"].search_count([
                ("lead_id", "=", self.id), ("rule_id", "=", rule.id),
                ("event_type", "=", event_type),
                ("assignment_datetime", "=", assignment_datetime),
            ])
            if existing:
                continue

            if event_type == "reassignment":
                reason = (
                    _(
                        "Automatic reassignment after no contact attempt or qualifying update, "
                    )
                    if assigned_to_team_leader
                    else _(
                        "Automatic reassignment after no contact attempt or qualifying update"
                    )
                )
                if self.team_id.brokerage_solo_campaign:
                    reassigned_user = self.env[
                        "crm.team"
                    ].assign_brokerage_solo_cross_team(
                        self,
                        preferred_team=rule.reassignment_team_id,
                        reason=reason,
                    )
                else:
                    reassigned_user = self.env[
                        "brokerage.crm.round.robin"
                    ].assign_lead_cross_team(
                        self,
                        preferred_team=rule.reassignment_team_id,
                        reason=reason,
                    )
                if not reassigned_user:
                    continue
                self.env["brokerage.crm.sla.log"].create({
                    "lead_id": self.id,
                    "rule_id": rule.id,
                    "assignment_datetime": assignment_datetime,
                    "deadline": deadline,
                    "state": "breached",
                    "completed_at": now,
                    "event_type": event_type,
                })
                self._clear_open_brokerage_sla_activities()
                self.message_post(
                    body=_(
                        "SLA Reassignment triggered after %s minutes."
                    ) % minutes,
                    subtype_xmlid="mail.mt_note",
                )
                continue

            target_user = self.user_id
            if event_type == "team_leader_escalation":
                target_user = self._brokerage_sla_escalation_target(
                    rule,
                )
            sla_log = self.env["brokerage.crm.sla.log"].create({
                "lead_id": self.id, "rule_id": rule.id,
                "assignment_datetime": assignment_datetime,
                "deadline": deadline, "state": "breached",
                "completed_at": now, "event_type": event_type,
                "target_user_id": target_user.id,
            })
            event_label = {
                "reminder_1": _("Reminder 1"),
                "reminder_2": _("Reminder 2"),
                "reminder_3": _("Reminder 3"),
                "team_leader_escalation": _(
                    "Team Leader Escalation"
                ),
            }[event_type]
            self.env["mail.activity"].create({
                "res_model_id": self.env["ir.model"]._get_id("crm.lead"),
                "res_id": self.id,
                "activity_type_id": rule.activity_type_id.id,
                "user_id": target_user.id,
                "date_deadline": fields.Date.context_today(self),
                "summary": _(
                    "SLA %s: update assigned lead"
                ) % event_label,
                "note": _("No contact attempt or qualifying update was recorded within %s minutes.") % minutes,
            })
            self._queue_brokerage_whatsapp_sla(
                target_user,
                event_type,
                minutes,
                rule,
                assignment_datetime,
            )
            self._queue_brokerage_email_sla(
                sla_log,
                target_user,
                minutes,
            )
            self.message_post(
                body=_("SLA %(event)s triggered after %(minutes)s minutes.") % {
                    "event": event_label,
                    "minutes": minutes,
                },
                subtype_xmlid="mail.mt_note",
            )

    def _brokerage_sla_escalation_target(self, rule):
        """Resolve the final escalation recipient: the Team Leader."""
        self.ensure_one()
        team = self.team_id
        team_leader = team._brokerage_team_leader() if team else (
            self.env["res.users"]
        )
        return (
            rule.escalation_user_id
            or team_leader
            or self.user_id
        )

    def _brokerage_sla_elapsed_minutes(self, now):
        """Count elapsed SLA time only inside the team's working calendar."""
        self.ensure_one()
        calendar = (
            self.team_id._brokerage_sla_calendar()
            if self.team_id
            else self.env.company.resource_calendar_id
        )
        if not calendar:
            return (
                (now - self.assigned_datetime).total_seconds() / 60
            )
        duration = calendar.get_work_duration_data(
            self.assigned_datetime,
            now,
            compute_leaves=True,
        )
        return duration["hours"] * 60

    def _brokerage_sla_deadline(self, minutes):
        """Return the wall-clock deadline after N working minutes."""
        self.ensure_one()
        calendar = (
            self.team_id._brokerage_sla_calendar()
            if self.team_id
            else self.env.company.resource_calendar_id
        )
        if not calendar:
            from datetime import timedelta
            return self.assigned_datetime + timedelta(minutes=minutes)
        deadline = calendar.plan_hours(
            minutes / 60,
            self.assigned_datetime,
            compute_leaves=True,
        )
        return (
            fields.Datetime.to_datetime(deadline)
            if deadline
            else self.assigned_datetime
        )

    def _clear_open_brokerage_sla_activities(self):
        activities = self.env["mail.activity"].search([
            ("res_model", "=", "crm.lead"),
            ("res_id", "in", self.ids),
            ("summary", "ilike", "SLA "),
        ])
        activities.unlink()

    @api.depends(
        "contact_attempt_ids",
        "brokerage_meeting_ids",
        "assignment_history_ids",
    )
    def _compute_brokerage_counts(self):
        for lead in self:
            lead.contact_attempt_count = len(lead.contact_attempt_ids)
            lead.meeting_count = len(lead.brokerage_meeting_ids)
            lead.assignment_history_count = len(
                lead.assignment_history_ids
            )

    @api.depends(
        "user_id",
        "team_id",
        "stage_id",
        "assignment_history_ids.is_recovered",
        "assignment_history_ids.before_snapshot",
    )
    def _compute_can_recover_last_assignment(self):
        recoverable_types = (
            "reassignment",
            "not_interested_reassignment",
        )
        history_model = self.env[
            "brokerage.crm.assignment.history"
        ].sudo()
        for lead in self:
            history = history_model.search(
                [("lead_id", "=", lead.id)],
                order="assigned_datetime desc, id desc",
                limit=1,
            )
            lead.can_recover_last_assignment = bool(
                history
                and history.assignment_type in recoverable_types
                and history.before_snapshot
                and not history.is_recovered
                and lead.user_id == history.new_user_id
                and lead.team_id == history.new_team_id
                and lead._stage_code(lead.stage_id) == "assigned"
            )

    @api.constrains("budget_from", "budget_to")
    def _check_budget_range(self):
        for lead in self:
            if lead.budget_from < 0 or lead.budget_to < 0:
                raise ValidationError(
                    _("Budget values cannot be negative.")
                )

            if (
                lead.budget_from
                and lead.budget_to
                and lead.budget_from > lead.budget_to
            ):
                raise ValidationError(
                    _("Budget From cannot be greater than Budget To.")
                )
            
    @api.constrains("estimated_property_value")
    def _check_estimated_property_value(self):
        for lead in self:
            if lead.estimated_property_value < 0:
                raise ValidationError(
                    _("Estimated Property Value cannot be negative.")
                )
            
    @api.constrains(
        "preferred_developer_id",
        "preferred_project_id",
        "final_developer_id",
        "final_project_id",
    )
    def _check_project_developer_consistency(self):
        for lead in self:
            if (
                lead.preferred_project_id
                and lead.preferred_project_id.developer_id
                != lead.preferred_developer_id
            ):
                raise ValidationError(
                    _(
                        "The preferred project does not belong to "
                        "the selected preferred developer."
                    )
                )

            if (
                lead.final_project_id
                and lead.final_project_id.developer_id
                != lead.final_developer_id
            ):
                raise ValidationError(
                    _(
                        "The final project does not belong to "
                        "the selected final developer."
                    )
                )
            
    @api.onchange("preferred_developer_id")
    def _onchange_preferred_developer_id(self):
        if (
            self.preferred_project_id
            and self.preferred_project_id.developer_id
            != self.preferred_developer_id
        ):
            self.preferred_project_id = False


    @api.onchange("final_developer_id")
    def _onchange_final_developer_id(self):
        if (
            self.final_project_id
            and self.final_project_id.developer_id
            != self.final_developer_id
        ):
            self.final_project_id = False

    def action_view_contact_attempts(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": _("Contact Attempts"),
            "res_model": "brokerage.crm.contact.attempt",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {
                "default_lead_id": self.id,
            },
        }

    def action_view_brokerage_meetings(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": _("Meetings"),
            "res_model": "brokerage.crm.meeting",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {
                "default_lead_id": self.id,
            },
        }


    def action_view_assignment_history(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": _("Assignment History"),
            "res_model": "brokerage.crm.assignment.history",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {
                "default_lead_id": self.id,
                "create": False,
                "edit": False,
                "delete": False,
            },
        }

    def action_recover_last_assignment(self):
        self.ensure_one()
        history = self.env[
            "brokerage.crm.assignment.history"
        ].sudo().search(
            [("lead_id", "=", self.id)],
            order="assigned_datetime desc, id desc",
            limit=1,
        )
        if not history:
            raise ValidationError(_("No assignment is available to recover."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Recover Previous Assignment"),
            "res_model": "brokerage.crm.assignment.recovery.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_lead_id": self.id,
                "default_assignment_history_id": history.id,
            },
        }
