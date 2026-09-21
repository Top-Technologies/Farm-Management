# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HrSalaryAttachmentAdjustWizard(models.TransientModel):
    _name = 'hr.salary.attachment.adjust.wizard'
    _description = 'Adjust Salary Attachment Repayment Schedule'

    attachment_id = fields.Many2one(
        'hr.salary.attachment',
        string='Salary Attachment',
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='attachment_id.currency_id',
        string='Currency',
    )
    schedule_line_id = fields.Many2one(
        'hr.salary.attachment.schedule',
        string='Installment Month',
        required=True,
        domain="[('attachment_id', '=', attachment_id), ('state', '=', 'scheduled')]",
        help='The scheduled installment month being adjusted.',
    )
    change_month = fields.Boolean(
        string='Select a different month',
        default=False,
        help='Check this if you want to adjust a month other than the current scheduled month.',
    )
    month_display = fields.Char(
        string='Installment Month',
        compute='_compute_month_display',
    )
    current_amount = fields.Monetary(
        string='Scheduled Amount',
        related='schedule_line_id.amount',
        readonly=True,
        currency_field='currency_id',
    )
    action_type = fields.Selection([
        ('skip', 'Skip this month (0 payment)'),
        ('reduce', 'Pay a partial amount'),
    ], string='Adjustment Action', default='skip', required=True)

    new_amount = fields.Monetary(
        string='New Amount for this Month',
        default=0.0,
        currency_field='currency_id',
    )
    difference_amount = fields.Monetary(
        string='Unpaid Difference',
        compute='_compute_difference',
        currency_field='currency_id',
    )
    redistribute_method = fields.Selection([
        ('extend_schedule', 'Add an extra month at the end (keep other monthly payments unchanged)'),
        ('spread_evenly', 'Spread evenly across remaining months (monthly payment increases)'),
    ], string='What to do with the unpaid amount?', default='extend_schedule', required=True)

    reason = fields.Char(
        string='Reason',
        required=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        att_id = res.get('attachment_id') or self.env.context.get('default_attachment_id')
        sched_id = res.get('schedule_line_id') or self.env.context.get('default_schedule_line_id')

        if att_id:
            att = self.env['hr.salary.attachment'].browse(att_id)
            if not sched_id:
                today = fields.Date.today()
                # 1. Look for scheduled installment matching current month
                curr_line = att.schedule_line_ids.filtered(
                    lambda l: l.state == 'scheduled' and l.date and l.date.year == today.year and l.date.month == today.month
                )
                if curr_line:
                    sched_id = curr_line[0].id
                else:
                    # 2. Look for first upcoming scheduled installment
                    upcoming = att.schedule_line_ids.filtered(
                        lambda l: l.state == 'scheduled' and l.date and l.date >= today
                    ).sorted('date')
                    if upcoming:
                        sched_id = upcoming[0].id
                    else:
                        # 3. Fallback to any first scheduled installment
                        any_sched = att.schedule_line_ids.filtered(lambda l: l.state == 'scheduled').sorted('date')
                        if any_sched:
                            sched_id = any_sched[0].id

            if sched_id:
                res['schedule_line_id'] = sched_id

        return res

    @api.depends('schedule_line_id', 'schedule_line_id.date')
    def _compute_month_display(self):
        for wiz in self:
            if wiz.schedule_line_id and wiz.schedule_line_id.date:
                wiz.month_display = wiz.schedule_line_id.date.strftime('%B %Y')
            else:
                wiz.month_display = _('Current Month')

    @api.onchange('action_type')
    def _onchange_action_type(self):
        if self.action_type == 'skip':
            self.new_amount = 0.0

    @api.onchange('schedule_line_id')
    def _onchange_schedule_line_id(self):
        if self.action_type == 'skip':
            self.new_amount = 0.0

    @api.depends('current_amount', 'new_amount', 'action_type')
    def _compute_difference(self):
        for wiz in self:
            if wiz.action_type == 'skip':
                wiz.difference_amount = wiz.current_amount
            else:
                wiz.difference_amount = max(0.0, wiz.current_amount - wiz.new_amount)

    @api.constrains('new_amount', 'action_type')
    def _check_amounts(self):
        for wiz in self:
            if wiz.action_type == 'reduce':
                if wiz.new_amount < 0:
                    raise ValidationError(_("The new installment amount cannot be negative."))
                if wiz.current_amount and wiz.new_amount > wiz.current_amount:
                    raise ValidationError(_("The new installment amount cannot exceed the original scheduled amount (%s).") % wiz.current_amount)

    def action_apply(self):
        self.ensure_one()
        line = self.schedule_line_id
        if not line or line.state != 'scheduled':
            raise UserError(_("The selected installment is no longer in 'scheduled' status."))

        diff = self.difference_amount
        orig_amount = line.amount
        selected_month_str = line.date.strftime('%B %Y') if line.date else _('Selected Month')
        method_label = dict(self._fields['redistribute_method'].selection).get(self.redistribute_method)

        # 1. Update the target line
        if self.action_type == 'skip' or self.new_amount == 0.0:
            line.write({
                'amount': 0.0,
                'state': 'skipped',
                'notes': f"Skipped on {fields.Date.today()}: {self.reason}",
            })
        else:
            line.write({
                'amount': round(self.new_amount, 2),
                'notes': f"Reduced from {orig_amount} to {self.new_amount}: {self.reason}",
            })

        # 2. Redistribute the difference
        if diff > 0:
            future_lines = self.attachment_id.schedule_line_ids.filtered(
                lambda l: l.state == 'scheduled' and l.id != line.id and l.date > line.date
            ).sorted(key=lambda l: l.date)

            if self.redistribute_method == 'spread_evenly' and future_lines:
                n = len(future_lines)
                per_month = round(diff / n, 2)
                allocated = 0.0
                for idx, f_line in enumerate(future_lines):
                    if idx == n - 1:
                        add_amt = round(diff - allocated, 2)
                    else:
                        add_amt = per_month
                        allocated += add_amt
                    new_f_amt = round(f_line.amount + add_amt, 2)
                    f_line.write({
                        'amount': new_f_amt,
                        'notes': (f_line.notes or '') + f" [+{add_amt} from {selected_month_str}]",
                    })
            else:
                # Extend schedule by adding an extra month at the end
                all_lines = self.attachment_id.schedule_line_ids.sorted(key=lambda l: l.date)
                last_date = all_lines[-1].date if all_lines else fields.Date.today()
                next_date = last_date + relativedelta(months=1)
                max_seq = max(all_lines.mapped('sequence')) if all_lines else 0

                self.env['hr.salary.attachment.schedule'].create({
                    'attachment_id': self.attachment_id.id,
                    'sequence': max_seq + 1,
                    'date': next_date,
                    'amount': round(diff, 2),
                    'state': 'scheduled',
                    'notes': f"Deferred payment from {selected_month_str} ({self.reason})",
                })

        # 3. Update attachment estimated end date
        all_lines_updated = self.attachment_id.schedule_line_ids.sorted(key=lambda l: l.date)
        if all_lines_updated:
            self.attachment_id.date_estimated_end = all_lines_updated[-1].date

        # 4. Synchronize contract deduction fields
        self.attachment_id._sync_contract_deductions()

        # 5. Post chatter note
        emp_names = ", ".join(self.attachment_id.employee_ids.mapped('name'))
        msg = (
            f"<b>Loan Repayment Schedule Adjusted</b><br/>"
            f"• <b>Month:</b> {selected_month_str}<br/>"
            f"• <b>Action:</b> {'Skipped (0.00 ' + (self.currency_id.symbol or 'ETB') + ')' if (self.action_type == 'skip' or self.new_amount == 0.0) else f'Reduced to {self.new_amount} ' + (self.currency_id.symbol or 'ETB')}<br/>"
            f"• <b>Redistributed Amount:</b> {diff:,.2f} {self.currency_id.symbol or 'ETB'}<br/>"
            f"• <b>Method:</b> {method_label}<br/>"
            f"• <b>Reason:</b> {self.reason}<br/>"
            f"• <b>Employee(s):</b> {emp_names}"
        )
        self.attachment_id.message_post(body=msg, subtype_xmlid='mail.mt_comment')

        # Also post on linked hr.loan if exists
        linked_loans = self.env['hr.loan'].search([('salary_attachment_id', '=', self.attachment_id.id)])
        for loan in linked_loans:
            loan.message_post(body=msg, subtype_xmlid='mail.mt_comment')

        return {'type': 'ir.actions.act_window_close'}
