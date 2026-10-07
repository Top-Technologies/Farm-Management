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

    name = fields.Char(
        string='Contract Reference',
        required=True,
        default=lambda self: _("New Contract"),
    )
    date_start = fields.Date(
        string='Start Date',
        required=True,
        default=fields.Date.today,
    )

    farm_employee_type = fields.Selection(
        related='employee_id.farm_employee_type',
        string='Employee Classification',
        store=True,
        index=True,
        readonly=True,
    )
    employment_term = fields.Selection(
        related='employee_id.employment_term',
        string='Employment Type',
        readonly=True,
    )

    # Salary Matrix Placement (Grade & Level Scale)
    salary_matrix_type = fields.Selection([
        ('head_office', 'Head Office (ዋና መ/ቤት)'),
        ('cpw', 'CPW'),
        ('farm', 'Farm (የእርሻ ልማቶች)'),
        ('saudi_star', 'Saudi Star (ሳዑዲ ስታር)'),
        ('other', 'Other / Custom (ሌላ)'),
    ], string='Salary Scale Category', tracking=True, help='Select which Salary Matrix applies to this contract.')

    salary_matrix_id = fields.Many2one(
        'hr.salary.matrix',
        string='Salary Scale Sheet',
        domain="[('matrix_type', '=', salary_matrix_type)] if salary_matrix_type else []",
        tracking=True,
        help='Specific Salary Matrix Scale sheet applied to this contract. Defaults to the active scale for the selected category.',
    )

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
    back_pay_previous_tax = fields.Float(
        string='Previous Monthly Income Tax (የቀድሞ የገቢ ግብር)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Monthly income tax from previous payslip before retroactive adjustment.',
    )
    back_pay_previous_pension = fields.Float(
        string='Previous Monthly Pension 7% (የቀድሞ ጡረታ 7%)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Monthly 7% employee pension from previous payslip before retroactive adjustment.',
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
    back_pay_tax_monthly = fields.Float(
        string='Monthly Back Pay Income Tax (ወርሃዊ የተከማቸ የገቢ ግብር)',
        compute='_compute_back_pay',
        store=True,
        digits=(16, 2),
        help='Monthly income tax difference between new and previous wage.',
    )
    back_pay_tax_total = fields.Float(
        string='Total Back Pay Income Tax (ጠቅላላ የተከማቸ የገቢ ግብር)',
        compute='_compute_back_pay',
        store=True,
        digits=(16, 2),
        help='Total income tax for the retroactive period (for government reporting, not deducted from net).',
    )
    back_pay_pension_monthly = fields.Float(
        string='Monthly Back Pay Pension 7% (ወርሃዊ የተከማቸ ጡረታ 7%)',
        compute='_compute_back_pay',
        store=True,
        digits=(16, 2),
        help='Monthly 7% employee pension difference between new and previous wage.',
    )
    back_pay_pension_total = fields.Float(
        string='Total Back Pay Pension 7% (ጠቅላላ የተከማቸ ጡረታ 7%)',
        compute='_compute_back_pay',
        store=True,
        digits=(16, 2),
        help='Total 7% employee pension for the retroactive period (for government reporting, not deducted from net).',
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
    has_pension = fields.Boolean(
        string='Pension Scheme (የጡረታ ተጠቃሚ)',
        default=True,
        tracking=True,
        help='Indicates whether employee is enrolled in the pension scheme. When disabled, 7% employee and 11% company pension will not be deducted.',
    )
    deduction_pension = fields.Float(
        string='Pension 7% (የጡረታ መዋጮ)',
        compute='_compute_statutory_taxes',
        store=True,
        readonly=False,
        digits=(16, 2),
        tracking=True,
        help='Legally required employee pension deduction (7% of Basic Salary).',
    )
    taxable_transport_allowance = fields.Float(
        string='Taxable Transport Allowance (የሚገበር የመጓጓዣ አበል)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Monthly transport allowance portion subject to employee income tax. Defaults to Transport Allowance.',
    )
    deduction_income_tax = fields.Float(
        string='Income Tax (የገቢ ግብር)',
        compute='_compute_statutory_taxes',
        store=True,
        readonly=False,
        digits=(16, 2),
        tracking=True,
        help='Statutory employee income tax calculated progressively from Taxable Salary.',
    )
    deduction_luc = fields.Float(
        string='L.U.C 1% (የሰራተኛ ማህበር 1%)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Labor Union Contribution (1%).',
    )
    has_credit_association = fields.Boolean(
        string='Credit Association Member (የብድርና ቁጠባ አባል)',
        default=True,
        tracking=True,
        help='Indicates whether employee is enrolled in Credit Association. When enabled, mandatory 5% of base wage is calculated.',
    )
    deduction_credit_assoc_mandatory = fields.Float(
        string='Credit Association - Mandatory (5% of Base) (የብድርና ቁጠባ አስገዳጅ)',
        compute='_compute_credit_association_deductions',
        store=True,
        readonly=False,
        digits=(16, 2),
        tracking=True,
        help='Mandatory 5% credit association contribution computed from base salary.',
    )
    credit_assoc_voluntary_rate = fields.Float(
        string='Credit Association Voluntary Rate (%) (የብድርና ቁጠባ ፈቃደኝነት %)',
        digits=(5, 2),
        default=0.0,
        tracking=True,
        help='Voluntary credit association contribution percentage deducted from basic salary.',
    )
    deduction_credit_assoc_voluntary = fields.Float(
        string='Credit Association - Voluntary (የብድርና ቁጠባ ፈቃደኝነት)',
        compute='_compute_credit_association_deductions',
        store=True,
        readonly=True,
        digits=(16, 2),
        tracking=True,
        help='Voluntary additional credit association contribution amount, computed from basic salary and voluntary percentage.',
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
    deduction_short_term_loan = fields.Float(
        string='Short Term Loan (የአጭር ጊዜ ብድር)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Short term loan repayment installment.',
    )
    deduction_long_term_loan = fields.Float(
        string='Long Term Loan (የረጅም ጊዜ ብድር)',
        digits=(16, 2),
        default=0.0,
        tracking=True,
        help='Long term loan repayment installment.',
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
                    self.taxable_transport_allowance = 4000.0
                elif g == 18:
                    self.transport_allowance_rule = 'fuel_50'
                    self.fuel_liters = 50.0
                    self.allowance_transport = 50.0 * fuel_price
                    self.taxable_transport_allowance = 50.0 * fuel_price
                else:
                    self.transport_allowance_rule = 'fuel_60'
                    self.fuel_liters = 60.0
                    self.allowance_transport = 60.0 * fuel_price
                    self.taxable_transport_allowance = 60.0 * fuel_price
            except Exception:
                pass

    @api.onchange('transport_allowance_rule')
    def _onchange_transport_allowance_rule(self):
        fuel_price = self.fuel_price_per_liter or (self.company_id.fuel_price_per_liter if self.company_id else 165.0) or 165.0
        if self.transport_allowance_rule == 'fixed_4000':
            self.allowance_transport = 4000.0
            self.taxable_transport_allowance = 4000.0
            self.fuel_liters = 0.0
        elif self.transport_allowance_rule == 'fuel_50':
            self.fuel_liters = 50.0
            self.allowance_transport = 50.0 * fuel_price
            self.taxable_transport_allowance = 50.0 * fuel_price
        elif self.transport_allowance_rule == 'fuel_60':
            self.fuel_liters = 60.0
            self.allowance_transport = 60.0 * fuel_price
            self.taxable_transport_allowance = 60.0 * fuel_price
        elif self.transport_allowance_rule == 'none':
            self.allowance_transport = 0.0
            self.taxable_transport_allowance = 0.0
            self.fuel_liters = 0.0

    @api.onchange('allowance_transport')
    def _onchange_allowance_transport(self):
        if not self.taxable_transport_allowance or (hasattr(self, '_origin') and self._origin.allowance_transport == self.taxable_transport_allowance):
            self.taxable_transport_allowance = self.allowance_transport or 0.0

    @api.onchange('taxable_transport_allowance')
    def _onchange_taxable_transport_allowance(self):
        self._compute_statutory_taxes()
        self._compute_all_deductions()

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
        'has_pension', 'deduction_pension', 'deduction_income_tax', 'deduction_luc',
        'has_credit_association', 'deduction_credit_assoc_mandatory', 'deduction_credit_assoc_voluntary',
        'deduction_social_contribution',
        # Category 2
        'deduction_advance', 'deduction_pre_payment', 'deduction_credit_assoc_loan',
        'deduction_short_term_loan', 'deduction_long_term_loan',
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
                 (c.deduction_credit_assoc_mandatory or 0.0) + (c.deduction_credit_assoc_voluntary or 0.0) + \
                 (c.deduction_social_contribution or 0.0)
            c2 = (c.deduction_advance or 0.0) + (c.deduction_pre_payment or 0.0) + (c.deduction_credit_assoc_loan or 0.0) + \
                 (c.deduction_short_term_loan or 0.0) + (c.deduction_long_term_loan or 0.0) + \
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

    @api.depends('salary_matrix_id', 'salary_matrix_type', 'salary_grade_id', 'salary_grade', 'salary_level', 'company_id')
    def _compute_matrix_basic_wage(self):
        for contract in self:
            grade_val = contract.salary_grade_id.grade if contract.salary_grade_id else (int(contract.salary_grade) if contract.salary_grade else False)
            if grade_val and contract.salary_level:
                try:
                    wage = 0.0
                    if contract.salary_matrix_id:
                        wage = contract.salary_matrix_id.get_wage(grade_val, contract.salary_level)
                    elif contract.salary_matrix_type:
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
            # Auto-assign active matrix for this type if none or mismatched
            if not self.salary_matrix_id or self.salary_matrix_id.matrix_type != self.salary_matrix_type:
                active_matrix = self.env['hr.salary.matrix'].search([
                    ('matrix_type', '=', self.salary_matrix_type),
                    ('active', '=', True),
                    ('company_id', '=', self.company_id.id if self.company_id else self.env.company.id),
                ], limit=1, order='effective_date desc, id desc')
                if not active_matrix:
                    active_matrix = self.env['hr.salary.matrix'].search([
                        ('matrix_type', '=', self.salary_matrix_type),
                        ('active', '=', True),
                    ], limit=1, order='effective_date desc, id desc')
                self.salary_matrix_id = active_matrix.id if active_matrix else False

            if self.salary_grade_id and self.salary_grade_id.matrix_type != self.salary_matrix_type:
                self.salary_grade_id = False
                self.salary_grade = False
                self.matrix_basic_wage = 0.0

        self._onchange_salary_matrix_wage()

    @api.onchange('salary_matrix_id')
    def _onchange_salary_matrix_id(self):
        if self.salary_matrix_id:
            if not self.salary_matrix_type or self.salary_matrix_type != self.salary_matrix_id.matrix_type:
                self.salary_matrix_type = self.salary_matrix_id.matrix_type
        self._onchange_salary_matrix_wage()

    @api.onchange('salary_grade_id')
    def _onchange_salary_grade_id(self):
        if self.salary_grade_id:
            self.salary_grade = str(self.salary_grade_id.grade)
            self._onchange_salary_grade_transport()
        else:
            self.salary_grade = False
        self._onchange_salary_matrix_wage()

    @api.onchange('salary_matrix_id', 'salary_matrix_type', 'salary_grade_id', 'salary_grade', 'salary_level')
    def _onchange_salary_matrix_wage(self):
        grade_val = self.salary_grade_id.grade if self.salary_grade_id else (int(self.salary_grade) if self.salary_grade else False)
        if grade_val and self.salary_level:
            wage = 0.0
            if self.salary_matrix_id:
                wage = self.salary_matrix_id.get_wage(grade_val, self.salary_level)
            elif self.salary_matrix_type:
                wage = self.env['hr.salary.matrix'].get_matrix_wage(
                    matrix_type=self.salary_matrix_type,
                    grade=int(grade_val),
                    level=self.salary_level,
                    company_id=self.company_id.id if self.company_id else None,
                )
            if wage > 0:
                self.matrix_basic_wage = wage
                self.wage = wage
                self._compute_statutory_taxes()

    @api.onchange('employee_id')
    def _onchange_employee_matrix_default(self):
        if self.employee_id:
            if self.employee_id.farm_employee_type == 'head_office':
                self.salary_matrix_type = 'head_office'
            elif self.employee_id.farm_employee_type == 'cpw':
                self.salary_matrix_type = 'cpw'
            elif self.employee_id.farm_employee_type == 'permanent':
                self.salary_matrix_type = 'farm'
            elif not self.salary_matrix_type:
                self.salary_matrix_type = 'head_office'
            self._onchange_salary_matrix_type()

    # =========================================================================
    # Statutory Taxes Dynamic Computation
    # =========================================================================
    @api.depends('wage', 'taxable_transport_allowance', 'allowance_transport', 'allowance_hardship', 'allowance_overtime', 'has_pension')
    def _compute_statutory_taxes(self):
        for c in self:
            wage = c.wage or 0.0
            # 7% Employee Pension based on basic wage
            if c.has_pension:
                c.deduction_pension = round(wage * 0.07, 2)
            else:
                c.deduction_pension = 0.0

            # Taxable Salary = Wage + Taxable Allowances (Taxable Transport, Hardship, Overtime)
            trans_taxable = c.taxable_transport_allowance or 0.0
            taxable = wage + trans_taxable + \
                      (c.allowance_hardship or 0.0) + (c.allowance_overtime or 0.0)

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

            c.deduction_income_tax = round(max(0.0, tax), 2)

    @api.depends('wage', 'has_credit_association', 'credit_assoc_voluntary_rate')
    def _compute_credit_association_deductions(self):
        for c in self:
            wage = c.wage or 0.0
            if c.has_credit_association:
                c.deduction_credit_assoc_mandatory = round(wage * 0.05, 2)
            else:
                c.deduction_credit_assoc_mandatory = 0.0

            rate = c.credit_assoc_voluntary_rate or 0.0
            c.deduction_credit_assoc_voluntary = round(wage * (rate / 100.0), 2)

    @api.onchange('wage', 'has_credit_association', 'credit_assoc_voluntary_rate')
    def _onchange_credit_association(self):
        self._compute_credit_association_deductions()
        self._compute_all_deductions()

    @api.onchange('wage', 'taxable_transport_allowance', 'allowance_transport', 'credit_assoc_voluntary_rate', 'has_credit_association', 'allowance_hardship', 'allowance_overtime', 'has_pension')
    def _onchange_wage_taxes_estimate(self):
        for c in self:
            c._compute_statutory_taxes()
            c._compute_credit_association_deductions()
            c._compute_all_deductions()

    # =========================================================================
    # Back Pay / Retroactive Adjustment Computation & Logic
    # =========================================================================
    def action_fetch_previous_payslip(self):
        """Fetches the previous month's net salary, income tax, and pension 7% from the employee's last confirmed payslip."""
        for c in self:
            c._fetch_previous_payslip_data()

    def _fetch_previous_payslip_data(self):
        for c in self:
            if not c.employee_id:
                continue
            payslip = self.env['hr.payslip'].search([
                ('employee_id', '=', c.employee_id.id),
                ('state', 'in', ('done', 'paid', 'verify')),
            ], order='date_to desc, id desc', limit=1)
            if not payslip:
                payslip = self.env['hr.payslip'].search([
                    ('employee_id', '=', c.employee_id.id),
                    ('state', '!=', 'cancel'),
                ], order='date_to desc, id desc', limit=1)
            if payslip:
                net_line = payslip.line_ids.filtered(lambda l: l.code == 'NET')
                net_val = net_line[0].total if net_line else payslip.net_wage
                c.back_pay_previous_net = net_val or 0.0

                tax_line = payslip.line_ids.filtered(lambda l: l.code == 'DED_INCOME_TAX')
                c.back_pay_previous_tax = abs(tax_line[0].total) if tax_line else 0.0

                pension_line = payslip.line_ids.filtered(lambda l: l.code == 'DED_PENSION_7')
                c.back_pay_previous_pension = abs(pension_line[0].total) if pension_line else 0.0

    @api.depends(
        'back_pay_months',
        'back_pay_previous_net',
        'back_pay_previous_tax',
        'back_pay_previous_pension',
        'wage',
        'allowance_transport',
        'taxable_transport_allowance',
        'allowance_hardship',
        'allowance_overtime',
        'has_pension',
        'total_monthly_deductions',
    )
    def _compute_back_pay(self):
        for c in self:
            wage = c.wage or 0.0
            # Regular monthly net without retroactive addition
            regular_gross = wage + (c.allowance_transport or 0.0) + \
                            (c.allowance_hardship or 0.0) + (c.allowance_overtime or 0.0)
            regular_net = max(0.0, regular_gross - (c.total_monthly_deductions or 0.0))
            c.back_pay_new_net = regular_net

            # Statutory taxes on new regular salary
            new_pension = round(wage * 0.07, 2) if c.has_pension else 0.0
            trans_taxable = c.taxable_transport_allowance or 0.0
            taxable = wage + trans_taxable + (c.allowance_hardship or 0.0) + (c.allowance_overtime or 0.0)
            if taxable <= 2000:
                new_tax = 0.0
            elif taxable <= 4000:
                new_tax = 0.15 * taxable - 300.0
            elif taxable <= 7000:
                new_tax = 0.20 * taxable - 500.0
            elif taxable <= 10000:
                new_tax = 0.25 * taxable - 850.0
            elif taxable <= 14000:
                new_tax = 0.30 * taxable - 1350.0
            else:
                new_tax = 0.35 * taxable - 2050.0
            new_tax = round(max(0.0, new_tax), 2)

            prev_tax = c.back_pay_previous_tax or 0.0
            prev_pension = c.back_pay_previous_pension or 0.0

            monthly_tax_diff = max(0.0, round(new_tax - prev_tax, 2)) if (new_tax > prev_tax and prev_tax > 0) else 0.0
            monthly_pension_diff = max(0.0, round(new_pension - prev_pension, 2)) if (new_pension > prev_pension and prev_pension > 0) else 0.0

            if c.back_pay_months > 0 and c.back_pay_previous_net > 0:
                monthly_diff = max(0.0, round(regular_net - c.back_pay_previous_net, 2))
                total_back_pay = round(monthly_diff * c.back_pay_months, 2)
                c.back_pay_monthly_diff = monthly_diff
                c.back_pay_total = total_back_pay
                c.allowance_retroactive = total_back_pay

                c.back_pay_tax_monthly = monthly_tax_diff
                c.back_pay_tax_total = round(monthly_tax_diff * c.back_pay_months, 2)
                c.back_pay_pension_monthly = monthly_pension_diff
                c.back_pay_pension_total = round(monthly_pension_diff * c.back_pay_months, 2)
            elif c.back_pay_months > 0 and c.allowance_retroactive > 0:
                c.back_pay_total = c.allowance_retroactive
                c.back_pay_monthly_diff = round(c.allowance_retroactive / c.back_pay_months, 2)
                c.back_pay_tax_monthly = monthly_tax_diff
                c.back_pay_tax_total = round(monthly_tax_diff * c.back_pay_months, 2)
                c.back_pay_pension_monthly = monthly_pension_diff
                c.back_pay_pension_total = round(monthly_pension_diff * c.back_pay_months, 2)
            else:
                c.back_pay_monthly_diff = 0.0
                c.back_pay_total = c.allowance_retroactive or 0.0
                c.back_pay_tax_monthly = 0.0
                c.back_pay_tax_total = 0.0
                c.back_pay_pension_monthly = 0.0
                c.back_pay_pension_total = 0.0

    @api.onchange('back_pay_months', 'back_pay_previous_net', 'wage', 'allowance_transport', 'taxable_transport_allowance', 'allowance_hardship', 'allowance_overtime', 'total_monthly_deductions')
    def _onchange_back_pay_calculator(self):
        if self.back_pay_months > 0 and not self.back_pay_previous_net:
            self._fetch_previous_payslip_data()

        wage = self.wage or 0.0
        regular_gross = wage + (self.allowance_transport or 0.0) + \
                        (self.allowance_hardship or 0.0) + (self.allowance_overtime or 0.0)
        regular_net = max(0.0, regular_gross - (self.total_monthly_deductions or 0.0))
        self.back_pay_new_net = regular_net

        new_pension = round(wage * 0.07, 2)
        trans_taxable = self.taxable_transport_allowance or 0.0
        taxable = wage + trans_taxable + (self.allowance_hardship or 0.0) + (self.allowance_overtime or 0.0)
        if taxable <= 2000:
            new_tax = 0.0
        elif taxable <= 4000:
            new_tax = 0.15 * taxable - 300.0
        elif taxable <= 7000:
            new_tax = 0.20 * taxable - 500.0
        elif taxable <= 10000:
            new_tax = 0.25 * taxable - 850.0
        elif taxable <= 14000:
            new_tax = 0.30 * taxable - 1350.0
        else:
            new_tax = 0.35 * taxable - 2050.0
        new_tax = round(max(0.0, new_tax), 2)

        prev_tax = self.back_pay_previous_tax or 0.0
        prev_pension = self.back_pay_previous_pension or 0.0

        monthly_tax_diff = max(0.0, round(new_tax - prev_tax, 2)) if (new_tax > prev_tax and prev_tax > 0) else 0.0
        monthly_pension_diff = max(0.0, round(new_pension - prev_pension, 2)) if (new_pension > prev_pension and prev_pension > 0) else 0.0

        if self.back_pay_months > 0 and self.back_pay_previous_net > 0:
            monthly_diff = max(0.0, round(regular_net - self.back_pay_previous_net, 2))
            total_back_pay = round(monthly_diff * self.back_pay_months, 2)
            self.back_pay_monthly_diff = monthly_diff
            self.back_pay_total = total_back_pay
            self.allowance_retroactive = total_back_pay

            self.back_pay_tax_monthly = monthly_tax_diff
            self.back_pay_tax_total = round(monthly_tax_diff * self.back_pay_months, 2)
            self.back_pay_pension_monthly = monthly_pension_diff
            self.back_pay_pension_total = round(monthly_pension_diff * self.back_pay_months, 2)

    def action_approve_back_pay(self):
        for c in self:
            c.is_back_pay_approved = True

    def action_reset_back_pay(self):
        for c in self:
            c.write({
                'back_pay_months': 0,
                'back_pay_previous_net': 0.0,
                'back_pay_previous_tax': 0.0,
                'back_pay_previous_pension': 0.0,
                'back_pay_tax_monthly': 0.0,
                'back_pay_tax_total': 0.0,
                'back_pay_pension_monthly': 0.0,
                'back_pay_pension_total': 0.0,
                'back_pay_monthly_diff': 0.0,
                'back_pay_total': 0.0,
                'allowance_retroactive': 0.0,
                'is_back_pay_approved': False,
                'back_pay_justification': False,
            })

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # 1. Ensure 'name' is never empty / null to satisfy database NOT NULL constraint
            if not vals.get('name') or vals.get('name') == _("New Contract"):
                emp = False
                if vals.get('employee_id'):
                    emp = self.env['hr.employee'].browse(vals['employee_id'])
                elif self.env.context.get('default_employee_id'):
                    emp = self.env['hr.employee'].browse(self.env.context['default_employee_id'])

                if emp and emp.name:
                    vals['name'] = f"{emp.name} - Contract"
                else:
                    vals['name'] = _("Contract")

            # 2. Ensure salary_matrix_type is set (defaults to scale of grade, or employee type, or 'farm')
            if not vals.get('salary_matrix_type'):
                if vals.get('salary_grade_id'):
                    grade_rec = self.env['hr.salary.matrix.grade'].browse(vals['salary_grade_id'])
                    if grade_rec.matrix_type:
                        vals['salary_matrix_type'] = grade_rec.matrix_type
                if not vals.get('salary_matrix_type'):
                    emp = self.env['hr.employee'].browse(vals.get('employee_id')) if vals.get('employee_id') else False
                    if emp and emp.farm_employee_type == 'head_office':
                        vals['salary_matrix_type'] = 'head_office'
                    elif emp and emp.farm_employee_type == 'cpw':
                        vals['salary_matrix_type'] = 'cpw'
                    else:
                        vals['salary_matrix_type'] = 'farm'

            # 3. Synchronize legacy salary_grade selection
            if vals.get('salary_grade_id') and not vals.get('salary_grade'):
                grade_rec = self.env['hr.salary.matrix.grade'].browse(vals['salary_grade_id'])
                if grade_rec.grade:
                    vals['salary_grade'] = str(grade_rec.grade)

            # 4. Auto-populate basic wage from Salary Matrix if wage is missing / zero
            if not vals.get('wage'):
                m_id = vals.get('salary_matrix_id')
                m_type = vals.get('salary_matrix_type')
                g_val = vals.get('salary_grade')
                if not g_val and vals.get('salary_grade_id'):
                    g_val = self.env['hr.salary.matrix.grade'].browse(vals['salary_grade_id']).grade
                l_val = vals.get('salary_level')
                if g_val and l_val:
                    try:
                        matrix_wage = 0.0
                        if m_id:
                            matrix_wage = self.env['hr.salary.matrix'].browse(m_id).get_wage(g_val, l_val)
                        elif m_type:
                            matrix_wage = self.env['hr.salary.matrix'].get_matrix_wage(
                                matrix_type=m_type,
                                grade=int(g_val),
                                level=l_val,
                                company_id=vals.get('company_id')
                            )
                        if matrix_wage > 0:
                            vals['wage'] = matrix_wage
                            vals['matrix_basic_wage'] = matrix_wage
                    except Exception:
                        pass
                if not vals.get('wage'):
                    vals['wage'] = 0.0

            # 5. Ensure 'date_start' is never empty / null to satisfy database NOT NULL constraint
            if not vals.get('date_start'):
                vals['date_start'] = fields.Date.today()

            # 6. Default taxable_transport_allowance from allowance_transport if not provided
            if vals.get('allowance_transport') and not vals.get('taxable_transport_allowance'):
                vals['taxable_transport_allowance'] = vals['allowance_transport']

        return super().create(vals_list)

    def write(self, vals):
        if 'allowance_transport' in vals and 'taxable_transport_allowance' not in vals:
            for contract in self:
                if not contract.taxable_transport_allowance or (contract.allowance_transport and contract.taxable_transport_allowance == contract.allowance_transport):
                    vals['taxable_transport_allowance'] = vals['allowance_transport']
                    break
        return super().write(vals)

    def init(self):
        super().init()
        # Default existing contracts with NULL has_pension to True (enrolled) and backfill taxable_transport_allowance
        self.env.cr.execute("""
            DO $$ 
            BEGIN 
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'hr_contract' AND column_name = 'has_pension'
                ) THEN 
                    UPDATE hr_contract SET has_pension = true WHERE has_pension IS NULL;
                END IF; 
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'hr_contract' AND column_name = 'taxable_transport_allowance'
                ) THEN 
                    UPDATE hr_contract 
                    SET taxable_transport_allowance = allowance_transport 
                    WHERE taxable_transport_allowance IS NULL OR (taxable_transport_allowance = 0 AND allowance_transport > 0);
                END IF; 
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'hr_contract' AND column_name = 'credit_assoc_voluntary_rate'
                ) THEN 
                    UPDATE hr_contract 
                    SET credit_assoc_voluntary_rate = round((deduction_credit_assoc_voluntary / wage) * 100.0, 2) 
                    WHERE wage > 0 AND deduction_credit_assoc_voluntary > 0 AND (credit_assoc_voluntary_rate IS NULL OR credit_assoc_voluntary_rate = 0);
                END IF;
            END $$;
        """)




