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

    salary_grade_id = fields.Many2one(
        'hr.salary.matrix.grade',
        string='Salary Grade (ደረጃ)',
        tracking=True,
        help='Employee grade dynamically filtered by the selected Salary Matrix Scale.',
    )

    salary_grade = fields.Selection([
        (str(i), f'Grade {i} (ደረጃ {i})') for i in range(1, 23)
    ], string='Salary Grade (Legacy Code)', tracking=True, help='Employee grade from Grade 1 to Grade 22.')

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

    # Back Pay / Retroactive Salary Adjustment Management
    back_pay_months = fields.Integer(
        string='Retroactive Months (የወራት ብዛት)',
        default=0,
        tracking=True,
        help='Number of retroactive months to calculate and pay the salary difference for.',
    )
    back_pay_previous_net = fields.Float(
        string='Previous Monthly Net Salary (የቀድሞ የተጣራ ደመወዝ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='The actual net monthly take-home salary the employee received prior to the approved raise.',
    )
    back_pay_new_net = fields.Float(
        string='Corrected Monthly Net Salary (አዲሱ የተጣራ ደመወዝ)',
        compute='_compute_back_pay',
        store=True,
        readonly=False,
        digits=(16, 2),
        tracking=True,
        help='The corrected monthly net salary with the approved raise (Regular Net Wage).',
    )
    back_pay_monthly_diff = fields.Float(
        string='Monthly Back Pay Difference (ወርሃዊ ልዩነት)',
        compute='_compute_back_pay',
        store=True,
        digits=(16, 2),
        help='Monthly Back Pay = Corrected Net Salary - Previous Net Salary.',
    )
    back_pay_total = fields.Float(
        string='Total Back Pay Amount (ጠቅላላ የተከማቸ ክፍያ)',
        compute='_compute_back_pay',
        store=True,
        digits=(16, 2),
        help='Total Back Pay = Monthly Difference × Number of Months.',
    )
    is_back_pay_approved = fields.Boolean(
        string='Finance Manager Approval (የፋይናንስ ማረጋገጫ)',
        default=False,
        tracking=True,
        help='Finance Manager approval is required before retroactive back pay is included on payslips.',
    )
    back_pay_justification = fields.Char(
        string='Back Pay Reason / Period Note',
        tracking=True,
        help='e.g. Retroactive promotion approved from Tir to Megabit.',
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
    deduction_dashen_credit = fields.Float(
        string='Dashen Bank – Loan / Credit (ዳሽን ባንክ ብድር)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Monthly loan repayment installment for Dashen Bank.',
    )
    deduction_dashen_saving = fields.Float(
        string='Dashen Bank – Savings (ዳሽን ባንክ ቁጠባ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Voluntary monthly savings deduction deposited to Dashen Bank.',
    )
    deduction_awash_credit = fields.Float(
        string='Awash Bank – Loan / Credit (አዋሽ ባንክ ብድር)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Monthly loan repayment installment for Awash Bank.',
    )
    deduction_awash_saving = fields.Float(
        string='Awash Bank – Savings (አዋሽ ባንክ ቁጠባ)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Voluntary monthly savings deduction deposited to Awash Bank.',
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

    @api.depends('salary_grade_id', 'salary_grade')
    def _compute_transport_policy(self):
        for c in self:
            grade_val = c.salary_grade_id.grade if c.salary_grade_id else (int(c.salary_grade) if c.salary_grade else False)
            if not grade_val:
                c.transport_allowance_rule = 'fixed_4000'
            else:
                try:
                    g = int(grade_val)
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

    @api.onchange('salary_grade_id', 'salary_grade')
    def _onchange_salary_grade_transport(self):
        grade_val = self.salary_grade_id.grade if self.salary_grade_id else (int(self.salary_grade) if self.salary_grade else False)
        if grade_val:
            try:
                g = int(grade_val)
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

    @api.depends('wage', 'allowance_transport', 'allowance_hardship', 'allowance_retroactive', 'allowance_overtime')
    def _compute_all_allowances(self):
        for c in self:
            tot_allow = (c.allowance_transport or 0.0) + \
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
        'deduction_dashen_credit', 'deduction_dashen_saving',
        'deduction_awash_credit', 'deduction_awash_saving', 'deduction_meredaja',
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
            c6 = (c.deduction_dashen_credit or 0.0) + (c.deduction_dashen_saving or 0.0) + \
                 (c.deduction_awash_credit or 0.0) + (c.deduction_awash_saving or 0.0) + (c.deduction_meredaja or 0.0)

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

    @api.depends('salary_matrix_type', 'salary_grade_id', 'salary_grade', 'salary_level', 'company_id')
    def _compute_matrix_basic_wage(self):
        for contract in self:
            grade_val = contract.salary_grade_id.grade if contract.salary_grade_id else (int(contract.salary_grade) if contract.salary_grade else False)
            if contract.salary_matrix_type and grade_val and contract.salary_level:
                try:
                    wage = self.env['hr.salary.matrix'].get_matrix_wage(
                        matrix_type=contract.salary_matrix_type,
                        grade=int(grade_val),
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

    @api.onchange('salary_matrix_type')
    def _onchange_salary_matrix_type(self):
        if self.salary_matrix_type:
            if self.salary_grade_id and self.salary_grade_id.matrix_type != self.salary_matrix_type:
                self.salary_grade_id = False
                self.salary_grade = False
                self.matrix_basic_wage = 0.0

    @api.onchange('salary_grade_id')
    def _onchange_salary_grade_id(self):
        if self.salary_grade_id:
            self.salary_grade = str(self.salary_grade_id.grade)
            self._onchange_salary_grade_transport()
        else:
            self.salary_grade = False
        self._onchange_salary_matrix_wage()

    @api.onchange('salary_matrix_type', 'salary_grade_id', 'salary_grade', 'salary_level')
    def _onchange_salary_matrix_wage(self):
        grade_val = self.salary_grade_id.grade if self.salary_grade_id else (int(self.salary_grade) if self.salary_grade else False)
        if self.salary_matrix_type and grade_val and self.salary_level:
            wage = self.env['hr.salary.matrix'].get_matrix_wage(
                matrix_type=self.salary_matrix_type,
                grade=int(grade_val),
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

    # =========================================================================
    # Back Pay / Retroactive Adjustment Computation & Logic
    # =========================================================================
    @api.depends(
        'back_pay_months',
        'back_pay_previous_net',
        'wage',
        'allowance_transport',
        'allowance_hardship',
        'allowance_overtime',
        'total_monthly_deductions',
    )
    def _compute_back_pay(self):
        for c in self:
            # Regular monthly net without retroactive addition
            regular_gross = (c.wage or 0.0) + (c.allowance_transport or 0.0) + \
                            (c.allowance_hardship or 0.0) + (c.allowance_overtime or 0.0)
            regular_net = max(0.0, regular_gross - (c.total_monthly_deductions or 0.0))
            c.back_pay_new_net = regular_net

            if c.back_pay_months > 0 and c.back_pay_previous_net > 0:
                monthly_diff = max(0.0, round(regular_net - c.back_pay_previous_net, 2))
                total_back_pay = round(monthly_diff * c.back_pay_months, 2)
                c.back_pay_monthly_diff = monthly_diff
                c.back_pay_total = total_back_pay
                c.allowance_retroactive = total_back_pay
            elif c.back_pay_months > 0 and c.allowance_retroactive > 0:
                c.back_pay_total = c.allowance_retroactive
                c.back_pay_monthly_diff = round(c.allowance_retroactive / c.back_pay_months, 2)
            else:
                c.back_pay_monthly_diff = 0.0
                c.back_pay_total = c.allowance_retroactive or 0.0

    @api.onchange('back_pay_months', 'back_pay_previous_net', 'wage', 'allowance_transport', 'allowance_hardship', 'allowance_overtime', 'total_monthly_deductions')
    def _onchange_back_pay_calculator(self):
        regular_gross = (self.wage or 0.0) + (self.allowance_transport or 0.0) + \
                        (self.allowance_hardship or 0.0) + (self.allowance_overtime or 0.0)
        regular_net = max(0.0, regular_gross - (self.total_monthly_deductions or 0.0))
        self.back_pay_new_net = regular_net

        if self.back_pay_months > 0 and self.back_pay_previous_net > 0:
            monthly_diff = max(0.0, round(regular_net - self.back_pay_previous_net, 2))
            total_back_pay = round(monthly_diff * self.back_pay_months, 2)
            self.back_pay_monthly_diff = monthly_diff
            self.back_pay_total = total_back_pay
            self.allowance_retroactive = total_back_pay

    @api.onchange('wage', 'allowance_transport', 'allowance_hardship', 'allowance_overtime')
    def _onchange_wage_taxes_estimate(self):
        if self.wage:
            # 7% Employee Pension
            if not self.deduction_pension:
                self.deduction_pension = round(self.wage * 0.07, 2)

            # Taxable Salary = Wage + Taxable Allowances (Transport, Hardship, Overtime)
            taxable = (self.wage or 0.0) + (self.allowance_transport or 0.0) + \
                      (self.allowance_hardship or 0.0) + (self.allowance_overtime or 0.0)
            if not self.deduction_income_tax:
                if taxable <= 2000:
                    tax = 0.0
                elif taxable <= 4000:
                    tax = 0.15 * taxable - 300.0
                elif taxable <= 7000:
                    tax = 0.20 * taxable - 500.0
                elif taxable <= 10000:
                    tax = 0.25 * taxable - 850.0
                elif taxable <= 14000:
                    tax = 0.30 * taxable - 1350.0
                else:
                    tax = 0.35 * taxable - 2050.0
                self.deduction_income_tax = round(max(0.0, tax), 2)

    def action_approve_back_pay(self):
        for c in self:
            c.is_back_pay_approved = True

    def action_reset_back_pay(self):
        for c in self:
            c.write({
                'back_pay_months': 0,
                'back_pay_previous_net': 0.0,
                'back_pay_monthly_diff': 0.0,
                'back_pay_total': 0.0,
                'allowance_retroactive': 0.0,
                'is_back_pay_approved': False,
                'back_pay_justification': False,
            })



