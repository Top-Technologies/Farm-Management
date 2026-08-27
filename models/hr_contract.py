# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

LEVEL_SELECTION = [
    ('base', 'Base (መነሻ)'),
    ('1', 'Step 1'),
    ('2', 'Step 2'),
    ('3', 'Step 3'),
    ('4', 'Step 4'),
    ('5', 'Step 5'),
    ('6', 'Step 6'),
    ('7', 'Step 7'),
    ('8', 'Step 8'),
    ('9', 'Step 9'),
    ('10', 'Step 10'),
    ('11', 'Step 11'),
    ('12', 'Step 12'),
    ('max', 'Max / Ceiling (ጣሪያ)'),
]


class HrContract(models.Model):
    _inherit = 'hr.contract'

    farm_employee_type = fields.Selection(
        related='employee_id.farm_employee_type',
        string='Employee Classification',
        readonly=True,
    )

    # Permanent Employee Salary Matrix Placement (Grade & Level Scale)
    salary_matrix_type = fields.Selection([
        ('head_office', 'Head Office (ዋና መ/ቤት)'),
        ('cpw', 'CPW'),
        ('farm', 'Farm Permanent (የእርሻ ልማቶች - ቋሚ)'),
    ], string='Salary Scale Category', tracking=True, help='Select which Salary Matrix applies to this contract.')

    salary_grade = fields.Selection([
        (str(i), f'Grade {i} (ደረጃ {i})') for i in range(1, 23)
    ], string='Salary Grade (ደረጃ)', tracking=True, help='Employee grade from Grade 1 to Grade 22.')

    salary_level = fields.Selection(
        LEVEL_SELECTION,
        string='Salary Step / Level',
        tracking=True,
        help='Step / Level from Base to Step 12 to Max.',
    )

    matrix_basic_wage = fields.Float(
        string='Matrix Basic Wage (Birr)',
        compute='_compute_matrix_basic_wage',
        store=True,
        digits=(16, 2),
        tracking=True,
        help='Monthly basic wage determined automatically by the Salary Matrix.',
    )

    # Suppress US-specific payroll benefits (401k, health benefits) from appearing
    country_code = fields.Char(
        string='Country Code',
        compute='_compute_clean_country_code',
        store=False,
    )

    @api.depends('company_id', 'company_country_id')
    def _compute_clean_country_code(self):
        for contract in self:
            c_code = contract.company_country_id.code if contract.company_country_id else ''
            # If country is US or empty, set to ET so US pre-tax/post-tax benefits remain hidden
            contract.country_code = 'ET' if c_code in ('US', '', False) else c_code

    @api.depends('salary_matrix_type', 'salary_grade', 'salary_level', 'company_id')
    def _compute_matrix_basic_wage(self):
        for contract in self:
            if contract.salary_matrix_type and contract.salary_grade and contract.salary_level:
                try:
                    wage = self.env['hr.salary.matrix'].get_matrix_wage(
                        matrix_type=contract.salary_matrix_type,
                        grade=int(contract.salary_grade),
                        level=contract.salary_level,
                        company_id=contract.company_id.id if contract.company_id else None,
                    )
                    contract.matrix_basic_wage = wage
                    if wage > 0 and (not contract.wage or contract.wage != wage):
                        contract.wage = wage
                except Exception as e:
                    _logger.warning("Failed to compute matrix wage for contract %s: %s", contract.name, str(e))
                    contract.matrix_basic_wage = 0.0
            else:
                contract.matrix_basic_wage = 0.0

    @api.onchange('salary_matrix_type', 'salary_grade', 'salary_level')
    def _onchange_salary_matrix_wage(self):
        if self.salary_matrix_type and self.salary_grade and self.salary_level:
            wage = self.env['hr.salary.matrix'].get_matrix_wage(
                matrix_type=self.salary_matrix_type,
                grade=int(self.salary_grade),
                level=self.salary_level,
                company_id=self.company_id.id if self.company_id else None,
            )
            if wage > 0:
                self.matrix_basic_wage = wage
                self.wage = wage

    @api.onchange('employee_id')
    def _onchange_employee_matrix_default(self):
        if self.employee_id:
            if self.employee_id.farm_employee_type == 'head_office':
                self.salary_matrix_type = 'head_office'
            elif self.employee_id.farm_employee_type == 'permanent':
                self.salary_matrix_type = 'farm'
            elif not self.salary_matrix_type:
                self.salary_matrix_type = 'head_office'

