# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class Farm(models.Model):
    _name = 'farm.farm'
    _description = 'Farm'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(string='Farm Name', required=True, tracking=True)
    code = fields.Char(string='Farm Code', copy=False, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    color = fields.Integer(string='Color Index')

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string='Farm Manager',
        tracking=True,
    )

    location = fields.Char(string='GPS Coordinates / Location')
    address = fields.Text(string='Address Details')
    description = fields.Html(string='Notes / Description')

    # Relational Hierarchy: Farm -> Sub Farms
    sub_farm_ids = fields.One2many(
        'farm.sub.farm',
        'farm_id',
        string='Sub Farms',
    )

    # Activity Norms for this Farm
    activity_norm_ids = fields.One2many(
        'farm.activity.norm',
        'farm_id',
        string='Activity Norms',
    )

    # Temporary Worker Wage Rates for this Farm
    temporary_rate_ids = fields.One2many(
        'farm.temporary.rate',
        'farm_id',
        string='Temporary Worker Rates',
    )

    # Computed Counts & Statistics
    sub_farm_count = fields.Integer(
        string='Sub Farms Count',
        compute='_compute_counts',
    )
    sub_unit_count = fields.Integer(
        string='Sub Units Count',
        compute='_compute_counts',
    )
    block_count = fields.Integer(
        string='Blocks Count',
        compute='_compute_counts',
    )
    activity_norm_count = fields.Integer(
        string='Activity Norms Count',
        compute='_compute_counts',
    )
    temporary_rate_count = fields.Integer(
        string='Temporary Rates Count',
        compute='_compute_counts',
    )
    total_area = fields.Float(
        string='Total Area',
        compute='_compute_total_area',
        store=True,
        help='Total combined area of all sub farms under this farm.',
    )

    @api.depends('sub_farm_ids', 'sub_farm_ids.sub_unit_ids', 'sub_farm_ids.sub_unit_ids.block_ids', 'activity_norm_ids', 'temporary_rate_ids')
    def _compute_counts(self):
        for farm in self:
            sub_farms = farm.sub_farm_ids
            sub_units = sub_farms.mapped('sub_unit_ids')
            blocks = sub_units.mapped('block_ids')
            farm.sub_farm_count = len(sub_farms)
            farm.sub_unit_count = len(sub_units)
            farm.block_count = len(blocks)
            farm.activity_norm_count = len(farm.activity_norm_ids)
            farm.temporary_rate_count = len(farm.temporary_rate_ids)

    @api.depends('sub_farm_ids.area')
    def _compute_total_area(self):
        for farm in self:
            farm.total_area = sum(farm.sub_farm_ids.mapped('area'))

    def action_view_sub_farms(self):
        self.ensure_one()
        return {
            'name': _('Sub Farms of %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'farm.sub.farm',
            'view_mode': 'list,kanban,form',
            'domain': [('farm_id', '=', self.id)],
            'context': {'default_farm_id': self.id},
        }

    def action_view_sub_units(self):
        self.ensure_one()
        return {
            'name': _('Sub Units of %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'farm.sub.unit',
            'view_mode': 'list,kanban,form',
            'domain': [('farm_id', '=', self.id)],
            'context': {'default_farm_id': self.id},
        }

    def action_view_blocks(self):
        self.ensure_one()
        return {
            'name': _('Blocks of %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'farm.block',
            'view_mode': 'list,kanban,form',
            'domain': [('farm_id', '=', self.id)],
            'context': {'default_farm_id': self.id},
        }
