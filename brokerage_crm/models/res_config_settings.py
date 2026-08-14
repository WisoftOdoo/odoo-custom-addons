import re

from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    brokerage_meta_enabled = fields.Boolean(
        string="Enable Meta Lead Ads",
        config_parameter="brokerage_crm.meta_enabled",
    )
    brokerage_meta_callback_url = fields.Char(
        string="Meta Callback URL",
        compute="_compute_brokerage_meta_callback_url",
        readonly=True,
    )
    brokerage_meta_verify_token = fields.Char(
        string="Webhook Verify Token",
        config_parameter="brokerage_crm.meta_verify_token",
        copy=False,
    )
    brokerage_meta_app_secret = fields.Char(
        string="Meta App Secret",
        config_parameter="brokerage_crm.meta_app_secret",
        copy=False,
    )
    brokerage_meta_page_access_token = fields.Char(
        string="Page Access Token",
        config_parameter="brokerage_crm.meta_page_access_token",
        copy=False,
    )
    brokerage_meta_page_id = fields.Char(
        string="Facebook Page ID",
        config_parameter="brokerage_crm.meta_page_id",
    )
    brokerage_meta_graph_version = fields.Char(
        string="Graph API Version",
        config_parameter="brokerage_crm.meta_graph_version",
        default="v24.0",
    )
    brokerage_meta_source_id = fields.Many2one(
        comodel_name="utm.source",
        string="Odoo Lead Source",
        config_parameter="brokerage_crm.meta_source_id",
        default=lambda self: self.env.ref(
            "brokerage_crm.lead_source_meta",
            raise_if_not_found=False,
        ),
    )
    brokerage_meta_request_timeout = fields.Integer(
        string="Graph API Response Timeout",
        config_parameter="brokerage_crm.meta_request_timeout",
        default=15,
    )
    brokerage_meta_max_attempts = fields.Integer(
        string="Maximum Processing Attempts",
        config_parameter="brokerage_crm.meta_max_attempts",
        default=5,
    )

    brokerage_telephony_provider_id = fields.Many2one(
        related="company_id.brokerage_telephony_provider_id",
        readonly=False,
        string="Default Telephony Provider",
    )

    brokerage_sla_enabled = fields.Boolean(
        string="Enable Assignment First-Contact SLA",
    )
    brokerage_sla_reminder_1_minutes = fields.Integer(
        string="Reminder 1 After",
    )
    brokerage_sla_reminder_2_minutes = fields.Integer(
        string="Reminder 2 After",
    )
    brokerage_sla_reminder_3_minutes = fields.Integer(
        string="Reminder 3 After",
    )
    brokerage_sla_escalation_minutes = fields.Integer(
        string="Team Leader Escalation After",
    )
    brokerage_sla_reassignment_minutes = fields.Integer(
        string="Cross-Team Reassignment After",
    )

    brokerage_lead_quality_aging_enabled = fields.Boolean(
        string="Enable Automatic Lead Quality Aging",
        config_parameter="brokerage_crm.lead_quality_aging_enabled",
        default=True,
    )
    brokerage_lead_quality_hot_days = fields.Integer(
        string="Hot Up To",
        config_parameter="brokerage_crm.lead_quality_hot_days",
        default=30,
    )
    brokerage_lead_quality_warm_days = fields.Integer(
        string="Warm Up To",
        config_parameter="brokerage_crm.lead_quality_warm_days",
        default=90,
    )

    brokerage_ultramsg_enabled = fields.Boolean(
        string="Enable UltraMsg Notifications",
        config_parameter="brokerage_crm.ultramsg_enabled",
    )
    brokerage_ultramsg_instance_id = fields.Char(
        string="UltraMsg Instance ID",
        config_parameter="brokerage_crm.ultramsg_instance_id",
        help="For example: instance123456",
    )
    brokerage_ultramsg_token = fields.Char(
        string="UltraMsg Token",
        config_parameter="brokerage_crm.ultramsg_token",
        copy=False,
    )
    brokerage_ultramsg_default_country_code = fields.Char(
        string="Default Country Code",
        config_parameter="brokerage_crm.ultramsg_default_country_code",
        default="971",
        help="Used for local user phone numbers. Enter digits only, without +.",
    )
    brokerage_ultramsg_connect_timeout = fields.Integer(
        string="Connection Timeout",
        config_parameter="brokerage_crm.ultramsg_connect_timeout",
        default=5,
    )
    brokerage_ultramsg_read_timeout = fields.Integer(
        string="Response Timeout",
        config_parameter="brokerage_crm.ultramsg_read_timeout",
        default=15,
    )
    brokerage_ultramsg_max_attempts = fields.Integer(
        string="Maximum Delivery Attempts",
        config_parameter="brokerage_crm.ultramsg_max_attempts",
        default=3,
    )
    brokerage_ultramsg_retry_base_minutes = fields.Integer(
        string="Initial Retry Delay",
        config_parameter="brokerage_crm.ultramsg_retry_base_minutes",
        default=5,
    )
    brokerage_ultramsg_retry_max_minutes = fields.Integer(
        string="Maximum Retry Delay",
        config_parameter="brokerage_crm.ultramsg_retry_max_minutes",
        default=60,
    )
    brokerage_ultramsg_failure_alert_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Delivery Failure Alert User",
        config_parameter="brokerage_crm.ultramsg_failure_alert_user_id",
        domain=[("share", "=", False), ("active", "=", True)],
        help=(
            "Receives an Odoo activity after WhatsApp delivery permanently "
            "fails. If empty, the lead's Sales Team manager is notified."
        ),
    )

    @api.model
    def _get_brokerage_default_sla_rule(self):
        rule = self.env.ref(
            "brokerage_crm.sla_rule_first_contact_default",
            raise_if_not_found=False,
        )
        return rule.sudo() if rule else rule

    @api.depends_context("company")
    def _compute_brokerage_meta_callback_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url",
            "",
        ).rstrip("/")
        for settings in self:
            settings.brokerage_meta_callback_url = (
                "%s/brokerage/api/v1/meta/webhook" % base_url
                if base_url else False
            )

    @api.model
    def get_values(self):
        values = super().get_values()
        parameters = self.env["ir.config_parameter"].sudo()
        values.update({
            "brokerage_lead_quality_aging_enabled": tools.str2bool(
                parameters.get_param(
                    "brokerage_crm.lead_quality_aging_enabled",
                    "True",
                ),
                default=True,
            ),
            "brokerage_lead_quality_hot_days": int(
                parameters.get_param(
                    "brokerage_crm.lead_quality_hot_days",
                    "30",
                )
            ),
            "brokerage_lead_quality_warm_days": int(
                parameters.get_param(
                    "brokerage_crm.lead_quality_warm_days",
                    "90",
                )
            ),
        })
        rule = self._get_brokerage_default_sla_rule()
        if rule:
            values.update({
                "brokerage_sla_enabled": rule.active,
                "brokerage_sla_reminder_1_minutes": (
                    rule.reminder_1_minutes
                ),
                "brokerage_sla_reminder_2_minutes": (
                    rule.reminder_2_minutes
                ),
                "brokerage_sla_reminder_3_minutes": (
                    rule.reminder_3_minutes
                ),
                "brokerage_sla_escalation_minutes": (
                    rule.escalation_minutes
                ),
                "brokerage_sla_reassignment_minutes": (
                    rule.reassignment_minutes
                ),
            })
        return values

    def _validate_brokerage_sla_timings(self):
        self.ensure_one()
        timings = [
            (
                _("Reminder 1"),
                self.brokerage_sla_reminder_1_minutes,
            ),
            (
                _("Reminder 2"),
                self.brokerage_sla_reminder_2_minutes,
            ),
            (
                _("Reminder 3"),
                self.brokerage_sla_reminder_3_minutes,
            ),
            (
                _("Team Leader Escalation"),
                self.brokerage_sla_escalation_minutes,
            ),
            (
                _("Cross-Team Reassignment"),
                self.brokerage_sla_reassignment_minutes,
            ),
        ]
        if any(minutes < 0 for _label, minutes in timings):
            raise ValidationError(_(
                "SLA timings cannot be negative. Use 0 to disable a step."
            ))

        previous_label = False
        previous_minutes = False
        for label, minutes in timings:
            if not minutes:
                continue
            if previous_minutes and minutes <= previous_minutes:
                raise ValidationError(_(
                    "%s must be later than %s."
                ) % (label, previous_label))
            previous_label = label
            previous_minutes = minutes

    def _validate_brokerage_lead_quality_aging(self):
        self.ensure_one()
        if not self.brokerage_lead_quality_aging_enabled:
            return
        hot_days = self.brokerage_lead_quality_hot_days
        warm_days = self.brokerage_lead_quality_warm_days
        if hot_days < 0 or warm_days < 0:
            raise ValidationError(_(
                "Lead quality aging thresholds cannot be negative."
            ))
        if warm_days <= hot_days:
            raise ValidationError(_(
                "Warm Up To must be greater than Hot Up To."
            ))

    def _validate_brokerage_meta_settings(self):
        self.ensure_one()
        if not self.brokerage_meta_enabled:
            return
        if not (self.brokerage_meta_verify_token or "").strip():
            raise ValidationError(_("Enter the Meta webhook verify token."))
        if not (self.brokerage_meta_app_secret or "").strip():
            raise ValidationError(_("Enter the Meta App Secret."))
        if not (self.brokerage_meta_page_access_token or "").strip():
            raise ValidationError(_("Enter the Meta Page access token."))
        page_id = (self.brokerage_meta_page_id or "").strip()
        if not page_id.isdigit():
            raise ValidationError(_(
                "The Facebook Page ID must contain digits only."
            ))
        if not re.fullmatch(
            r"v\d+\.\d+",
            (self.brokerage_meta_graph_version or "").strip(),
        ):
            raise ValidationError(_(
                "The Meta Graph API version must use a value such as v24.0."
            ))
        if not self.brokerage_meta_source_id:
            raise ValidationError(_("Select the Odoo source for Meta leads."))
        if self.brokerage_meta_request_timeout <= 0:
            raise ValidationError(_(
                "The Meta Graph API response timeout must be positive."
            ))
        if self.brokerage_meta_max_attempts <= 0:
            raise ValidationError(_(
                "Maximum Meta processing attempts must be positive."
            ))

    def set_values(self):
        for settings in self:
            settings._validate_brokerage_sla_timings()
            settings._validate_brokerage_lead_quality_aging()
            settings._validate_brokerage_meta_settings()
            if not settings.brokerage_ultramsg_enabled:
                continue
            instance_id = (
                settings.brokerage_ultramsg_instance_id or ""
            ).strip()
            token = (settings.brokerage_ultramsg_token or "").strip()
            country_code = re.sub(
                r"\D", "",
                settings.brokerage_ultramsg_default_country_code or "",
            )
            if not re.fullmatch(r"instance\d+", instance_id):
                raise ValidationError(_(
                    "UltraMsg Instance ID must use the format instance123456."
                ))
            if not token:
                raise ValidationError(_("Enter the UltraMsg token."))
            if not country_code:
                raise ValidationError(_(
                    "Enter a valid numeric default country code."
                ))
            if settings.brokerage_ultramsg_connect_timeout <= 0:
                raise ValidationError(_(
                    "The UltraMsg connection timeout must be positive."
                ))
            if settings.brokerage_ultramsg_read_timeout <= 0:
                raise ValidationError(_(
                    "The UltraMsg response timeout must be positive."
                ))
            if settings.brokerage_ultramsg_max_attempts <= 0:
                raise ValidationError(_(
                    "Maximum UltraMsg delivery attempts must be positive."
                ))
            if settings.brokerage_ultramsg_retry_base_minutes <= 0:
                raise ValidationError(_(
                    "The initial UltraMsg retry delay must be positive."
                ))
            if (
                settings.brokerage_ultramsg_retry_max_minutes
                < settings.brokerage_ultramsg_retry_base_minutes
            ):
                raise ValidationError(_(
                    "The maximum UltraMsg retry delay must be greater than or "
                    "equal to the initial retry delay."
                ))
        result = super().set_values()
        for settings in self:
            rule = settings._get_brokerage_default_sla_rule()
            if not rule:
                raise ValidationError(_(
                    "The default first-contact SLA rule is missing. "
                    "Upgrade the Brokerage CRM module and try again."
                ))
            rule.sudo().write({
                "active": settings.brokerage_sla_enabled,
                "reminder_1_minutes": (
                    settings.brokerage_sla_reminder_1_minutes
                ),
                "reminder_2_minutes": (
                    settings.brokerage_sla_reminder_2_minutes
                ),
                "reminder_3_minutes": (
                    settings.brokerage_sla_reminder_3_minutes
                ),
                "escalation_minutes": (
                    settings.brokerage_sla_escalation_minutes
                ),
                "reassignment_minutes": (
                    settings.brokerage_sla_reassignment_minutes
                ),
            })
        return result
