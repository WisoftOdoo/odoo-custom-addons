def migrate(cr, version):
    # Place the new manager escalation between the existing Team Leader
    # escalation and cross-team reassignment wherever an integer gap exists.
    cr.execute(
        """
        UPDATE brokerage_crm_sla_rule
           SET manager_escalation_minutes = CASE
               WHEN escalation_minutes > 0
                AND reassignment_minutes - escalation_minutes > 1
               THEN escalation_minutes
                    + ((reassignment_minutes - escalation_minutes) / 2)
               ELSE 0
           END
        """
    )

    # Supervisors never participate in agent rotation. Existing live data used
    # the standard team responsible field for Sales Managers, so remove any
    # such accidental memberships without changing queue counters.
    cr.execute(
        """
        DELETE FROM brokerage_crm_round_robin_agent AS agent
              USING brokerage_crm_round_robin AS queue,
                    crm_team AS team
              WHERE agent.round_robin_id = queue.id
                AND queue.team_id = team.id
                AND agent.user_id IN (
                    team.user_id,
                    team.brokerage_team_leader_id
                )
        """
    )
    cr.execute(
        """
        DELETE FROM brokerage_round_robin_user_rel AS member
              USING brokerage_crm_round_robin AS queue,
                    crm_team AS team
              WHERE member.round_robin_id = queue.id
                AND queue.team_id = team.id
                AND member.user_id IN (
                    team.user_id,
                    team.brokerage_team_leader_id
                )
        """
    )
