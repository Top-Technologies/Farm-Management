# -*- coding: utf-8 -*-
import logging
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEDUCTION_FIELD_MAP = {
    'cost_sharing': 'deduction_cost_sharing',
    'dashen_credit': 'deduction_dashen_credit',
    'awash_credit': 'deduction_awash_credit',
    'credit_assoc_loan': 'deduction_credit_assoc_loan',
    'advance': 'deduction_advance',
    'pre_payment': 'deduction_pre_payment',
    'medical_recovery': 'deduction_medical_recovery',
    'pension_receivable': 'deduction_pension_receivable',
    'fine': 'deduction_fine',
}


class HrSalaryAttachment(models.Model):
    _inherit = 'hr.salary.attachment'

    loan_deduction_type = fields.Selection([
        ('other', 'Other Standard Attachment'),
        ('cost_sharing', 'Cost Sharing'),
        ('dashen_credit', 'Dashen Bank Loan / Credit'),
        ('awash_credit', 'Awash Bank Loan / Credit'),
        ('credit_assoc_loan', 'Credit Association Loan'),
        ('advance', 'Salary Advance'),
        ('pre_payment', 'Pre-Payment'),
        ('medical_recovery', 'Medical Recovery'),
        ('pension_receivable', 'Pension Receivable'),
        ('fine', 'Fine'),
    ], string='Contract Deduction Link', default='other', tracking=True,
       help='Link this salary attachment / loan to the employee contract deduction field for seamless tracking without double-deduction.')

    schedule_line_ids = fields.One2many(
        'hr.salary.attachment.schedule',
        'attachment_id',
        string='Repayment Schedule',
        copy=False,
    )
    schedule_count = fields.Integer(
        string='Installments Count',
        compute='_compute_schedule_stats',
    )
    has_schedule = fields.Boolean(
        string='Has Schedule',
        compute='_compute_schedule_stats',
    )
    current_month_installment = fields.Monetary(
        string='Current Month Installment',
        compute='_compute_schedule_stats',
        currency_field='currency_id',
        help='The installment amount scheduled to be deducted during the active payroll month.',
    )

    @api.model
    def _default_other_input_type_id(self):
        input_type = self.env.ref('hr_payroll.input_attachment_salary', raise_if_not_found=False)
        if not input_type:
            input_type = self.env['hr.payslip.input.type'].search([('code', '=', 'ATTACH_SALARY')], limit=1)
        return input_type.id if input_type else False

    other_input_type_id = fields.Many2one(
        'hr.payslip.input.type',
        string='Type',
        default=_default_other_input_type_id,
    )

    @api.depends('schedule_line_ids', 'schedule_line_ids.state', 'schedule_line_ids.amount', 'schedule_line_ids.date')
    def _compute_schedule_stats(self):
        today = fields.Date.today()
        for att in self:
            lines = att.schedule_line_ids
            att.schedule_count = len(lines)
            att.has_schedule = bool(lines)

            # Find installment for active month
            curr_line = lines.filtered(
                lambda l: l.date and l.date.year == today.year and l.date.month == today.month
            )
            if curr_line:
                # If skipped, current month installment is 0.0
                att.current_month_installment = curr_line[0].amount if curr_line[0].state != 'skipped' else 0.0
            else:
                # Fallback to next upcoming scheduled line or monthly_amount
                upcoming = lines.filtered(lambda l: l.state == 'scheduled' and l.date and l.date >= today)
                if upcoming:
                    att.current_month_installment = upcoming[0].amount
                else:
                    att.current_month_installment = att.monthly_amount

    def action_generate_schedule(self):
        """Generates or recalculates the repayment schedule based on total amount and monthly installment."""
        self.ensure_one()
        if not self.has_total_amount or self.total_amount <= 0:
            raise UserError(_("Please specify a Total Amount greater than zero to generate a repayment schedule."))
        if self.monthly_amount <= 0:
            raise UserError(_("Please specify a Monthly Payslip Amount greater than zero to generate a repayment schedule."))

        start_date = self.date_start or fields.Date.today()
        # Preserve paid lines
        paid_lines = self.schedule_line_ids.filtered(lambda l: l.state == 'paid')
        paid_amount = sum(paid_lines.mapped('amount'))
        remaining = self.total_amount - paid_amount

        # Remove unpaid/skipped existing lines
        (self.schedule_line_ids - paid_lines).unlink()

        if remaining <= 0:
            return True

        curr_date = start_date
        # If paid lines exist, advance start date past the last paid installment
        if paid_lines:
            last_paid_date = max(paid_lines.mapped('date'))
            curr_date = last_paid_date + relativedelta(months=1)

        seq = len(paid_lines) + 1
        new_lines = []
        monthly = self.monthly_amount

        while remaining > 0:
            inst_amount = min(monthly, remaining)
            new_lines.append({
                'attachment_id': self.id,
                'sequence': seq,
                'date': curr_date,
                'amount': round(inst_amount, 2),
                'state': 'scheduled',
                'notes': f"Installment #{seq}",
            })
            remaining -= inst_amount
            seq += 1
            curr_date = curr_date + relativedelta(months=1)

        if new_lines:
            self.env['hr.salary.attachment.schedule'].create(new_lines)
            last_date = new_lines[-1]['date']
            self.date_estimated_end = last_date

        self._sync_contract_deductions()
        return True

    def action_adjust_schedule(self):
        """Opens the schedule adjustment wizard to skip a month or change repayment amount."""
        self.ensure_one()
        if not self.schedule_line_ids:
            self.action_generate_schedule()

        return {
            'name': _('Adjust Repayment Schedule / Skip Month'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.salary.attachment.adjust.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_attachment_id': self.id,
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.has_total_amount and rec.total_amount > 0 and rec.monthly_amount > 0 and not rec.schedule_line_ids:
                try:
                    rec.action_generate_schedule()
                except Exception as e:
                    _logger.warning("Could not auto-generate schedule for attachment %s: %s", rec.id, str(e))
        records._sync_contract_deductions()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('monthly_amount', 'loan_deduction_type', 'state', 'employee_ids', 'date_start', 'date_end', 'has_total_amount', 'total_amount')):
            self._sync_contract_deductions()
        return res

    def unlink(self):
        records_to_sync = self.filtered(lambda r: r.loan_deduction_type and r.loan_deduction_type != 'other')
        employees = records_to_sync.mapped('employee_ids')
        ded_types = set(records_to_sync.mapped('loan_deduction_type'))
        res = super().unlink()
        for emp in employees:
            contracts = emp.contract_ids.filtered(lambda c: c.state in ('open', 'draft'))
            for ded_type in ded_types:
                field_name = DEDUCTION_FIELD_MAP.get(ded_type)
                if field_name:
                    other_open = self.env['hr.salary.attachment'].search([
                        ('employee_ids', 'in', emp.id),
                        ('loan_deduction_type', '=', ded_type),
                        ('state', '=', 'open'),
                    ])
                    amount = sum(other_open._get_effective_monthly_amount()) if other_open else 0.0
                    contracts.write({field_name: amount})
        return res

    def _get_effective_monthly_amount(self):
        """Returns the effective monthly deduction for this attachment, respecting any schedule/skips."""
        today = fields.Date.today()
        amounts = []
        for att in self:
            if att.schedule_line_ids:
                # Find line for current month
                curr_line = att.schedule_line_ids.filtered(
                    lambda l: l.date and l.date.year == today.year and l.date.month == today.month
                )
                if curr_line:
                    amounts.append(curr_line[0].amount if curr_line[0].state != 'skipped' else 0.0)
                    continue
                # Upcoming scheduled
                upcoming = att.schedule_line_ids.filtered(lambda l: l.state == 'scheduled' and l.date and l.date >= today)
                if upcoming:
                    amounts.append(upcoming[0].amount)
                    continue
            amounts.append(att.monthly_amount)
        return amounts

    def _sync_contract_deductions(self):
        for attachment in self:
            if not attachment.loan_deduction_type or attachment.loan_deduction_type == 'other':
                continue
            field_name = DEDUCTION_FIELD_MAP.get(attachment.loan_deduction_type)
            if not field_name:
                continue

            for emp in attachment.employee_ids:
                contracts = emp.contract_ids.filtered(lambda c: c.state in ('open', 'draft'))
                if not contracts:
                    continue

                open_attachments = self.env['hr.salary.attachment'].search([
                    ('employee_ids', 'in', emp.id),
                    ('loan_deduction_type', '=', attachment.loan_deduction_type),
                    ('state', '=', 'open'),
                ])
                total_monthly = sum(open_attachments._get_effective_monthly_amount())
                contracts.write({field_name: total_monthly})
