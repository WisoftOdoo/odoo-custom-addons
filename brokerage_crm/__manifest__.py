{
    "name": "Wisoft Brokerage CRM",
    "version": "19.0.1.3.1",
    "category": "Sales/CRM",
    "summary": "Off-plan brokerage lead management workflow",
    "author": "Wisoft",
    "license": "LGPL-3",
    "depends": [
        "crm",
        "utm",
        "calendar",
        "sales_team",
        "mail",
    ],    
    "data": [
        # Security must load first.
        "security/brokerage_crm_security.xml",
        "security/ir.model.access.csv",

        # Master data.
        "data/utm_source_data.xml",
        "data/lead_status_data.xml",
        "data/crm_stage_data.xml",
        "data/lead_quality_data.xml",
        "data/crm_activity_data.xml",
        "data/crm_sla_rule_data.xml",

        # Normal models, views and actions.
        "views/brokerage_developer_views.xml",
        "views/brokerage_project_views.xml",
        "views/utm_source_views.xml",
        "views/crm_lead_status_views.xml",
        "views/crm_lead_quality_views.xml",
        "views/crm_round_robin_views.xml",
        "views/crm_sla_rule_views.xml",
        "views/res_config_settings_views.xml",
        "views/whatsapp_notification_views.xml",
        "views/crm_meeting_views.xml",

        # Wizard actions must load before crm_lead_views.xml.
        "views/crm_wizard_views.xml",

        # References wizard actions.
        "views/crm_lead_views.xml",

        # Menus reference all preceding actions.
        "views/crm_configuration_menu.xml",

        "data/crm_sla_cron.xml",
        "data/whatsapp_cron.xml",
    ],
    "application": False,
    "installable": True,
}
