# -*- coding: utf-8 -*-
from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    fuel_price_per_liter = fields.Float(
        string='Universal Fuel Price / Liter (Birr)',
        default=165.0,
        digits=(16, 2),
        help='Universal fuel price per liter used across all employee contracts for Grade 18 (50 Litres) and Grade 19+ (60 Litres) transport calculations.',
    )
