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
        default=fields.Date.context_today,
        tracking=True,
        index=True,
    )

    # Employee & FMS Identifiers
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
        index=True,
    )
    fms_employee_id = fields.Char(
        string='FMS Employee ID',
        related='employee_id.fms_employee_id',
        store=True,
        readonly=True,
        index=True,
        help='External FMS identifier formatted as [FarmID]_[EmployeeID], e.g. FM02_0001',
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

    # Activity & Rate Calculation
    activity_id = fields.Many2one(
        'farm.activity',
        string='Activity',
        required=True,
        tracking=True,
        index=True,
    )
    activity_code = fields.Char(
        string='Activity Code',
        related='activity_id.code',
        readonly=True,
    )
    uom_name = fields.Char(
        string='Unit of Measure',
        related='activity_id.uom_name',
        readonly=True,
    )
    norm_rate = fields.Float(
        string='Norm Rate',
        compute='_compute_norm_rate',
        store=True,
        readonly=False,
        digits=(16, 2),
        tracking=True,
        help='Standard productivity/payment rate per unit configured for this Activity on this Farm.',
    )
    score_value = fields.Float(
        string='Score',
        required=True,
        default=1.0,
        digits=(16, 2),
        tracking=True,
        help='Score / amount of work performed by the employee.',
    )
    total_amount = fields.Float(
        string='Total Payment (Birr)',
        compute='_compute_total_amount',
        store=True,
        digits=(16, 2),
        tracking=True,
        help='Calculated as Score × Norm Rate.',
    )

    # Status Workflow
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('approved', 'Approved / Paid'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, index=True)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='farm_id.company_id',
        store=True,
        readonly=True,
    )
    notes = fields.Text(string='Notes / Remarks')

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

    @api.depends('activity_id', 'farm_id')
    def _compute_norm_rate(self):
        for entry in self:
            if entry.activity_id and entry.farm_id:
                norm_rec = self.env['farm.activity.norm'].search([
                    ('activity_id', '=', entry.activity_id.id),
                    ('farm_id', '=', entry.farm_id.id),
                ], limit=1)
                if norm_rec:
                    entry.norm_rate = norm_rec.norm_value
                else:
                    entry.norm_rate = 0.0
            else:
                entry.norm_rate = 0.0

    @api.depends('score_value', 'norm_rate')
    def _compute_total_amount(self):
        for entry in self:
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
                raise ValidationError(_("Score value must be greater than zero!"))
            entry.state = 'confirmed'

    def action_approve(self):
        for entry in self:
            entry.state = 'approved'

    def action_draft(self):
        for entry in self:
            entry.state = 'draft'

    def action_cancel(self):
        for entry in self:
            entry.state = 'cancelled'
