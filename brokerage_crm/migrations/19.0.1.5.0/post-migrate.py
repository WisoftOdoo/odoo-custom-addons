def migrate(cr, version):
    cr.execute(
        """
        UPDATE brokerage_crm_meeting
           SET recorded_datetime = create_date
         WHERE recorded_datetime IS NULL
        """
    )
    cr.execute(
        """
        UPDATE brokerage_whatsapp_notification
           SET retry_cycle_attempt_count = attempt_count
         WHERE retry_cycle_attempt_count = 0
           AND attempt_count > 0
        """
    )
