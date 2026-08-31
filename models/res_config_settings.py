# -*- coding: utf-8 -*-
from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fuel_price_per_liter = fields.Float(
        related='company_id.fuel_price_per_liter',
        string='Universal Fuel Price / Liter (Birr)',
        readonly=False,
        help='Universal fuel price per liter used to compute fuel allowances for Grade 18 and Grade 19+ employees.',
    )
