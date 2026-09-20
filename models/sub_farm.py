# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class SubFarm(models.Model):
    _name = 'farm.sub.farm'
    _description = 'Sub Farm'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(string='Sub Farm Name', required=True, tracking=True)
    code = fields.Char(
        string='Sub Farm ID',
        copy=False,
        readonly=True,
        tracking=True,
        help='System-generated ID based on parent Farm: [FarmCode]SF01, [FarmCode]SF02...',
    )
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

    def _generate_sub_farm_code(self, farm):
        if not farm:
            return False
        farm_code = (farm.code or f"FM{farm.id:02d}").strip()
        prefix = f"{farm_code}SF"
        existing_domain = [('farm_id', '=', farm.id), ('code', '=like', f"{prefix}%")]
        if self.id:
            existing_domain.append(('id', '!=', self.id))
        records = self.sudo().search(existing_domain)
        max_num = 0
        for rec in records:
            code_val = rec.code or ''
            num_part = code_val[len(prefix):]
            if num_part.isdigit():
                num = int(num_part)
                if num > max_num:
                    max_num = num
        return f"{prefix}{max_num + 1:02d}"

    @api.onchange('farm_id')
    def _onchange_farm_id(self):
        if self.farm_id:
            self.code = self._generate_sub_farm_code(self.farm_id)
        else:
            self.code = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            farm_id = vals.get('farm_id')
            farm = self.env['farm.farm'].browse(farm_id) if farm_id else False
            if farm and (not vals.get('code') or vals.get('code') == '/'):
                vals['code'] = self._generate_sub_farm_code(farm)
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if 'farm_id' in vals:
            for rec in self:
                if rec.farm_id:
                    new_code = rec._generate_sub_farm_code(rec.farm_id)
                    rec.code = new_code
                    for su in rec.sub_unit_ids:
                        su.code = su._generate_sub_unit_code(rec)
                        for bk in su.block_ids:
                            bk.code = bk._generate_block_code(su)
        return res
