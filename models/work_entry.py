# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class FarmWorkEntry(models.Model):
    _name = 'farm.work.entry'
    _description = 'Farm Work Entry'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        tracking=True,
    )
    date = fields.Date(
        string='Work Date',
        required=True,
        default=fields.Date.today,
        tracking=True,
        index=True,
    )

    # Payment / Calculation Type
    entry_type = fields.Selection([
        ('piece_rate', 'Activity Piece Rate (Norm)'),
        ('temporary_rate', 'Temporary Worker (Daily Rate)'),
    ], string='Payment Type', default='piece_rate', required=True, tracking=True)

    work_duration = fields.Selection([
        ('half_day', 'Half Day (0.5)'),
        ('full_day', 'Full Day (1.0)'),
        ('one_and_half_day', 'Full Day + Half Day (1.5)'),
    ], string='Work Duration', default='full_day', tracking=True)

    # Employee & FMS Identifiers
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
        index=True,
    )
    fms_employee_id = fields.Char(
        string='Employee ID',
        related='employee_id.fms_employee_id',
        store=True,
        readonly=True,
        index=True,
        help='Auto-generated identifier in format: [FarmCode][TypeCode][SequentialNumber] (e.g. FM01T0001, FM03Z5283)',
    )
    employee_type = fields.Selection(
        related='employee_id.farm_employee_type',
        string='Employee Classification',
        store=True,
        readonly=True,
    )

    # Farm Location Hierarchy (Auto-filled based on current location)
    farm_id = fields.Many2one(
        'farm.farm',
        string='Farm',
        required=True,
        tracking=True,
        index=True,
    )
    sub_farm_id = fields.Many2one(
        'farm.sub.farm',
        string='Sub Farm',
        domain="[('farm_id', '=', farm_id)]",
        tracking=True,
    )
    sub_unit_id = fields.Many2one(
        'farm.sub.unit',
        string='Sub Unit',
        domain="[('sub_farm_id', '=', sub_farm_id)]",
        tracking=True,
    )
    block_id = fields.Many2one(
        'farm.block',
        string='Block',
        domain="[('sub_unit_id', '=', sub_unit_id)]",
        tracking=True,
    )

    # Activity & Piece-Rate Linkage
    activity_id = fields.Many2one(
        'farm.activity',
        string='Activity',
        tracking=True,
        index=True,
    )
    activity_code = fields.Char(
        string='Activity Code',
        related='activity_id.code',
        readonly=True,
    )

    # Temporary Worker Rate Linkage
    temporary_rate_id = fields.Many2one(
        'farm.temporary.rate',
        string='Temporary Rate Rule',
        compute='_compute_temporary_rate',
        store=True,
    )

    # Rates & Units
    uom_name = fields.Char(
        string='Unit of Measure',
        compute='_compute_rates',
        store=True,
        readonly=False,
    )
    norm_rate = fields.Float(
        string='Applied Rate',
        compute='_compute_rates',
        store=True,
        readonly=False,
        digits=(16, 2),
        tracking=True,
        help='Applicable productivity rate per unit (Piece Rate) or daily/half-day wage rate (Temporary Worker).',
    )
    score_value = fields.Float(
        string='Score / Days',
        required=True,
        default=1.0,
        digits=(16, 2),
        tracking=True,
        help='Amount of work performed (Score/Qty for Piece Rate, or 1.0 / 0.5 for Temporary Days).',
    )
    total_amount = fields.Float(
        string='Total Payment (Birr)',
        compute='_compute_total_amount',
        store=True,
        digits=(16, 2),
        tracking=True,
        help='Calculated total payment amount in Birr.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
    )

    # Status Workflow
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('approved', 'Approved'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, index=True)

    # Payroll & Payment Integration
    payment_status = fields.Selection([
        ('unpaid', 'Unpaid'),
        ('in_payroll', 'In Payroll'),
        ('paid', 'Paid'),
    ], string='Payment Status', default='unpaid', required=True, tracking=True, index=True)

    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Payslip',
        readonly=True,
        copy=False,
        ondelete='set null',
        tracking=True,
        index=True,
    )
    payslip_run_id = fields.Many2one(
        'hr.payslip.run',
        string='Payslip Batch',
        readonly=True,
        copy=False,
        ondelete='set null',
        tracking=True,
        index=True,
    )
    paid_date = fields.Date(
        string='Payment Date',
        readonly=True,
        copy=False,
        tracking=True,
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='farm_id.company_id',
        store=True,
        readonly=True,
    )
    notes = fields.Text(string='Notes / Remarks')

    @api.constrains('entry_type', 'employee_id', 'score_value', 'work_duration')
    def _check_temporary_worker_restriction(self):
        for entry in self:
            if entry.entry_type == 'temporary_rate':
                emp = entry.employee_id
                emp_code = (emp.fms_employee_id or emp.employee_code or '').upper()
                is_temp_type = emp.farm_employee_type == 'temporary'
                has_t_code = 'T' in emp_code if emp_code else is_temp_type

                if not (is_temp_type and has_t_code):
                    type_str = dict(emp._fields['farm_employee_type'].selection).get(emp.farm_employee_type, emp.farm_employee_type or 'Unknown')
                    raise ValidationError(_(
                        "Temporary Worker Daily Rate entries are ONLY permitted for Temporary Workers whose ID contains 'T'!\n\n"
                        "Employee '%s' (ID: %s) is classified as '%s'. "
                        "Please use Activity Piece Rate for Permanent and Zemach workers."
                    ) % (emp.name, emp.fms_employee_id or emp.id, type_str))

                if entry.score_value not in (0.5, 1.0, 1.5):
                    raise ValidationError(_(
                        "Temporary Worker work score must be strictly 0.5 (Half Day), 1.0 (Full Day), or 1.5 (Full + Half Day).\n"
                        "Received score: %s. Custom scores are not permitted for temporary workers."
                    ) % entry.score_value)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('farm.work.entry') or _('New')
            # Auto-populate location from employee if not explicitly passed
            if vals.get('employee_id') and not vals.get('farm_id'):
                emp = self.env['hr.employee'].browse(vals['employee_id'])
                curr = emp.current_transfer_id
                if curr and not curr.moving_date:
                    vals['farm_id'] = curr.farm_id.id
                    vals['sub_farm_id'] = curr.sub_farm_id.id if curr.sub_farm_id else False
                    vals['sub_unit_id'] = curr.sub_unit_id.id if curr.sub_unit_id else False
                    vals['block_id'] = curr.block_id.id if curr.block_id else False
                elif emp.current_farm_id:
                    vals['farm_id'] = emp.current_farm_id.id
                    vals['sub_farm_id'] = emp.current_sub_farm_id.id if emp.current_sub_farm_id else False
                    vals['sub_unit_id'] = emp.current_sub_unit_id.id if emp.current_sub_unit_id else False
                    vals['block_id'] = emp.current_block_id.id if emp.current_block_id else False
        return super().create(vals_list)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            # Auto-fill farm location from employee current location
            curr = self.employee_id.current_transfer_id
            if curr and not curr.moving_date:
                self.farm_id = curr.farm_id
                self.sub_farm_id = curr.sub_farm_id
                self.sub_unit_id = curr.sub_unit_id
                self.block_id = curr.block_id
            elif self.employee_id.current_farm_id:
                self.farm_id = self.employee_id.current_farm_id
                self.sub_farm_id = self.employee_id.current_sub_farm_id
                self.sub_unit_id = self.employee_id.current_sub_unit_id
                self.block_id = self.employee_id.current_block_id

            # Auto-suggest payment type: Temporary worker defaults to temporary rate; others default to piece rate
            if self.employee_id.farm_employee_type == 'temporary':
                self.entry_type = 'temporary_rate'
            else:
                self.entry_type = 'piece_rate'

    @api.onchange('work_duration')
    def _onchange_work_duration(self):
        if self.entry_type == 'temporary_rate':
            if self.work_duration == 'half_day':
                self.score_value = 0.5
            elif self.work_duration == 'one_and_half_day':
                self.score_value = 1.5
            else:
                self.score_value = 1.0

    @api.onchange('score_value')
    def _onchange_score_value(self):
        if self.entry_type == 'temporary_rate':
            if self.score_value == 0.5:
                self.work_duration = 'half_day'
            elif self.score_value == 1.5:
                self.work_duration = 'one_and_half_day'
            else:
                self.score_value = 1.0
                self.work_duration = 'full_day'

    @api.depends('farm_id', 'entry_type')
    def _compute_temporary_rate(self):
        for entry in self:
            if entry.entry_type == 'temporary_rate' and entry.farm_id:
                rate_rec = self.env['farm.temporary.rate'].search([
                    ('farm_id', '=', entry.farm_id.id),
                    ('active', '=', True),
                ], limit=1)
                entry.temporary_rate_id = rate_rec
            else:
                entry.temporary_rate_id = False

    @api.depends('entry_type', 'activity_id', 'farm_id', 'temporary_rate_id', 'score_value', 'work_duration')
    def _compute_rates(self):
        for entry in self:
            if entry.entry_type == 'piece_rate':
                if entry.activity_id and entry.farm_id:
                    norm_rec = self.env['farm.activity.norm'].search([
                        ('activity_id', '=', entry.activity_id.id),
                        ('farm_id', '=', entry.farm_id.id),
                    ], limit=1)
                    entry.norm_rate = norm_rec.norm_value if norm_rec else 0.0
                    entry.uom_name = entry.activity_id.uom_name or 'Birr/Kg'
                else:
                    entry.norm_rate = 0.0
                    entry.uom_name = 'Birr/Kg'
            elif entry.entry_type == 'temporary_rate':
                temp_rate = entry.temporary_rate_id
                if temp_rate:
                    if entry.score_value == 0.5 or entry.work_duration == 'half_day':
                        entry.norm_rate = temp_rate.half_day_rate
                        entry.uom_name = _('Birr/Half-Day')
                    elif entry.score_value == 1.5 or entry.work_duration == 'one_and_half_day':
                        entry.norm_rate = round(temp_rate.full_day_rate + temp_rate.half_day_rate, 2)
                        entry.uom_name = _('Birr/1.5-Day')
                    else:
                        entry.norm_rate = temp_rate.full_day_rate
                        entry.uom_name = _('Birr/Day')
                else:
                    entry.norm_rate = 0.0
                    entry.uom_name = _('Birr/Day')

    @api.depends('score_value', 'norm_rate', 'entry_type', 'temporary_rate_id', 'work_duration')
    def _compute_total_amount(self):
        for entry in self:
            if entry.entry_type == 'temporary_rate':
                temp_rate = entry.temporary_rate_id
                if temp_rate:
                    if entry.score_value == 0.5 or entry.work_duration == 'half_day':
                        entry.total_amount = temp_rate.half_day_rate
                    elif entry.score_value == 1.5 or entry.work_duration == 'one_and_half_day':
                        entry.total_amount = round(temp_rate.full_day_rate + temp_rate.half_day_rate, 2)
                    else:
                        entry.total_amount = temp_rate.full_day_rate
                else:
                    entry.total_amount = (entry.score_value or 0.0) * (entry.norm_rate or 0.0)
            else:
                entry.total_amount = (entry.score_value or 0.0) * (entry.norm_rate or 0.0)

    @api.onchange('farm_id')
    def _onchange_farm_id(self):
        if self.sub_farm_id and self.sub_farm_id.farm_id != self.farm_id:
            self.sub_farm_id = False
            self.sub_unit_id = False
            self.block_id = False

    @api.onchange('sub_farm_id')
    def _onchange_sub_farm_id(self):
        if self.sub_farm_id:
            self.farm_id = self.sub_farm_id.farm_id
            if self.sub_unit_id and self.sub_unit_id.sub_farm_id != self.sub_farm_id:
                self.sub_unit_id = False
                self.block_id = False

    @api.onchange('sub_unit_id')
    def _onchange_sub_unit_id(self):
        if self.sub_unit_id:
            self.sub_farm_id = self.sub_unit_id.sub_farm_id
            self.farm_id = self.sub_unit_id.farm_id
            if self.block_id and self.block_id.sub_unit_id != self.sub_unit_id:
                self.block_id = False

    @api.onchange('block_id')
    def _onchange_block_id(self):
        if self.block_id:
            self.sub_unit_id = self.block_id.sub_unit_id
            self.sub_farm_id = self.block_id.sub_farm_id
            self.farm_id = self.block_id.farm_id

    # State Workflow Actions
    def action_confirm(self):
        for entry in self:
            if entry.score_value <= 0:
                raise ValidationError(_("Score / Days worked must be greater than zero!"))
            if entry.entry_type == 'piece_rate' and not entry.activity_id:
                raise ValidationError(_("Please select an Activity for Piece Rate work entry!"))
            if entry.entry_type == 'temporary_rate':
                emp = entry.employee_id
                emp_code = (emp.fms_employee_id or emp.employee_code or '').upper()
                if emp.farm_employee_type != 'temporary' or ('T' not in emp_code if emp_code else False):
                    raise ValidationError(_(
                        "Temporary Worker Daily Rate entries are ONLY permitted for Temporary Workers (IDs containing 'T')!\n\n"
                        "Employee '%s' (ID: %s) is not a Temporary Worker."
                    ) % (emp.name, emp.fms_employee_id or emp.id))
                if entry.score_value not in (0.5, 1.0, 1.5):
                    raise ValidationError(_("Temporary Worker work score must be strictly 0.5 (Half Day), 1.0 (Full Day), or 1.5 (Full + Half Day)."))
            entry.state = 'confirmed'

    def action_approve(self):
        for entry in self:
            entry.state = 'approved'

    def action_draft(self):
        for entry in self:
            if entry.payment_status == 'paid':
                raise ValidationError(_("Cannot reset a Paid work entry to Draft! Please refund/cancel the associated payslip first."))
            entry.state = 'draft'
            entry.payment_status = 'unpaid'
            entry.payslip_id = False
            entry.payslip_run_id = False
            entry.paid_date = False

    def action_cancel(self):
        for entry in self:
            if entry.payment_status == 'paid':
                raise ValidationError(_("Cannot cancel a Paid work entry! Please refund/cancel the associated payslip first."))
            entry.state = 'cancelled'
            entry.payment_status = 'unpaid'
            entry.payslip_id = False
            entry.payslip_run_id = False
            entry.paid_date = False

    def write(self, vals):
        # If payslip link is removed and payment_status is not explicitly passed, auto-revert to unpaid
        if ('payslip_id' in vals and not vals['payslip_id']) or ('payslip_run_id' in vals and not vals['payslip_run_id']):
            if 'payment_status' not in vals:
                for entry in self:
                    if entry.payment_status == 'in_payroll':
                        vals['payment_status'] = 'unpaid'
                        vals['paid_date'] = False
                        break
        return super().write(vals)

    def init(self):
        super().init()
        # 1. Backfill any existing records without payment_status
        # 2. Fix any orphaned records that are 'in_payroll' but have no payslip_id and no payslip_run_id
        try:
            self.env.cr.execute("""
                UPDATE farm_work_entry
                SET payment_status = 'unpaid',
                    payslip_id = NULL,
                    payslip_run_id = NULL,
                    paid_date = NULL
                WHERE payment_status IS NULL 
                   OR (payment_status = 'in_payroll' AND (payslip_id IS NULL AND payslip_run_id IS NULL));
            """)
        except Exception:
            pass
