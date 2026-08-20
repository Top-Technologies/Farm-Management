# -*- coding: utf-8 -*-
from odoo import models, fields, api


class Block(models.Model):
    _name = 'farm.block'
    _description = 'Farm Block'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(string='Block Name', required=True, tracking=True)
    code = fields.Char(string='Block Code', copy=False, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    color = fields.Integer(string='Color Index')

    sub_unit_id = fields.Many2one(
        'farm.sub.unit',
        string='Parent Sub Unit',
        required=True,
        ondelete='cascade',
        tracking=True,
    )
    sub_farm_id = fields.Many2one(
        'farm.sub.farm',
        string='Sub Farm',
        related='sub_unit_id.sub_farm_id',
        store=True,
        readonly=True,
    )
    farm_id = fields.Many2one(
        'farm.farm',
        string='Farm',
        related='sub_unit_id.farm_id',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='sub_unit_id.company_id',
        store=True,
        readonly=True,
    )

    supervisor_id = fields.Many2one(
        'hr.employee',
        string='Block Supervisor',
        tracking=True,
    )

    area = fields.Float(string='Area (Acres/Ha)', tracking=True)
    crop_type = fields.Char(string='Crop / Culture', tracking=True)
    soil_type = fields.Char(string='Soil Type')
    status = fields.Selection([
        ('preparation', 'Land Preparation'),
        ('active', 'Cultivated / Active'),
        ('harvested', 'Harvested'),
        ('fallow', 'Fallow / Resting'),
    ], string='Status', default='active', tracking=True)

    description = fields.Html(string='Notes / Description')
