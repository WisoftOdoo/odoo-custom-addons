def migrate(cr, version):
    cr.execute("""
        UPDATE crm_lead AS lead
           SET sla_cycle_active = TRUE
          FROM crm_stage AS stage
         WHERE lead.stage_id = stage.id
           AND stage.brokerage_code = 'assigned'
           AND lead.user_id IS NOT NULL
           AND lead.assigned_datetime IS NOT NULL
           AND lead.assignment_type IN (
               'round_robin',
               'reassignment',
               'not_interested_reassignment'
           )
    """)
