# -*- coding: utf-8 -*-
from odoo import models, api


class HrJob(models.Model):
    _inherit = 'hr.job'

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        if name and isinstance(name, str):
            name = name.strip()
        return super().name_search(name=name, args=args, operator=operator, limit=limit)
