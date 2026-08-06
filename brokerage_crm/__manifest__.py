{
    "name": "Wisoft Brokerage CRM",
    "version": "19.0.1.22.0",
    "category": "Sales/CRM",
    "summary": "Off-plan brokerage lead management workflow",
    "author": "Tranquil",
    "license": "LGPL-3",
    "depends": [
        "crm",
        "utm",
        "calendar",
        "sales_team",
        "sale_crm",
        "mail",
        "resource",
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
        "data/crm_contact_method_data.xml",
        "data/crm_meeting_type_data.xml",
        "data/crm_meeting_outcome_data.xml",
        "data/crm_booking_master_data.xml",
        "data/customer_requirement_option_data.xml",
        "data/crm_activity_data.xml",
        "data/email_notification_data.xml",
        "data/crm_sla_rule_data.xml",
        "data/telephony_data.xml",
        "data/crm_round_robin_data.xml",

        # Normal models, views and actions.
        "views/brokerage_developer_views.xml",
        "views/brokerage_project_views.xml",
        "views/utm_source_views.xml",
        "views/crm_lead_status_views.xml",
        "views/crm_lead_quality_views.xml",
        "views/crm_customer_requirement_option_views.xml",
        "views/crm_interaction_master_views.xml",
        "views/crm_booking_master_views.xml",
        "views/crm_team_hierarchy_views.xml",
        "views/crm_round_robin_views.xml",
        "views/crm_sla_rule_views.xml",
        "views/brokerage_telephony_views.xml",
        "views/res_config_settings_views.xml",
        "views/whatsapp_notification_views.xml",
        "views/email_notification_views.xml",
        "views/res_users_views.xml",
        "views/crm_meeting_views.xml",

        # Wizard actions must load before crm_lead_views.xml.
        "views/crm_wizard_views.xml",

        # References wizard actions.
        "views/crm_lead_views.xml",

        # Menus reference all preceding actions.
        "views/crm_configuration_menu.xml",

        "data/crm_sla_cron.xml",
        "data/lead_quality_aging_cron.xml",
        "data/whatsapp_cron.xml",
        "data/email_notification_cron.xml",
    ],
    "application": False,
    "installable": True,
}
