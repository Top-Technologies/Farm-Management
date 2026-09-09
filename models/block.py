# -*- coding: utf-8 -*-
from odoo import models, fields, api


class Block(models.Model):
    _name = 'farm.block'
    _description = 'Farm Block'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(string='Block Name', required=True, tracking=True)
    code = fields.Char(
        string='Block ID',
        copy=False,
        readonly=True,
        tracking=True,
        help='System-generated ID based on parent Sub Unit: [SubUnitCode]BK01, [SubUnitCode]BK02...',
    )
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

    def _generate_block_code(self, sub_unit):
        if not sub_unit:
            return False
        sub_unit_code = sub_unit.code
        if not sub_unit_code and sub_unit.sub_farm_id:
            sub_unit.code = sub_unit._generate_sub_unit_code(sub_unit.sub_farm_id)
            sub_unit_code = sub_unit.code
        if not sub_unit_code:
            sub_unit_code = f"SU{sub_unit.id:02d}"

        prefix = f"{sub_unit_code}BK"
        existing_domain = [('sub_unit_id', '=', sub_unit.id), ('code', '=like', f"{prefix}%")]
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

    @api.onchange('sub_unit_id')
    def _onchange_sub_unit_id(self):
        if self.sub_unit_id:
            self.code = self._generate_block_code(self.sub_unit_id)
        else:
            self.code = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            sub_unit_id = vals.get('sub_unit_id')
            sub_unit = self.env['farm.sub.unit'].browse(sub_unit_id) if sub_unit_id else False
            if sub_unit and (not vals.get('code') or vals.get('code') == '/'):
                vals['code'] = self._generate_block_code(sub_unit)
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if 'sub_unit_id' in vals:
            for rec in self:
                if rec.sub_unit_id:
                    rec.code = rec._generate_block_code(rec.sub_unit_id)
        return res

    def init(self):
        super().init()
        # Automatically migrate existing blocks to match hierarchical [SubUnitCode]BK0X format
        sub_units = self.env['farm.sub.unit'].search([], order='id asc')
        for su in sub_units:
            su_code = su.code or f"SU{su.id:02d}"
            prefix = f"{su_code}BK"
            blocks = self.search([('sub_unit_id', '=', su.id)], order='id asc')
            seq = 1
            for bk in blocks:
                expected_code = f"{prefix}{seq:02d}"
                if bk.code != expected_code:
                    bk.code = expected_code
                seq += 1
