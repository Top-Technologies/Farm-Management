# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class FarmTemporaryRate(models.Model):
    _name = 'farm.temporary.rate'
    _description = 'Temporary Worker Wage Rate'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'farm_id asc'

    name = fields.Char(string='Rate Name', compute='_compute_name', store=True)
    farm_id = fields.Many2one(
        'farm.farm',
        string='Farm',
        required=True,
        tracking=True,
        ondelete='cascade',
    )
    full_day_rate = fields.Float(
        string='Full Day Rate (Birr)',
        required=True,
        digits=(16, 2),
        tracking=True,
        help='Fixed daily wage for a temporary worker for a full day of work (score = 1.0).',
    )
    half_day_rate = fields.Float(
        string='Half Day Rate (Birr)',
        required=True,
        digits=(16, 2),
        tracking=True,
        help='Fixed wage for a temporary worker for a half day of work (score = 0.5).',
    )
    uom_name = fields.Char(
        string='Unit of Measure',
        default='Birr/Day',
        help='Rate unit, e.g. Birr/Day',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='farm_id.company_id',
        store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True, tracking=True)
    notes = fields.Text(string='Remarks / Guidelines')

    _sql_constraints = [
        ('farm_rate_uniq', 'unique(farm_id)', 'A temporary worker rate for this farm is already configured! Each farm has one temporary wage rate.'),
    ]

    @api.depends('farm_id.name', 'full_day_rate')
    def _compute_name(self):
        for rec in self:
            farm_str = rec.farm_id.name or _('Farm')
            rec.name = f"{farm_str} - Temporary Rate ({rec.full_day_rate:.2f} Birr/Day)"

    @api.onchange('full_day_rate')
    def _onchange_full_day_rate(self):
        if self.full_day_rate and (not self.half_day_rate or self.half_day_rate == self._origin.half_day_rate):
            self.half_day_rate = round(self.full_day_rate / 2.0, 2)
