# -*- coding: utf-8 -*-
from odoo import models


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    _rec_names_search = ['complete_name', 'name']
