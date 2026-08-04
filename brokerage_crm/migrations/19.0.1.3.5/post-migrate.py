def migrate(cr, version):
    cr.execute(
        """
        INSERT INTO brokerage_crm_round_robin_agent (
            round_robin_id,
            user_id,
            sequence,
            create_uid,
            write_uid,
            create_date,
            write_date
        )
        SELECT
            relation.round_robin_id,
            relation.user_id,
            ROW_NUMBER() OVER (
                PARTITION BY relation.round_robin_id
                ORDER BY relation.user_id
            ) * 10,
            1,
            1,
            NOW() AT TIME ZONE 'UTC',
            NOW() AT TIME ZONE 'UTC'
        FROM brokerage_round_robin_user_rel AS relation
        WHERE NOT EXISTS (
            SELECT 1
            FROM brokerage_crm_round_robin_agent AS agent
            WHERE agent.round_robin_id = relation.round_robin_id
              AND agent.user_id = relation.user_id
        )
        """
    )
