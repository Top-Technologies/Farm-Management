# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class FarmActivity(models.Model):
    _name = 'farm.activity'
    _description = 'Farm Activity'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(
        string='Activity Name',
        required=True,
        tracking=True,
        help='Name of the agricultural activity, e.g. Soil Preparation, Cultivating, Harvesting, Irrigation...',
    )
    code = fields.Char(
        string='Activity ID / Code',
        required=True,
        copy=False,
        tracking=True,
        help='Short unique identifier for the activity, e.g. SP, CULT, HARV...',
    )
    active = fields.Boolean(default=True, tracking=True)
    color = fields.Integer(string='Color Index')

    category = fields.Selection([
        ('land_prep', 'Land Preparation'),
        ('planting', 'Planting & Sowing'),
        ('crop_care', 'Crop Care & Fertilization'),
        ('irrigation', 'Irrigation'),
        ('harvest', 'Harvesting'),
        ('maintenance', 'Maintenance & Other'),
    ], string='Category', default='land_prep', tracking=True)

    uom_name = fields.Char(
        string='Unit of Measure',
        default='Birr/Kg',
        help='Default measurement unit for norms, e.g. Birr/Kg, Hours/Acre...',
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    description = fields.Html(string='Activity Description & Standard Operating Procedures')

    # Relational link to Farm Norms Table
    farm_norm_ids = fields.One2many(
        'farm.activity.norm',
        'activity_id',
        string='Farm Norms',
        copy=True,
    )
    farm_norm_count = fields.Integer(
        string='Configured Farms Count',
        compute='_compute_farm_norm_count',
    )

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'The Activity ID / Code must be unique per company!'),
    ]

    @api.depends('farm_norm_ids')
    def _compute_farm_norm_count(self):
        for act in self:
            act.farm_norm_count = len(act.farm_norm_ids)


class FarmActivityNorm(models.Model):
    _name = 'farm.activity.norm'
    _description = 'Farm Activity Norm'
    _order = 'farm_id asc'

    activity_id = fields.Many2one(
        'farm.activity',
        string='Activity',
        required=True,
        ondelete='cascade',
    )
    farm_id = fields.Many2one(
        'farm.farm',
        string='Farm',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='farm_id.company_id',
        store=True,
        readonly=True,
    )
    norm_value = fields.Float(
        string='Standard Norm',
        required=True,
        digits=(16, 2),
        help='The standard target / productivity norm value for this activity at this specific farm (e.g. 6.0, 7.5).',
    )
    uom_name = fields.Char(
        string='Unit',
        related='activity_id.uom_name',
        readonly=True,
    )

    _sql_constraints = [
        ('activity_farm_uniq', 'unique(activity_id, farm_id)', 'A norm for this activity on this farm is already configured!'),
    ]
