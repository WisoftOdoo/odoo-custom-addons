def migrate(cr, version):
    cr.execute(
        """
        UPDATE brokerage_crm_contact_attempt AS attempt
           SET method_id = method.id
          FROM brokerage_crm_contact_method AS method
         WHERE attempt.method_id IS NULL
           AND method.code = COALESCE(attempt.method, 'call')
        """
    )
    cr.execute(
        """
        UPDATE brokerage_crm_contact_attempt AS attempt
           SET method_id = method.id
          FROM brokerage_crm_contact_method AS method
         WHERE attempt.method_id IS NULL
           AND method.code = 'other'
        """
    )
    cr.execute(
        """
        UPDATE brokerage_crm_meeting AS meeting
           SET meeting_type_id = meeting_type.id
          FROM brokerage_crm_meeting_type AS meeting_type
         WHERE meeting.meeting_type_id IS NULL
           AND meeting_type.code = COALESCE(meeting.meeting_type, 'office')
        """
    )
    cr.execute(
        """
        UPDATE brokerage_crm_meeting AS meeting
           SET meeting_type_id = meeting_type.id
          FROM brokerage_crm_meeting_type AS meeting_type
         WHERE meeting.meeting_type_id IS NULL
           AND meeting_type.code = 'other'
        """
    )

