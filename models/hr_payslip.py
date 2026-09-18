# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, Command, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

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
        store=True,
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
        """Finds and attaches unpaid non-cancelled work entries for all workers (Permanent, Seasonal, Temporary)."""
        for slip in self:
            emp = slip.employee_id
            if not emp:
                continue
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

    def init(self):
        super().init()
        try:
            with self.env.cr.savepoint():
                # Set noupdate=False for farm_management data records so XML updates apply seamlessly
                self.env.cr.execute("""
                    UPDATE ir_model_data 
                    SET noupdate = false 
                    WHERE module IN ('farm_management', 'Farm-Management', 'Farm_Management');
                """)
                # Clean up any legacy obsolete salary rules
                self.env.cr.execute("""
                    DELETE FROM hr_salary_rule WHERE code IN ('DED_DASHEN_BANK', 'DED_AWASH');
                    DELETE FROM hr_salary_rule WHERE code = 'NET' AND name::text LIKE '%Net Salary%' 
                    AND struct_id IN (SELECT DISTINCT struct_id FROM hr_salary_rule WHERE code = 'DED_PENSION_7');
                """)
                # Update sequences across all structures:
                # 1. Pension 11% right after Pension 7% (110 -> 111)
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 111 WHERE code = 'COMP_PENSION_11';")
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 112 WHERE code = 'DED_INCOME_TAX';")
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 113 WHERE code = 'DED_LUC';")
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 114 WHERE code = 'DED_CREDIT_MANDATORY';")
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 115 WHERE code = 'DED_CREDIT_VOLUNTARY';")
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 116 WHERE code = 'DED_SOCIAL_CONTRIBUTION';")
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 180 WHERE code = 'BACK_PAY_TAX';")
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 181 WHERE code = 'BACK_PAY_PENSION_7';")
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 190 WHERE code = 'TOTAL_DEDUCTIONS';")
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 195 WHERE code = 'TOTAL_DEPOSITS';")
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 126 WHERE code = 'DED_ABSENT';")
                # 2. Net salary as final row
                self.env.cr.execute("UPDATE hr_salary_rule SET sequence = 300 WHERE code = 'NET';")

                # Ensure all payroll structures have Unpaid Leave (LEAVE90) registered as unpaid
                self.env.cr.execute("""
                    INSERT INTO hr_payroll_structure_hr_work_entry_type_rel (hr_payroll_structure_id, hr_work_entry_type_id)
                    SELECT s.id, w.id
                    FROM hr_payroll_structure s
                    CROSS JOIN hr_work_entry_type w
                    WHERE (w.code = 'LEAVE90' OR w.id IN (SELECT work_entry_type_id FROM hr_leave_type WHERE unpaid = true AND work_entry_type_id IS NOT NULL))
                    AND NOT EXISTS (
                        SELECT 1 FROM hr_payroll_structure_hr_work_entry_type_rel rel
                        WHERE rel.hr_payroll_structure_id = s.id AND rel.hr_work_entry_type_id = w.id
                    );
                """)

                # Update BASIC rule to evaluate paid worked days and deduct unpaid days
                basic_code = """result = payslip.paid_amount if (payslip.worked_days_line_ids and payslip.struct_id.use_worked_day_lines) else (contract.wage or 0.0)"""
                self.env.cr.execute("""
                    UPDATE hr_salary_rule
                    SET amount_python_compute = %s
                    WHERE code = 'BASIC' AND struct_id IN (SELECT id FROM hr_payroll_structure WHERE name = 'Permanent & Head Office Employee Structure');
                """, (basic_code,))

                # Update DED_CREDIT_MANDATORY to dynamically compute 5% of Basic Salary
                credit_mand_code = """basic = categories['BASIC'] if 'BASIC' in categories else (contract.wage or 0.0)\nresult = -round(basic * 0.05, 2)"""
                self.env.cr.execute("""
                    UPDATE hr_salary_rule
                    SET amount_python_compute = %s
                    WHERE code = 'DED_CREDIT_MANDATORY';
                """, (credit_mand_code,))

                # Directly ensure DED_INCOME_TAX, DED_PENSION_7, and COMP_PENSION_11 rules compute dynamically
                income_tax_code = """basic = categories['BASIC'] if 'BASIC' in categories else (contract.wage or 0.0)
taxable = result_rules['TAXABLE_SALARY']['total'] if ('TAXABLE_SALARY' in result_rules and result_rules['TAXABLE_SALARY']['total'] is not None) else (basic + (contract.allowance_transport or 0.0) + (contract.allowance_hardship or 0.0) + (contract.allowance_overtime or 0.0))

if taxable <= 2000:
    result = 0.0
elif taxable <= 4000:
    result = - 0.15 * taxable + 300.0
elif taxable <= 7000:
    result = - 0.20 * taxable + 500.0
elif taxable <= 10000:
    result = - 0.25 * taxable + 850.0
elif taxable <= 14000:
    result = - 0.30 * taxable + 1350.0
else:
    result = - 0.35 * taxable + 2050.0

result = round(result, 2)"""
                pension_code = """basic = categories['BASIC'] if 'BASIC' in categories else (contract.wage or 0.0)
result = -round(basic * 0.07, 2)"""
                comp_pension_code = """basic = categories['BASIC'] if 'BASIC' in categories else (contract.wage or 0.0)
result = round(basic * 0.11, 2)"""

                self.env.cr.execute("""
                    UPDATE hr_salary_rule
                    SET amount_python_compute = %s
                    WHERE code = 'DED_INCOME_TAX';
                """, (income_tax_code,))
                self.env.cr.execute("""
                    UPDATE hr_salary_rule
                    SET amount_python_compute = %s
                    WHERE code = 'DED_PENSION_7';
                """, (pension_code,))
                self.env.cr.execute("""
                    UPDATE hr_salary_rule
                    SET amount_python_compute = %s
                    WHERE code = 'COMP_PENSION_11';
                """, (comp_pension_code,))

                # Synchronize new rules to other permanent structures (like Beha Land Coffee)
                self.env.cr.execute("""
                    INSERT INTO hr_salary_rule (
                        name, code, sequence, category_id, active, appears_on_payslip,
                        condition_select, condition_python, amount_select, amount_python_compute,
                        struct_id, create_uid, write_uid, create_date, write_date
                    )
                    SELECT 
                        r.name, r.code, r.sequence, r.category_id, r.active, r.appears_on_payslip,
                        r.condition_select, r.condition_python, r.amount_select, r.amount_python_compute,
                        s.id, 1, 1, NOW(), NOW()
                    FROM hr_payroll_structure s
                    CROSS JOIN hr_salary_rule r
                    WHERE s.id != r.struct_id
                    AND s.id IN (SELECT DISTINCT struct_id FROM hr_salary_rule WHERE code = 'DED_PENSION_7' AND struct_id IS NOT NULL)
                    AND r.struct_id = (SELECT id FROM hr_payroll_structure WHERE name = 'Permanent & Head Office Employee Structure' LIMIT 1)
                    AND r.code IN ('DED_CREDIT_VOLUNTARY', 'BACK_PAY_TAX', 'BACK_PAY_PENSION_7', 'TOTAL_DEDUCTIONS', 'TOTAL_DEPOSITS', 'COMP_PENSION_11', 'DED_ABSENT')
                    AND NOT EXISTS (
                        SELECT 1 FROM hr_salary_rule existing
                        WHERE existing.struct_id = s.id AND existing.code = r.code
                    );
                """)
        except Exception as e:
            _logger.warning("HrPayslip.init() warning: %s", e)
