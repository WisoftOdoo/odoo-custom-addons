import logging

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


_logger = logging.getLogger(__name__)


class BrokerageCrmAssignmentHistory(models.Model):
    _name = "brokerage.crm.assignment.history"
    _description = "CRM Assignment History"
    _order = "assigned_datetime desc, id desc"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        string="Lead / Opportunity",
        required=True,
        ondelete="cascade",
        index=True,
    )

    source_id = fields.Many2one(
        comodel_name="utm.source",
        string="Lead Source",
        ondelete="set null",
        index=True,
    )

    previous_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Previous Salesperson",
        ondelete="set null",
    )

    new_user_id = fields.Many2one(
        comodel_name="res.users",
        string="New Salesperson",
        required=True,
        ondelete="restrict",
    )

    previous_team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Previous Sales Team",
        ondelete="set null",
    )

    new_team_id = fields.Many2one(
        comodel_name="crm.team",
        string="New Sales Team",
        required=True,
        ondelete="restrict",
    )

    assignment_type = fields.Selection(
        selection=[
            ("round_robin", "Round Robin"),
            ("manual", "Manual"),
            ("referral", "Referral"),
            ("walk_in", "Walk-in"),
            ("bulk", "Bulk Distribution"),
            ("reassignment", "Reassignment"),
            (
                "not_interested_reassignment",
                "Not Interested Reassignment",
            ),
            ("solo_campaign", "Solo Campaign"),
            ("recovery", "Assignment Recovery"),
        ],
        required=True,
        index=True,
    )

    assigned_datetime = fields.Datetime(
        string="Assigned Date/Time",
        required=True,
        default=fields.Datetime.now,
        index=True,
    )

    assigned_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Assigned By",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
    )

    reason = fields.Text()

    round_robin_id = fields.Many2one(
        comodel_name="brokerage.crm.round.robin",
        string="Round Robin Configuration",
        ondelete="set null",
    )

    round_robin_position = fields.Integer(
        string="Round Robin Position",
    )

    previous_stage_id = fields.Many2one(
        comodel_name="crm.stage",
        string="Previous Stage",
        ondelete="set null",
    )

    new_stage_id = fields.Many2one(
        comodel_name="crm.stage",
        string="New Stage",
        ondelete="set null",
    )

    before_snapshot = fields.Json(
        string="Before Assignment Snapshot",
        readonly=True,
        copy=False,
    )

    after_snapshot = fields.Json(
        string="After Assignment Snapshot",
        readonly=True,
        copy=False,
    )

    is_recovered = fields.Boolean(
        string="Recovered",
        readonly=True,
        copy=False,
        index=True,
    )

    recovered_at = fields.Datetime(
        string="Recovered At",
        readonly=True,
        copy=False,
    )

    recovered_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Recovered By",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    recovery_reason = fields.Text(
        readonly=True,
        copy=False,
    )

    recovery_history_id = fields.Many2one(
        comodel_name="brokerage.crm.assignment.history",
        string="Recovery Audit Entry",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    odoo_notification_message_id = fields.Many2one(
        comodel_name="mail.message",
        string="Odoo Assignment Notification",
        readonly=True,
        copy=False,
        ondelete="set null",
        help=(
            "The single targeted Odoo inbox/mobile notification generated "
            "for this assignment event."
        ),
    )

    odoo_notification_sent_at = fields.Datetime(
        string="Odoo Notification Sent At",
        readonly=True,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        histories = super().create(vals_list)
        histories._notify_new_assignee_in_odoo_once()
        histories._queue_new_assignee_email_once()
        return histories

    def _queue_new_assignee_email_once(self):
        """Queue one independent email for every assignment audit event."""
        for history in self.sudo():
            if (
                not history.lead_id
                or not history.new_user_id
                or not history.new_user_id.active
                or history.new_user_id.share
            ):
                continue
            try:
                self.env[
                    "brokerage.crm.email.notification"
                ].sudo().queue_assignment(history)
            except Exception:
                # Assignment must never roll back because an alert channel
                # is temporarily unavailable.
                _logger.exception(
                    "Could not queue assignment email for history %s",
                    history.id,
                )
        return True

    def _notify_new_assignee_in_odoo_once(self):
        """Send one persistent Odoo notification for each assignment event.

        SLA reminders deliberately do not use this helper: their existing
        ``mail.activity`` already creates Odoo inbox, desktop, web-push and
        mobile notifications. Keeping assignment notifications on their audit
        row gives us a durable idempotency marker without creating an unwanted
        acknowledgement activity.
        """
        for history in self.sudo():
            # Odoo 19 can defer stored writes until a flush is required. Flush
            # the idempotency marker before checking it with a row lock.
            history.flush_recordset(["odoo_notification_message_id"])
            self.env.cr.execute(
                """
                    SELECT odoo_notification_message_id
                      FROM brokerage_crm_assignment_history
                     WHERE id = %s
                     FOR UPDATE
                """,
                [history.id],
            )
            stored_message_id = self.env.cr.fetchone()[0]
            if stored_message_id:
                continue

            lead = history.lead_id.sudo()
            user = history.new_user_id.sudo()
            if not lead or not user or not user.active or user.share:
                continue

            is_reassignment = history.assignment_type in (
                "reassignment",
                "not_interested_reassignment",
                "recovery",
            )
            subject = (
                _("CRM Lead Reassigned: %s") % lead.display_name
                if is_reassignment
                else _("New CRM Lead Assigned: %s") % lead.display_name
            )
            heading = (
                _("CRM Lead Reassigned")
                if is_reassignment
                else _("New CRM Lead Assigned")
            )
            body = Markup(
                "<p><b>%(heading)s</b></p>"
                "<p>%(lead_label)s: %(lead)s<br/>"
                "%(customer_label)s: %(customer)s<br/>"
                "%(team_label)s: %(team)s<br/>"
                "%(salesperson_label)s: %(salesperson)s<br/>"
                "%(reason_label)s: %(reason)s</p>"
                "<p>%(instruction)s</p>"
            ) % {
                "heading": heading,
                "lead_label": _("Lead"),
                "lead": lead.display_name,
                "customer_label": _("Customer"),
                "customer": lead.contact_name or lead.partner_name or "-",
                "team_label": _("Sales team"),
                "team": history.new_team_id.display_name,
                "salesperson_label": _("Salesperson"),
                "salesperson": user.display_name,
                "reason_label": _("Assignment reason"),
                "reason": history.reason or "-",
                "instruction": _(
                    "Open the lead, contact the customer, and update its "
                    "progress in CRM."
                ),
            }
            message = lead.message_notify(
                partner_ids=user.partner_id.ids,
                author_id=history.assigned_by_id.partner_id.id,
                body=body,
                subject=subject,
                model_description=_("CRM Lead"),
                force_record_name=lead.display_name,
                notify_skip_followers=True,
                skip_existing=True,
            )
            if message:
                history.write({
                    "odoo_notification_message_id": message.id,
                    "odoo_notification_sent_at": fields.Datetime.now(),
                })
        return True

    def _check_recovery_allowed(self):
        self.ensure_one()
        if not self.env.user.has_group(
            "brokerage_crm.group_brokerage_sales_manager"
        ):
            raise AccessError(_(
                "Only a Brokerage Configuration Manager can recover an "
                "assignment."
            ))
        if self.assignment_type not in (
            "reassignment",
            "not_interested_reassignment",
        ):
            raise ValidationError(_(
                "Only a reassignment can be recovered."
            ))
        if not self.before_snapshot:
            raise ValidationError(_(
                "This historical assignment predates recovery snapshots and "
                "cannot be restored automatically."
            ))
        if self.is_recovered:
            raise ValidationError(_("This reassignment was already recovered."))

        latest = self.sudo().search(
            [("lead_id", "=", self.lead_id.id)],
            order="assigned_datetime desc, id desc",
            limit=1,
        )
        if latest != self:
            raise ValidationError(_(
                "Only the latest assignment can be recovered."
            ))

        lead = self.lead_id.sudo()
        if (
            lead.user_id != self.new_user_id
            or lead.team_id != self.new_team_id
        ):
            raise ValidationError(_(
                "The lead assignment has changed since this record was "
                "created and cannot be recovered automatically."
            ))
        if lead._stage_code(lead.stage_id) != "assigned":
            raise ValidationError(_(
                "Recovery is allowed only while the lead is still in the "
                "Assigned stage. Use the manager correction tools if the new "
                "salesperson has already progressed it."
            ))
        if (
            lead._current_assignment_contact_attempts()
            or lead._current_assignment_meetings()
        ):
            raise ValidationError(_(
                "The new salesperson has already recorded activity for this "
                "assignment. Automatic recovery is blocked to protect that "
                "work."
            ))
        return lead

    def action_recover_assignment(self, reason):
        self.ensure_one()
        if not (reason or "").strip():
            raise ValidationError(_("Enter a recovery reason."))

        lead = self._check_recovery_allowed()
        current_snapshot = lead._brokerage_assignment_snapshot()
        restored_values = lead._brokerage_assignment_snapshot_values(
            self.before_snapshot
        )
        restored_stage_id = restored_values.pop("stage_id", False)
        restored_user_id = restored_values.get("user_id")
        restored_team_id = restored_values.get("team_id")
        if not restored_user_id or not restored_team_id or not restored_stage_id:
            raise ValidationError(_(
                "The previous salesperson, team, or stage no longer exists. "
                "Use the manual Reassign and Correct Stage actions instead."
            ))

        # Never reactivate an old timer during a recovery. Managers may start
        # a new assignment cycle later through the normal Reassign action.
        restored_values["sla_cycle_active"] = False
        restored_values["not_interested_reassignment_done"] = bool(
            lead.not_interested_reassignment_done
            or restored_values.get("not_interested_reassignment_done")
        )

        recovered_at = fields.Datetime.now()
        lead._clear_open_brokerage_sla_activities()
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write(restored_values)
        lead.with_context(
            skip_assignment_history=True,
            skip_round_robin=True,
            brokerage_workflow_action=True,
        ).write({"stage_id": restored_stage_id})

        recovery_history = self.sudo().create({
            "lead_id": lead.id,
            "source_id": lead.source_id.id or False,
            "previous_user_id": current_snapshot.get("user_id") or False,
            "new_user_id": restored_user_id,
            "previous_team_id": current_snapshot.get("team_id") or False,
            "new_team_id": restored_team_id,
            "previous_stage_id": current_snapshot.get("stage_id") or False,
            "new_stage_id": restored_stage_id,
            "assignment_type": "recovery",
            "assigned_datetime": recovered_at,
            "assigned_by_id": self.env.user.id,
            "reason": reason.strip(),
            "before_snapshot": current_snapshot,
            "after_snapshot": lead._brokerage_assignment_snapshot(),
        })
        self.sudo().write({
            "is_recovered": True,
            "recovered_at": recovered_at,
            "recovered_by_id": self.env.user.id,
            "recovery_reason": reason.strip(),
            "recovery_history_id": recovery_history.id,
        })

        lead.message_post(
            body=Markup(_(
                "Assignment recovered by <b>%(manager)s</b>: "
                "<b>%(current_user)s</b> / <b>%(current_team)s</b> was "
                "restored to <b>%(restored_user)s</b> / "
                "<b>%(restored_team)s</b> at stage "
                "<b>%(restored_stage)s</b>.<br/>Reason: %(reason)s"
                "<br/>The old SLA timer was not restarted."
            )) % {
                "manager": self.env.user.display_name,
                "current_user": self.new_user_id.display_name,
                "current_team": self.new_team_id.display_name,
                "restored_user": lead.user_id.display_name,
                "restored_team": lead.team_id.display_name,
                "restored_stage": lead.stage_id.display_name,
                "reason": reason.strip(),
            },
            subtype_xmlid="mail.mt_note",
            author_id=self.env.user.partner_id.id,
        )
        lead._queue_brokerage_whatsapp_assignment(
            lead.user_id,
            _("Assignment recovery: %s") % reason.strip(),
        )
        return recovery_history
