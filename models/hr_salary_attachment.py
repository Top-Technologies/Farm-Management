# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

DEDUCTION_FIELD_MAP = {
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

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_contract_deductions()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('monthly_amount', 'loan_deduction_type', 'state', 'employee_ids', 'date_start', 'date_end')):
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
                    amount = sum(other_open.mapped('monthly_amount')) if other_open else 0.0
                    contracts.write({field_name: amount})
        return res

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
                total_monthly = sum(open_attachments.mapped('monthly_amount'))
                contracts.write({field_name: total_monthly})
