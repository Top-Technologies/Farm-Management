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

    # Analytical & Reporting Fields (for Pivot, Graph & Summary Reports)
    work_done_qty = fields.Float(
        string='Work Done (Qty/Score)',
        compute='_compute_report_metrics',
        store=True,
        digits=(16, 2),
        aggregator='sum',
        help='Volume of work output achieved.',
    )
    work_days = fields.Float(
        string='Days Worked',
        compute='_compute_report_metrics',
        store=True,
        digits=(16, 2),
        aggregator='sum',
        help='Normalized days worked (1.0 for full day, 0.5 for half day, 1.5 for 1.5 days).',
    )
    amount_paid = fields.Float(
        string='Amount Paid (Birr)',
        compute='_compute_report_metrics',
        store=True,
        digits=(16, 2),
        aggregator='sum',
        help='Labor payment already settled in paid payslips.',
    )
    amount_in_payroll = fields.Float(
        string='Amount In Payroll (Birr)',
        compute='_compute_report_metrics',
        store=True,
        digits=(16, 2),
        aggregator='sum',
        help='Labor payment currently queued in an open payslip batch.',
    )
    amount_unpaid = fields.Float(
        string='Amount Unpaid (Birr)',
        compute='_compute_report_metrics',
        store=True,
        digits=(16, 2),
        aggregator='sum',
        help='Unpaid labor liability pending payroll processing.',
    )
    entry_count = fields.Integer(
        string='Entries Count',
        default=1,
        aggregator='sum',
        help='Count of work entries for aggregation in reports.',
    )
    employee_gender = fields.Selection(
        related='employee_id.gender',
        string='Worker Gender',
        store=True,
        readonly=True,
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

    @api.constrains('entry_type', 'score_value')
    def _check_work_entry_validity(self):
        for entry in self:
            if entry.score_value <= 0:
                raise ValidationError(_("Work score / days worked must be strictly greater than 0!"))
            if entry.entry_type == 'piece_rate' and not entry.activity_id:
                raise ValidationError(_("Please select an Activity for Piece Rate work entries."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('farm.work.entry') or _('New')
            # Auto-populate location from employee
            if vals.get('employee_id'):
                emp = self.env['hr.employee'].browse(vals['employee_id'])
                curr = emp.current_transfer_id
                target_farm = (curr.farm_id if curr and not curr.moving_date else False) or emp.current_farm_id or emp.initial_farm_id
                target_sub_farm = (curr.sub_farm_id if curr and not curr.moving_date else False) or emp.current_sub_farm_id or emp.initial_sub_farm_id
                target_sub_unit = (curr.sub_unit_id if curr and not curr.moving_date else False) or emp.current_sub_unit_id or emp.initial_sub_unit_id
                target_block = (curr.block_id if curr and not curr.moving_date else False) or emp.current_block_id or emp.initial_block_id

                if target_farm:
                    vals['farm_id'] = target_farm.id
                if target_sub_farm:
                    vals['sub_farm_id'] = target_sub_farm.id
                if target_sub_unit:
                    vals['sub_unit_id'] = target_sub_unit.id
                if target_block and not vals.get('block_id'):
                    vals['block_id'] = target_block.id
        return super().create(vals_list)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            emp = self.employee_id
            curr = emp.current_transfer_id
            target_farm = (curr.farm_id if curr and not curr.moving_date else False) or emp.current_farm_id or emp.initial_farm_id
            target_sub_farm = (curr.sub_farm_id if curr and not curr.moving_date else False) or emp.current_sub_farm_id or emp.initial_sub_farm_id
            target_sub_unit = (curr.sub_unit_id if curr and not curr.moving_date else False) or emp.current_sub_unit_id or emp.initial_sub_unit_id
            target_block = (curr.block_id if curr and not curr.moving_date else False) or emp.current_block_id or emp.initial_block_id

            self.farm_id = target_farm
            self.sub_farm_id = target_sub_farm
            self.sub_unit_id = target_sub_unit
            self.block_id = target_block

            # Auto-suggest payment type: Temporary worker defaults to temporary rate; others default to piece rate
            if emp.farm_employee_type == 'temporary':
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

    @api.depends('score_value', 'total_amount', 'payment_status', 'entry_type', 'work_duration')
    def _compute_report_metrics(self):
        for entry in self:
            entry.work_done_qty = entry.score_value or 0.0
            entry.entry_count = 1

            # Days worked normalization
            if entry.entry_type == 'temporary_rate':
                if entry.work_duration == 'half_day':
                    entry.work_days = 0.5
                elif entry.work_duration == 'one_and_half_day':
                    entry.work_days = 1.5
                else:
                    entry.work_days = 1.0
            else:
                entry.work_days = 1.0 if entry.score_value > 0 else 0.0

            # Financial status breakdown
            tot = entry.total_amount or 0.0
            if entry.payment_status == 'paid':
                entry.amount_paid = tot
                entry.amount_in_payroll = 0.0
                entry.amount_unpaid = 0.0
            elif entry.payment_status == 'in_payroll':
                entry.amount_paid = 0.0
                entry.amount_in_payroll = tot
                entry.amount_unpaid = 0.0
            else:
                entry.amount_paid = 0.0
                entry.amount_in_payroll = 0.0
                entry.amount_unpaid = tot

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
