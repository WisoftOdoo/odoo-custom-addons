import json
import logging
import time
from datetime import datetime, timedelta

import requests

from odoo import api, fields, models, tools, _

_logger = logging.getLogger(__name__)


class ProfolioPullLead(models.Model):
    _name = "brokerage.profolio.pull.lead"
    _description = "Profolio Pulled Lead"
    _order = "lead_datetime desc, id desc"

    external_lead_id = fields.Char(required=True, readonly=True, index=True)
    source = fields.Selection([("bayut", "Bayut"), ("dubizzle", "dubizzle")], required=True, readonly=True)
    lead_datetime = fields.Datetime(readonly=True, index=True)
    crm_lead_id = fields.Many2one("crm.lead", readonly=True, ondelete="set null")
    response_payload = fields.Text(readonly=True)
    state = fields.Selection([("imported", "Imported"), ("failed", "Failed")], default="imported", readonly=True)
    error = fields.Text(readonly=True)

    _external_unique = models.Constraint("UNIQUE(external_lead_id, source)", "This Profolio lead was already imported.")

    @api.model
    def _param(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param("brokerage_crm.%s" % key, default)

    @api.model
    def _enabled(self):
        return tools.str2bool(self._param("profolio_pull_enabled", "False"), default=False)

    @api.model
    def _campaign(self, source):
        name = "Bayut Leads" if source == "bayut" else "dubizzle Leads"
        return self.env["utm.campaign"].sudo().search([("name", "=", name)], limit=1)

    @api.model
    def _source(self, source):
        name = "Bayut" if source == "bayut" else "dubizzle"
        return self.env["utm.source"].sudo().search([("name", "=", name)], limit=1) or self.env["utm.source"].sudo().create({"name": name})

    @api.model
    def _timestamp(self, source):
        key = "profolio_%s_last_timestamp" % source
        value = self._param(key, "")
        if value:
            return value
        return (datetime.utcnow() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")

    @api.model
    def _endpoint(self):
        return "https://www.bayut.com/api-v7/stats/website-client-leads"

    @api.model
    def _import_item(self, item):
        source = str(item.get("source") or "").strip().lower()
        if source not in ("bayut", "dubizzle"):
            _logger.warning("Skipping Profolio lead with unsupported source: %s", source)
            return "unsupported"
        campaign = self._campaign(source)
        if not campaign:
            _logger.warning("Profolio %s lead skipped: default campaign is missing", source)
            return "missing_campaign"
        utm_source = self._source(source)
        external_id = str(item.get("lead_id") or "").strip()
        if not external_id or self.sudo().search_count([("external_lead_id", "=", external_id), ("source", "=", source)]):
            return "duplicate"
        details = item.get("inquirer_details") or {}
        listing = item.get("listing_details") or {}
        name = str(details.get("name") or "Profolio Lead %s" % external_id)
        policy = self.env["brokerage.meta.campaign.rule"].sudo().policy_for_utm_campaign(
            campaign, self.env.company,
        )
        assignment_type = self._param("profolio_default_assignment_type", "manual")
        if policy:
            assignment_type = "manual" if policy.routing_mode == "manual" else "round_robin"
        values = {
            "name": name,
            "contact_name": details.get("name") or False,
            "email_from": details.get("email") or False,
            "phone": details.get("cell") or False,
            "description": details.get("message") or False,
            "source_id": utm_source.id,
            "campaign_id": campaign.id or False,
            "assignment_type": assignment_type,
        }
        if listing:
            values["description"] = "%s\n\nListing: %s (%s)" % (values["description"] or "", listing.get("listing_reference") or "", listing.get("listing_id") or "")
        lead = self.env["crm.lead"].sudo().create(values)
        self.sudo().create({
            "external_lead_id": external_id, "source": source,
            "lead_datetime": item.get("date_time") or fields.Datetime.now(),
            "crm_lead_id": lead.id,
            "response_payload": json.dumps(item, ensure_ascii=False)[:12000],
        })
        return "imported"

    @api.model
    def _pull_unified(self):
        retry_key = "profolio_unified_retry_until"
        retry_until = self._param(retry_key, "")
        if retry_until:
            try:
                if datetime.utcnow() < datetime.strptime(retry_until, "%Y-%m-%d %H:%M:%S"):
                    _logger.info("Profolio unified pull paused until %s", retry_until)
                    return
            except ValueError:
                self.env["ir.config_parameter"].sudo().set_param("brokerage_crm.%s" % retry_key, "")
        token = str(self._param("profolio_bayut_api_key", "") or "").strip()
        if not token:
            _logger.warning("Profolio unified pull is enabled but its API key is missing")
            return
        headers = {"Authorization": "Bearer %s" % token, "Accept": "application/json"}
        timestamp = self._param("profolio_unified_last_timestamp", "") or (
            datetime.utcnow() - timedelta(minutes=15)
        ).strftime("%Y-%m-%d %H:%M:%S")
        latest = timestamp
        request_number = 0
        api_items = imported = duplicates = unsupported = missing_campaign = 0
        for target in ("listing", "agent", "agency"):
            for lead_type in ("email", "whatsapp", "sms", "phone"):
                if request_number:
                    time.sleep(60)
                request_number += 1
                params = {"timestamp": timestamp, "target": target, "type": lead_type, "is_trulead": 1}
                response = requests.get(self._endpoint(), params=params, headers=headers, timeout=(5, 30))
                if response.status_code == 429:
                    try:
                        retry_after = max(60, int((response.json() or {}).get("retry_after", 60)))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        retry_after = 60
                    retry_until = datetime.utcnow() + timedelta(seconds=retry_after)
                    self.env["ir.config_parameter"].sudo().set_param(
                        "brokerage_crm.%s" % retry_key,
                        retry_until.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    _logger.warning("Profolio unified pull rate limited; retrying after %s seconds", retry_after)
                    return
                response.raise_for_status()
                items = response.json() or []
                for item in items:
                    api_items += 1
                    result = self._import_item(item)
                    imported += result == "imported"
                    duplicates += result == "duplicate"
                    unsupported += result == "unsupported"
                    missing_campaign += result == "missing_campaign"
                    latest = max(latest, str(item.get("date_time") or latest))
        self.env["ir.config_parameter"].sudo().set_param("brokerage_crm.profolio_unified_last_timestamp", latest)
        self.env["ir.config_parameter"].sudo().set_param("brokerage_crm.%s" % retry_key, "")
        _logger.info(
            "Profolio unified pull completed: api_calls=%s, api_leads=%s, imported=%s, duplicates=%s, unsupported=%s, missing_campaign=%s",
            request_number, api_items, imported, duplicates, unsupported, missing_campaign,
        )

    @api.model
    def _cron_pull_leads(self):
        if not self._enabled():
            return True
        try:
            with self.env.cr.savepoint():
                self._pull_unified()
        except Exception:
            _logger.exception("Profolio unified lead pull failed")
        return True
