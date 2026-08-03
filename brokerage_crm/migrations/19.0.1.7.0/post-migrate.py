def migrate(cr, version):
    # If a Team Leader was configured in the temporary two-level hierarchy,
    # move that user back to Odoo's native Team Leader field. When it was left
    # empty, preserve the existing native value for manual review.
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'crm_team'
           AND column_name = 'brokerage_team_leader_id'
        """
    )
    if cr.fetchone():
        cr.execute(
            """
            UPDATE crm_team
               SET user_id = brokerage_team_leader_id,
                   brokerage_team_leader_id = NULL
             WHERE brokerage_team_leader_id IS NOT NULL
            """
        )

    # Remove the obsolete Sales Manager step without making customers wait
    # until the old, later reassignment time. Its configured threshold becomes
    # the new post-Team-Leader cross-team threshold when it was valid.
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'brokerage_crm_sla_rule'
           AND column_name = 'manager_escalation_minutes'
        """
    )
    if cr.fetchone():
        cr.execute(
            """
            UPDATE brokerage_crm_sla_rule
               SET reassignment_minutes = manager_escalation_minutes
             WHERE manager_escalation_minutes > escalation_minutes
               AND (
                   reassignment_minutes = 0
                   OR manager_escalation_minutes < reassignment_minutes
               )
            """
        )
