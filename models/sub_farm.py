# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SubFarm(models.Model):
    _name = 'farm.sub.farm'
    _description = 'Sub Farm'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(string='Sub Farm Name', required=True, tracking=True)
    code = fields.Char(string='Sub Farm Code', copy=False, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    color = fields.Integer(string='Color Index')

    farm_id = fields.Many2one(
        'farm.farm',
        string='Parent Farm',
        required=True,
        ondelete='cascade',
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='farm_id.company_id',
        store=True,
        readonly=True,
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string='Sub Farm Manager',
        tracking=True,
    )

    area = fields.Float(string='Area (Acres/Ha)', tracking=True)
    description = fields.Html(string='Notes / Description')

    # Relational Hierarchy: Sub Farm -> Sub Units
    sub_unit_ids = fields.One2many(
        'farm.sub.unit',
        'sub_farm_id',
        string='Sub Units',
    )

    # Computed Counts
    sub_unit_count = fields.Integer(
        string='Sub Units Count',
        compute='_compute_counts',
    )
    block_count = fields.Integer(
        string='Blocks Count',
        compute='_compute_counts',
    )

    @api.depends('sub_unit_ids', 'sub_unit_ids.block_ids')
    def _compute_counts(self):
        for sub_farm in self:
            sub_units = sub_farm.sub_unit_ids
            blocks = sub_units.mapped('block_ids')
            sub_farm.sub_unit_count = len(sub_units)
            sub_farm.block_count = len(blocks)

    def action_view_sub_units(self):
        self.ensure_one()
        return {
            'name': _('Sub Units of %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'farm.sub.unit',
            'view_mode': 'list,kanban,form',
            'domain': [('sub_farm_id', '=', self.id)],
            'context': {'default_sub_farm_id': self.id, 'default_farm_id': self.farm_id.id},
        }

    def action_view_blocks(self):
        self.ensure_one()
        return {
            'name': _('Blocks of %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'farm.block',
            'view_mode': 'list,kanban,form',
            'domain': [('sub_farm_id', '=', self.id)],
            'context': {'default_sub_farm_id': self.id, 'default_farm_id': self.farm_id.id},
        }
