from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Retire the former KYC and Booking stages without losing leads."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    stage_model = env["crm.stage"].with_context(active_test=False)
    lead_model = env["crm.lead"].with_context(active_test=False)

    obsolete_menus = env["ir.ui.menu"].browse([
        menu.id
        for xmlid in (
            "brokerage_crm.menu_brokerage_booking_payment_methods",
            "brokerage_crm.menu_brokerage_booking_documentation_statuses",
        )
        if (menu := env.ref(xmlid, raise_if_not_found=False))
    ])
    obsolete_menus.unlink()

    # Normalize workflow codes by business stage name. Some databases had
    # stale codes copied onto the wrong stages, so names are the safe upgrade
    # anchor and prevent Contacted (for example) being mistaken for legacy KYC.
    workflow_codes = {
        "New Lead": "new",
        "New": "new",
        "Assigned": "assigned",
        "Contact Attempted": "contact_attempted",
        "Contacted": "contacted",
        "Meeting Scheduled": "meeting_scheduled",
        "Meeting Completed": "meeting_completed",
        "Forecast": "forecast",
        "Hot / Booking Expected": "hot",
        "Closed Won": "won",
        "Not Interested": "not_interested",
    }
    for stage_name, code in workflow_codes.items():
        stage_model.search([("name", "=ilike", stage_name)]).write({
            "brokerage_code": code,
        })

    legacy_stages = stage_model.search([
        ("name", "in", ("KYC in Progress", "Booking / Documentation")),
    ])
    unmigrated_stage_ids = set()
    for lead in lead_model.search([("stage_id", "in", legacy_stages.ids)]):
        hot_stage = lead._find_brokerage_stage("hot", team=lead.team_id)
        if not hot_stage:
            hot_stage = stage_model.search(
                [("brokerage_code", "=", "hot")],
                order="sequence, id",
                limit=1,
            )
        if not hot_stage:
            unmigrated_stage_ids.add(lead.stage_id.id)
            continue
        lead.with_context(
            brokerage_workflow_action=True,
            skip_assignment_history=True,
            skip_round_robin=True,
            tracking_disable=True,
        ).write({"stage_id": hot_stage.id})

    removable_stages = legacy_stages.filtered(
        lambda stage: stage.id not in unmigrated_stage_ids
        and not lead_model.search_count([("stage_id", "=", stage.id)])
    )
    removable_stages.unlink()

    # The API now accepts one contact channel. Recompute existing stored keys
    # so email-only and phone-only records participate in deduplication too.
    all_leads = lead_model.search([])
    if all_leads:
        all_leads._compute_brokerage_deduplication_key()
