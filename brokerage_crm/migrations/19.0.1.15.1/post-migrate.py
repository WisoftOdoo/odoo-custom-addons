def migrate(cr, version):
    """Hide obsolete catch-all choices without breaking historical records."""
    cr.execute(
        """
        UPDATE brokerage_crm_contact_method
           SET active = FALSE
         WHERE code = 'other'
        """
    )
    cr.execute(
        """
        UPDATE brokerage_crm_meeting_type
           SET active = FALSE
         WHERE code = 'other'
        """
    )
