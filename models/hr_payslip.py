# -*- coding: utf-8 -*-
from odoo import models, fields, api, Command, _
from odoo.exceptions import UserError, ValidationError

LOAN_RULE_TO_ATTACHMENT_TYPE = {
    'DED_DASHEN_CREDIT': 'dashen_credit',
    'DED_AWASH_CREDIT': 'awash_credit',
    'DED_CREDIT_LOAN': 'credit_assoc_loan',
    'DED_ADVANCE': 'advance',
    'DED_PRE_PAYMENT': 'pre_payment',
    'DED_MEDICAL_RECOVERY': 'medical_recovery',
    'DED_PENSION_RECEIVABLE': 'pension_receivable',
    'DED_FINE': 'fine',
}


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    farm_employee_type = fields.Selection(
        related='employee_id.farm_employee_type',
        string='Worker Classification',
        store=True,
        readonly=True,
    )
    farm_id = fields.Many2one(
        'farm.farm',
        related='employee_id.current_farm_id',
        string='Farm Location',
        store=True,
        readonly=True,
    )
    sub_unit_id = fields.Many2one(
        'farm.sub.unit',
        related='employee_id.current_sub_unit_id',
        string='Sub Unit Location',
        store=True,
        readonly=True,
    )

    # Permanent Employee Salary Matrix Placement
    salary_matrix_type = fields.Selection(
        related='employee_id.salary_matrix_type',
        string='Salary Scale Category',
        readonly=True,
    )
    salary_grade = fields.Selection(
        related='employee_id.salary_grade',
        string='Salary Grade',
        readonly=True,
    )
    salary_level = fields.Selection(
        related='employee_id.salary_level',
        string='Salary Step / Level',
        readonly=True,
    )
    matrix_basic_wage = fields.Float(
        related='employee_id.matrix_basic_wage',
        string='Matrix Basic Wage (Birr)',
        store=True,
        readonly=True,
        digits=(16, 2),
    )

    # Linked Farm Work Entries
    farm_work_entry_ids = fields.One2many(
        'farm.work.entry',
        'payslip_id',
        string='Farm Work Entries',
        help='Field work entries included in this payslip for daily or piece-rate wage calculation.',
    )
    farm_work_entries_count = fields.Integer(
        string='Work Entries Count',
        compute='_compute_farm_work_entry_stats',
        store=True,
    )
    farm_work_total_amount = fields.Float(
        string='Farm Total Amount (Birr)',
        compute='_compute_farm_work_entry_stats',
        store=True,
        digits=(16, 2),
        help='Total gross earnings calculated directly from attached farm work entries.',
    )
    farm_work_days_count = fields.Float(
        string='Total Work Days',
        compute='_compute_farm_work_entry_stats',
        digits=(16, 2),
        help='Total full days and half days worked by temporary worker.',
    )

    @api.depends('farm_work_entry_ids', 'farm_work_entry_ids.total_amount', 'farm_work_entry_ids.score_value')
    def _compute_farm_work_entry_stats(self):
        for slip in self:
            entries = slip.farm_work_entry_ids
            slip.farm_work_entries_count = len(entries)
            slip.farm_work_total_amount = sum(entries.mapped('total_amount'))
            slip.farm_work_days_count = sum(entries.mapped('score_value'))

    def _attach_farm_work_entries(self):
        """Finds and attaches unpaid non-cancelled work entries for Temporary & Zemach workers."""
        for slip in self:
            emp = slip.employee_id
            if emp.farm_employee_type in ('temporary', 'zemach'):
                domain = [
                    ('employee_id', '=', emp.id),
                    ('date', '>=', slip.date_from),
                    ('date', '<=', slip.date_to),
                    ('state', '!=', 'cancelled'),
                    ('payment_status', 'in', ('unpaid', 'in_payroll', False)),
                    '|',
                    ('payslip_id', '=', False),
                    ('payslip_id', '=', slip.id),
                ]
                work_entries = self.env['farm.work.entry'].search(domain)
                if work_entries:
                    work_entries.write({
                        'payslip_id': slip.id,
                        'payslip_run_id': slip.payslip_run_id.id if slip.payslip_run_id else False,
                        'payment_status': 'in_payroll',
                    })

    def _compute_input_line_ids(self):
        super()._compute_input_line_ids()
        for slip in self:
            # Prevent double deductions: If an attachment is linked to a contract deduction
            # (e.g. Dashen/Awash credit, credit assoc loan, advance), suppress the generic ATTACH_SALARY input line
            loan_attachments = slip.employee_id.salary_attachment_ids.filtered(
                lambda a: a.state == 'open' and a.loan_deduction_type and a.loan_deduction_type != 'other'
            )
            if loan_attachments:
                types_to_remove = loan_attachments.mapped('other_input_type_id').ids
                lines_to_remove = slip.input_line_ids.filtered(lambda l: l.input_type_id.id in types_to_remove)
                if lines_to_remove:
                    slip.update({'input_line_ids': [Command.unlink(line.id) for line in lines_to_remove]})

    def _record_loan_attachment_payments(self):
        """Record loan deduction payments against open salary attachments when payslip is paid."""
        for slip in self:
            if not slip.employee_id:
                continue
            for line in slip.line_ids:
                ded_type = LOAN_RULE_TO_ATTACHMENT_TYPE.get(line.code)
                if not ded_type or line.total == 0:
                    continue
                amount_paid = abs(line.total)
                attachments = slip.employee_id.salary_attachment_ids.filtered(
                    lambda a: a.state == 'open' and a.loan_deduction_type == ded_type
                )
                for att in attachments:
                    att.record_payment(amount_paid)
                    att.write({'payslip_ids': [(4, slip.id)]})

    def compute_sheet(self):
        # Attach farm work entries before computing salary rules
        self._attach_farm_work_entries()
        return super().compute_sheet()

    def action_payslip_done(self):
        res = super().action_payslip_done()
        for slip in self:
            if slip.farm_work_entry_ids:
                slip.farm_work_entry_ids.write({
                    'payment_status': 'paid',
                    'paid_date': fields.Date.today(),
                })
        self._record_loan_attachment_payments()
        return res

    def action_payslip_paid(self):
        res = super().action_payslip_paid()
        for slip in self:
            if slip.farm_work_entry_ids:
                slip.farm_work_entry_ids.write({
                    'payment_status': 'paid',
                    'paid_date': fields.Date.today(),
                })
        self._record_loan_attachment_payments()
        return res

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') == 'paid':
            self._record_loan_attachment_payments()
        return res

    def action_payslip_cancel(self):
        work_entries = self.env['farm.work.entry'].search([('payslip_id', 'in', self.ids)])
        if work_entries:
            work_entries.write({
                'payment_status': 'unpaid',
                'payslip_id': False,
                'payslip_run_id': False,
                'paid_date': False,
            })
        return super().action_payslip_cancel()

    def action_payslip_draft(self):
        work_entries = self.env['farm.work.entry'].search([('payslip_id', 'in', self.ids)])
        if work_entries:
            work_entries.write({
                'payment_status': 'unpaid',
                'payslip_id': False,
                'payslip_run_id': False,
                'paid_date': False,
            })
        return super().action_payslip_draft()

    def unlink(self):
        # Release all work entries back to unpaid status upon deletion of payslips
        work_entries = self.env['farm.work.entry'].search([('payslip_id', 'in', self.ids)])
        if work_entries:
            work_entries.write({
                'payment_status': 'unpaid',
                'payslip_id': False,
                'payslip_run_id': False,
                'paid_date': False,
            })
        return super().unlink()
