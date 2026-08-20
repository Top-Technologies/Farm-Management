# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SubUnit(models.Model):
    _name = 'farm.sub.unit'
    _description = 'Sub Unit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(string='Sub Unit Name', required=True, tracking=True)
    code = fields.Char(string='Sub Unit Code', copy=False, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    color = fields.Integer(string='Color Index')

    sub_farm_id = fields.Many2one(
        'farm.sub.farm',
        string='Parent Sub Farm',
        required=True,
        ondelete='cascade',
        tracking=True,
    )
    farm_id = fields.Many2one(
        'farm.farm',
        string='Farm',
        related='sub_farm_id.farm_id',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='sub_farm_id.company_id',
        store=True,
        readonly=True,
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string='Sub Unit Supervisor / Manager',
        tracking=True,
    )

    area = fields.Float(string='Area (Acres/Ha)', tracking=True)
    description = fields.Html(string='Notes / Description')

    # Relational Hierarchy: Sub Unit -> Blocks
    block_ids = fields.One2many(
        'farm.block',
        'sub_unit_id',
        string='Blocks',
    )

    # Field Workers Assigned at Sub Unit Level
    assigned_employee_ids = fields.Many2many(
        'hr.employee',
        'farm_sub_unit_employee_rel',
        'sub_unit_id',
        'employee_id',
        string='Assigned Field Workers',
    )
    worker_count = fields.Integer(
        string='Workers Count',
        compute='_compute_worker_count',
        store=True,
    )

    # Transfer History at Sub Unit Level
    transfer_ids = fields.One2many(
        'farm.employee.transfer',
        'sub_unit_id',
        string='Transfer Records',
    )

    # Computed Counts
    block_count = fields.Integer(
        string='Blocks Count',
        compute='_compute_counts',
    )

    @api.depends('block_ids')
    def _compute_counts(self):
        for unit in self:
            unit.block_count = len(unit.block_ids)

    @api.depends('assigned_employee_ids')
    def _compute_worker_count(self):
        for unit in self:
            unit.worker_count = len(unit.assigned_employee_ids)

    def action_view_blocks(self):
        self.ensure_one()
        return {
            'name': _('Blocks of %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'farm.block',
            'view_mode': 'list,kanban,form',
            'domain': [('sub_unit_id', '=', self.id)],
            'context': {
                'default_sub_unit_id': self.id,
                'default_sub_farm_id': self.sub_farm_id.id,
                'default_farm_id': self.farm_id.id,
            },
        }

    def action_view_workers(self):
        self.ensure_one()
        return {
            'name': _('Workers of Sub Unit %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'view_mode': 'list,kanban,form',
            'domain': [('id', 'in', self.assigned_employee_ids.ids)],
            'context': {'default_current_sub_unit_id': self.id},
        }
