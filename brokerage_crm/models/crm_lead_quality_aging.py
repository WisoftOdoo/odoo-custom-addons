import logging

from odoo import api, fields, models, tools


_logger = logging.getLogger(__name__)


class CrmLeadQualityAging(models.Model):
    _inherit = "crm.lead"

    _brokerage_quality_aging_codes = ("hot", "warm", "cold")

    @api.model
    def _brokerage_lead_quality_aging_config(self):
        parameters = self.env["ir.config_parameter"].sudo()
        enabled = tools.str2bool(
            parameters.get_param(
                "brokerage_crm.lead_quality_aging_enabled",
                "True",
            ),
            default=True,
        )
        try:
            hot_days = int(parameters.get_param(
                "brokerage_crm.lead_quality_hot_days",
                "30",
            ))
            warm_days = int(parameters.get_param(
                "brokerage_crm.lead_quality_warm_days",
                "90",
            ))
        except (TypeError, ValueError):
            _logger.error(
                "Automatic lead quality aging is disabled for this run "
                "because its thresholds are not valid integers."
            )
            return False, 30, 90
        if hot_days < 0 or warm_days <= hot_days:
            _logger.error(
                "Automatic lead quality aging is disabled for this run: "
                "Hot Up To must be non-negative and Warm Up To must be "
                "greater than Hot Up To."
            )
            return False, hot_days, warm_days
        return enabled, hot_days, warm_days

    @api.model
    def _brokerage_age_quality_records(self):
        qualities = self.env[
            "brokerage.crm.lead.quality"
        ].sudo().search([
            ("code", "in", list(self._brokerage_quality_aging_codes)),
            ("active", "=", True),
        ])
        quality_by_code = {quality.code: quality for quality in qualities}
        missing = set(self._brokerage_quality_aging_codes) - set(
            quality_by_code
        )
        if missing:
            _logger.error(
                "Automatic lead quality aging is disabled for this run "
                "because active quality records are missing for: %s.",
                ", ".join(sorted(missing)),
            )
            return {}
        return quality_by_code

    def _brokerage_is_age_quality_eligible(self):
        self.ensure_one()
        return bool(
            self.active
            and self.won_status == "pending"
            and not self.lead_status_id.is_invalid
            and self._stage_code(self.stage_id) != "not_interested"
        )

    @api.model
    def _brokerage_quality_code_for_age(
        self,
        age_days,
        hot_days,
        warm_days,
    ):
        if age_days <= hot_days:
            return "hot"
        if age_days <= warm_days:
            return "warm"
        return "cold"

    def _apply_brokerage_age_based_quality(self, evaluation_datetime=None):
        enabled, hot_days, warm_days = (
            self._brokerage_lead_quality_aging_config()
        )
        if not enabled:
            return 0
        quality_by_code = self._brokerage_age_quality_records()
        if not quality_by_code:
            return 0

        evaluation_datetime = fields.Datetime.to_datetime(
            evaluation_datetime or fields.Datetime.now()
        )
        leads_by_quality = {
            code: self.env["crm.lead"]
            for code in self._brokerage_quality_aging_codes
        }
        for lead in self:
            if (
                not lead.create_date
                or not lead._brokerage_is_age_quality_eligible()
            ):
                continue
            created_datetime = fields.Datetime.to_datetime(lead.create_date)
            age_days = max(
                0,
                (evaluation_datetime - created_datetime).days,
            )
            quality_code = lead._brokerage_quality_code_for_age(
                age_days,
                hot_days,
                warm_days,
            )
            if lead.lead_quality_id != quality_by_code[quality_code]:
                leads_by_quality[quality_code] |= lead

        updated_count = 0
        for quality_code, leads in leads_by_quality.items():
            if not leads:
                continue
            leads.sudo().with_context(
                brokerage_age_quality_update=True,
            ).write({
                "lead_quality_id": quality_by_code[quality_code].id,
            })
            updated_count += len(leads)
        return updated_count

    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        leads._apply_brokerage_age_based_quality()
        return leads

    @api.model
    def _cron_update_brokerage_lead_quality(self):
        leads = self.sudo().search([("active", "=", True)])
        return leads._apply_brokerage_age_based_quality()
