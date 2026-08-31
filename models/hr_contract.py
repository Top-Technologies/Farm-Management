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

    # =========================================================================
    # Allowances & Earnings Engine
    # =========================================================================
    transport_allowance_rule = fields.Selection([
        ('fixed_4000', 'Fixed Transport Allowance (ETB 4,000 / month) — Grade ≤ 17'),
        ('fuel_50', 'Transport Allowance 50 Litres Fuel — Grade 18'),
        ('fuel_60', 'Transport Allowance 60 Litres Fuel — Grade 19+'),
        ('custom', 'Custom / Manual Transport Allowance'),
        ('none', 'No Transport Allowance (Company Vehicle Assigned)'),
    ], string='Transport Policy', compute='_compute_transport_policy', store=True, readonly=False, tracking=True)

    fuel_price_per_liter = fields.Float(
        string='Universal Fuel Price / Liter (Birr)',
        related='company_id.fuel_price_per_liter',
        readonly=True,
        digits=(16, 2),
        help='Universal fuel price in Birr per liter configured in Company Settings.',
    )
    fuel_liters = fields.Float(
        string='Fuel Liters (Litres)',
        compute='_compute_fuel_liters',
        store=True,
        digits=(16, 1),
        help='Fuel entitlement in litres based on employee grade.',
    )
    allowance_transport = fields.Float(
        string='Transport Allowance (የመጓጓዣ አበል)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Monthly transport or fuel allowance. Auto-populated from grade/fuel price, but freely editable for custom rates.',
    )

    allowance_electric_vehicle = fields.Float(
        string='Electric Vehicle Allowance (የኤሌክትሪክ መኪና አበል)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='ETB 5,000 per month for employees assigned electric company vehicles (operating expense).',
    )
    allowance_hardship = fields.Float(
        string='Hardship Allowance (የአስቸጋሪ ቦታ / ስራ አበል)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Additional payment for exceptional operational demands/high-workload harvesting periods.',
    )
    allowance_retroactive = fields.Float(
        string='Back Payment / Retroactive Pay (የተከማቸ የደመወዝ ጭማሪ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Salary difference resulting from approved retroactive salary adjustments.',
    )
    allowance_overtime = fields.Float(
        string='Approved Overtime Payment (የትርፍ ሰዓት ክፍያ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Payment for approved working hours exceeding normal work schedule.',
    )
    total_monthly_allowances = fields.Float(
        string='Total Monthly Allowances (ጠቅላላ አበሎች)',
        compute='_compute_all_allowances',
        store=True,
        digits=(16, 2),
        help='Sum of all monthly allowances (Transport + EV + Hardship + Retroactive + Overtime).',
    )
    gross_monthly_wage = fields.Float(
        string='Total Gross Monthly Wage (ጠቅላላ ወርሃዊ ገቢ)',
        compute='_compute_all_allowances',
        store=True,
        digits=(16, 2),
        help='Total gross monthly earnings: Basic Wage + Total Allowances.',
    )

    # =========================================================================
    # 1. Statutory & Mandatory Deductions
    # =========================================================================
    deduction_pension = fields.Float(
        string='Pension (የጡረታ መዋጮ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Legally required employee pension deduction.',
    )
    deduction_income_tax = fields.Float(
        string='Income Tax (የገቢ ግብር)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Statutory employee income tax deduction.',
    )
    deduction_luc = fields.Float(
        string='L.U.C 1% (የሰራተኛ ማህበር 1%)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Labor Union Contribution (1%).',
    )
    deduction_credit_assoc_mandatory = fields.Float(
        string='Credit Association - Mandatory (የብድርና ቁጠባ አስገዳጅ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Mandatory credit association contribution.',
    )
    deduction_social_contribution = fields.Float(
        string='Social Contribution (ማህበራዊ መዋጮ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Approved social contribution.',
    )
    total_statutory_deductions = fields.Float(
        string='Total Statutory Deductions',
        compute='_compute_all_deductions',
        store=True,
        digits=(16, 2),
    )

    # =========================================================================
    # 2. Loans, Advances & Recoveries
    # =========================================================================
    deduction_advance = fields.Float(
        string='Advance (የደመወዝ ቅድመ ክፍያ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Monthly salary advance recovery.',
    )
    deduction_pre_payment = fields.Float(
        string='Pre-Payment (ቅድመ ክፍያ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Previous pre-payment recovery.',
    )
    deduction_credit_assoc_loan = fields.Float(
        string='Credit Association Loan (የብድርና ቁጠባ ብድር)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Credit association loan repayment installment.',
    )
    deduction_medical_recovery = fields.Float(
        string='Medical Recovery (የህክምና ወጪ ተመላሽ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Excess medical expenses recovery.',
    )
    deduction_pension_receivable = fields.Float(
        string='Pension Receivable (የጡረታ ተሰብሳቢ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Pension receivable balance recovery.',
    )
    deduction_fine = fields.Float(
        string='Fine (ቅጣት)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Approved disciplinary or administrative fine.',
    )
    total_loan_deductions = fields.Float(
        string='Total Loans & Recoveries',
        compute='_compute_all_deductions',
        store=True,
        digits=(16, 2),
    )

    # =========================================================================
    # 3. Employee Savings & Financial Contributions
    # =========================================================================
    deduction_saving_kossa = fields.Float(
        string='Saving Kossa (የኮሳ ቁጠባ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Kossa voluntary savings contribution.',
    )
    deduction_saving_jimma = fields.Float(
        string='Saving Jimma (የጅማ ቁጠባ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Jimma voluntary savings contribution.',
    )
    deduction_suntu_saving = fields.Float(
        string='Suntu Saving (የሱንቱ ቁጠባ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Suntu savings contribution.',
    )
    deduction_family_allotment = fields.Float(
        string='Family Allotment (ለቤተሰብ የሚተላለፍ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Family-related payroll allocation.',
    )
    deduction_cost_sharing = fields.Float(
        string='Cost Sharing (የወጪ መጋራት)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Higher education cost-sharing deduction.',
    )
    total_savings_deductions = fields.Float(
        string='Total Savings & Contributions',
        compute='_compute_all_deductions',
        store=True,
        digits=(16, 2),
    )

    # =========================================================================
    # 4. Employee Welfare & Services
    # =========================================================================
    deduction_ration = fields.Float(
        string='Ration (የራሽን ተቀናሽ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Food ration deduction.',
    )
    deduction_service = fields.Float(
        string='Service (የአገልግሎት ተቀናሽ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='General service deduction.',
    )
    deduction_medical_8 = fields.Float(
        string='Medical 8 (የህክምና 8)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Medical 8 welfare program contribution.',
    )
    deduction_church_contribution = fields.Float(
        string='Church Contribution (የቤተክርስቲያን መዋጮ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Voluntary religious / church contribution.',
    )
    deduction_kindergarten = fields.Float(
        string='Kindergarten (የህፃናት ማቆያ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Childcare / Kindergarten deduction.',
    )
    deduction_cafeteria = fields.Float(
        string='Cafeteria (የካፌቴሪያ ተቀናሽ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Cafeteria / dining expense deduction.',
    )
    deduction_school = fields.Float(
        string='School (የትምህርት ቤት ተቀናሽ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Education / School fees deduction.',
    )
    deduction_sport = fields.Float(
        string='Sport (የስፖርት መዋጮ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Sport & recreation contribution.',
    )
    deduction_hiv = fields.Float(
        string='HIV (የኤች አይ ቪ መዋጮ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Anti-HIV / AIDS social program contribution.',
    )
    total_welfare_deductions = fields.Float(
        string='Total Welfare & Services',
        compute='_compute_all_deductions',
        store=True,
        digits=(16, 2),
    )

    # =========================================================================
    # 5. Food, Meat & Consumable Deductions
    # =========================================================================
    deduction_meat_meredaja = fields.Float(
        string='Meat Meredaja (የስጋ መረዳጃ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Meat meredaja consumable deduction.',
    )
    deduction_jimma_meat = fields.Float(
        string='Jimma Meat (የጅማ ስጋ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Jimma meat consumable deduction.',
    )
    deduction_suntu_meat = fields.Float(
        string='Suntu Meat (የሱንቱ ስጋ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Suntu meat consumable deduction.',
    )
    total_food_deductions = fields.Float(
        string='Total Meat & Consumables',
        compute='_compute_all_deductions',
        store=True,
        digits=(16, 2),
    )

    # =========================================================================
    # 6. Bank & Other Specific Deductions
    # =========================================================================
    deduction_dashen_bank = fields.Float(
        string='Dashen Bank (ዳሽን ባንክ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Dashen bank loan or deduction.',
    )
    deduction_awash = fields.Float(
        string='Awash (አዋሽ ባንክ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Awash bank loan or deduction.',
    )
    deduction_meredaja = fields.Float(
        string='Meredaja (መርጃ / እድር)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Organization or community meredaja / iddir deduction.',
    )
    total_bank_deductions = fields.Float(
        string='Total Bank & Specific',
        compute='_compute_all_deductions',
        store=True,
        digits=(16, 2),
    )

    # =========================================================================
    # Overall Totals
    # =========================================================================
    total_monthly_deductions = fields.Float(
        string='Total Monthly Deductions (ጠቅላላ ተቀናሽ)',
        compute='_compute_all_deductions',
        store=True,
        digits=(16, 2),
        help='Grand total of all monthly deductions configured on this contract.',
    )
    net_wage_after_deductions = fields.Float(
        string='Estimated Net Wage (የተጣራ ተገማች ደመወዝ)',
        compute='_compute_all_deductions',
        store=True,
        digits=(16, 2),
        help='Estimated net monthly wage after subtracting all contract deductions from basic wage.',
    )

    @api.depends('company_id', 'company_country_id')
    def _compute_clean_country_code(self):
        for contract in self:
            # Force country_code != 'US' so US pre-tax/post-tax benefits remain hidden
            contract.country_code = 'ET'

    @api.depends('salary_grade')
    def _compute_transport_policy(self):
        for c in self:
            if not c.salary_grade:
                c.transport_allowance_rule = 'fixed_4000'
            else:
                try:
                    g = int(c.salary_grade)
                    if g <= 17:
                        c.transport_allowance_rule = 'fixed_4000'
                    elif g == 18:
                        c.transport_allowance_rule = 'fuel_50'
                    else:
                        c.transport_allowance_rule = 'fuel_60'
                except Exception:
                    c.transport_allowance_rule = 'fixed_4000'

    @api.depends('transport_allowance_rule')
    def _compute_fuel_liters(self):
        for c in self:
            if c.transport_allowance_rule == 'fuel_50':
                c.fuel_liters = 50.0
            elif c.transport_allowance_rule == 'fuel_60':
                c.fuel_liters = 60.0
            else:
                c.fuel_liters = 0.0

    @api.onchange('salary_grade')
    def _onchange_salary_grade_transport(self):
        if self.salary_grade:
            try:
                g = int(self.salary_grade)
                fuel_price = self.fuel_price_per_liter or (self.company_id.fuel_price_per_liter if self.company_id else 165.0) or 165.0
                if g <= 17:
                    self.transport_allowance_rule = 'fixed_4000'
                    self.fuel_liters = 0.0
                    self.allowance_transport = 4000.0
                elif g == 18:
                    self.transport_allowance_rule = 'fuel_50'
                    self.fuel_liters = 50.0
                    self.allowance_transport = 50.0 * fuel_price
                else:
                    self.transport_allowance_rule = 'fuel_60'
                    self.fuel_liters = 60.0
                    self.allowance_transport = 60.0 * fuel_price
            except Exception:
                pass

    @api.onchange('transport_allowance_rule')
    def _onchange_transport_allowance_rule(self):
        fuel_price = self.fuel_price_per_liter or (self.company_id.fuel_price_per_liter if self.company_id else 165.0) or 165.0
        if self.transport_allowance_rule == 'fixed_4000':
            self.allowance_transport = 4000.0
            self.fuel_liters = 0.0
        elif self.transport_allowance_rule == 'fuel_50':
            self.fuel_liters = 50.0
            self.allowance_transport = 50.0 * fuel_price
        elif self.transport_allowance_rule == 'fuel_60':
            self.fuel_liters = 60.0
            self.allowance_transport = 60.0 * fuel_price
        elif self.transport_allowance_rule == 'none':
            self.allowance_transport = 0.0
            self.fuel_liters = 0.0

    @api.depends('wage', 'allowance_transport', 'allowance_electric_vehicle', 'allowance_hardship', 'allowance_retroactive', 'allowance_overtime')
    def _compute_all_allowances(self):
        for c in self:
            tot_allow = (c.allowance_transport or 0.0) + (c.allowance_electric_vehicle or 0.0) + \
                        (c.allowance_hardship or 0.0) + (c.allowance_retroactive or 0.0) + \
                        (c.allowance_overtime or 0.0)
            c.total_monthly_allowances = tot_allow
            c.gross_monthly_wage = (c.wage or 0.0) + tot_allow

    @api.depends(
        'wage',
        'gross_monthly_wage',
        # Category 1
        'deduction_pension', 'deduction_income_tax', 'deduction_luc',
        'deduction_credit_assoc_mandatory', 'deduction_social_contribution',
        # Category 2
        'deduction_advance', 'deduction_pre_payment', 'deduction_credit_assoc_loan',
        'deduction_medical_recovery', 'deduction_pension_receivable', 'deduction_fine',
        # Category 3
        'deduction_saving_kossa', 'deduction_saving_jimma', 'deduction_suntu_saving',
        'deduction_family_allotment', 'deduction_cost_sharing',
        # Category 4
        'deduction_ration', 'deduction_service', 'deduction_medical_8',
        'deduction_church_contribution', 'deduction_kindergarten', 'deduction_cafeteria',
        'deduction_school', 'deduction_sport', 'deduction_hiv',
        # Category 5
        'deduction_meat_meredaja', 'deduction_jimma_meat', 'deduction_suntu_meat',
        # Category 6
        'deduction_dashen_bank', 'deduction_awash', 'deduction_meredaja',
    )
    def _compute_all_deductions(self):
        for c in self:
            c1 = (c.deduction_pension or 0.0) + (c.deduction_income_tax or 0.0) + (c.deduction_luc or 0.0) + \
                 (c.deduction_credit_assoc_mandatory or 0.0) + (c.deduction_social_contribution or 0.0)
            c2 = (c.deduction_advance or 0.0) + (c.deduction_pre_payment or 0.0) + (c.deduction_credit_assoc_loan or 0.0) + \
                 (c.deduction_medical_recovery or 0.0) + (c.deduction_pension_receivable or 0.0) + (c.deduction_fine or 0.0)
            c3 = (c.deduction_saving_kossa or 0.0) + (c.deduction_saving_jimma or 0.0) + (c.deduction_suntu_saving or 0.0) + \
                 (c.deduction_family_allotment or 0.0) + (c.deduction_cost_sharing or 0.0)
            c4 = (c.deduction_ration or 0.0) + (c.deduction_service or 0.0) + (c.deduction_medical_8 or 0.0) + \
                 (c.deduction_church_contribution or 0.0) + (c.deduction_kindergarten or 0.0) + (c.deduction_cafeteria or 0.0) + \
                 (c.deduction_school or 0.0) + (c.deduction_sport or 0.0) + (c.deduction_hiv or 0.0)
            c5 = (c.deduction_meat_meredaja or 0.0) + (c.deduction_jimma_meat or 0.0) + (c.deduction_suntu_meat or 0.0)
            c6 = (c.deduction_dashen_bank or 0.0) + (c.deduction_awash or 0.0) + (c.deduction_meredaja or 0.0)

            c.total_statutory_deductions = c1
            c.total_loan_deductions = c2
            c.total_savings_deductions = c3
            c.total_welfare_deductions = c4
            c.total_food_deductions = c5
            c.total_bank_deductions = c6

            total = c1 + c2 + c3 + c4 + c5 + c6
            c.total_monthly_deductions = total
            gross = c.gross_monthly_wage if c.gross_monthly_wage else (c.wage or 0.0)
            c.net_wage_after_deductions = max(0.0, gross - total)

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



