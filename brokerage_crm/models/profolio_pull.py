import json
import logging
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
    def _endpoint(self, source):
        if source == "bayut":
            return "https://www.bayut.com/api-v7/stats/website-client-leads"
        return "https://dubizzle.com/profolio/api-v7/stats/website-client-leads"

    @api.model
    def _import_item(self, item, source, campaign, utm_source):
        external_id = str(item.get("lead_id") or "").strip()
        if not external_id or self.sudo().search_count([("external_lead_id", "=", external_id), ("source", "=", source)]):
            return False
        details = item.get("inquirer_details") or {}
        listing = item.get("listing_details") or {}
        name = str(details.get("name") or "Profolio Lead %s" % external_id)
        values = {
            "name": name,
            "contact_name": details.get("name") or False,
            "email_from": details.get("email") or False,
            "phone": details.get("cell") or False,
            "description": details.get("message") or False,
            "source_id": utm_source.id,
            "campaign_id": campaign.id or False,
            "assignment_type": self._param("profolio_default_assignment_type", "manual"),
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
        return True

    @api.model
    def _pull_source(self, source):
        token = str(self._param("profolio_%s_api_key" % source, "") or "").strip()
        if not token:
            _logger.warning("Profolio %s pull is enabled but its API key is missing", source)
            return
        campaign = self._campaign(source)
        if not campaign:
            _logger.warning("Profolio %s pull skipped: default campaign is missing", source)
            return
        headers = {"Authorization": "Bearer %s" % token, "Accept": "application/json"}
        timestamp = self._timestamp(source)
        latest = timestamp
        for target in ("listing", "agent", "agency"):
            for lead_type in ("email", "whatsapp", "sms", "phone"):
                params = {"timestamp": timestamp, "target": target, "type": lead_type, "is_trulead": 1}
                response = requests.get(self._endpoint(source), params=params, headers=headers, timeout=(5, 15))
                if response.status_code == 429:
                    _logger.warning("Profolio %s rate limited: %s", source, response.json().get("retry_after"))
                    return
                response.raise_for_status()
                items = response.json() or []
                for item in items:
                    self._import_item(item, source, campaign, self._source(source))
                    latest = max(latest, str(item.get("date_time") or latest))
        self.env["ir.config_parameter"].sudo().set_param("brokerage_crm.profolio_%s_last_timestamp" % source, latest)

    @api.model
    def _cron_pull_leads(self):
        if not self._enabled():
            return True
        for source in ("bayut", "dubizzle"):
            try:
                with self.env.cr.savepoint():
                    self._pull_source(source)
            except Exception:
                _logger.exception("Profolio %s lead pull failed", source)
        return True
