def migrate(cr, version):
    """Link legacy meeting outcome values to configurable outcomes."""
    cr.execute(
        """
        UPDATE brokerage_crm_meeting AS meeting
           SET outcome_id = outcome.id
          FROM brokerage_crm_meeting_outcome AS outcome
         WHERE meeting.outcome_id IS NULL
           AND outcome.code = COALESCE(meeting.outcome, 'other')
        """
    )
    cr.execute(
        """
        UPDATE brokerage_crm_meeting
           SET outcome_id = (
               SELECT id
                 FROM brokerage_crm_meeting_outcome
                WHERE code = 'other'
                LIMIT 1
           )
         WHERE outcome_id IS NULL
           AND outcome IS NOT NULL
        """
    )
    cr.execute(
        """
        UPDATE brokerage_crm_meeting_outcome
           SET active = FALSE
         WHERE code = 'other'
        """
    )
