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

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for unit in records:
            if unit.assigned_employee_ids:
                unit._sync_assigned_employees()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'assigned_employee_ids' in vals or 'sub_farm_id' in vals:
            for unit in self:
                unit._sync_assigned_employees()
        return res

    def _sync_assigned_employees(self):
        """Synchronizes assigned employees with the Sub Unit location and generates their FMS IDs."""
        for unit in self:
            for emp in unit.assigned_employee_ids:
                updates = {}
                need_id_gen = False

                if emp.initial_sub_unit_id != unit:
                    updates['initial_sub_unit_id'] = unit.id
                    updates['initial_sub_farm_id'] = unit.sub_farm_id.id if unit.sub_farm_id else False
                    updates['initial_farm_id'] = unit.farm_id.id if unit.farm_id else False
                    need_id_gen = True

                if need_id_gen or not emp.fms_employee_id or '_' in str(emp.fms_employee_id):
                    new_id = emp._generate_farm_employee_id(unit.farm_id, emp.farm_employee_type)
                    updates['fms_employee_id'] = new_id
                    updates['employee_code'] = new_id

                if updates:
                    emp.with_context(skip_sub_unit_sync=True).write(updates)

                # Ensure active transfer record exists for this employee at this sub unit
                active_transfers = emp.transfer_history_ids.filtered(lambda t: not t.moving_date)
                if not active_transfers:
                    self.env['farm.employee.transfer'].create({
                        'employee_id': emp.id,
                        'farm_id': unit.farm_id.id if unit.farm_id else False,
                        'sub_farm_id': unit.sub_farm_id.id if unit.sub_farm_id else False,
                        'sub_unit_id': unit.id,
                        'transfer_date': fields.Date.today(),
                        'notes': _('Assigned as field worker in Sub Unit: %s', unit.name),
                    })
                elif active_transfers[0].sub_unit_id != unit:
                    active_transfers[0].write({'moving_date': fields.Date.today()})
                    self.env['farm.employee.transfer'].create({
                        'employee_id': emp.id,
                        'farm_id': unit.farm_id.id if unit.farm_id else False,
                        'sub_farm_id': unit.sub_farm_id.id if unit.sub_farm_id else False,
                        'sub_unit_id': unit.id,
                        'transfer_date': fields.Date.today(),
                        'notes': _('Reassigned to Sub Unit: %s', unit.name),
                    })


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
