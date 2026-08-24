# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrPayslipEmployees(models.TransientModel):
    _inherit = 'hr.payslip.employees'

    worker_type = fields.Selection([
        ('temporary', 'Temporary Workers (Daily Wage)'),
        ('zemach', 'Seasonal / Zemach Workers (Piece Rate)'),
        ('permanent', 'Permanent Employees (Standard Salary)'),
        ('all', 'All Workers'),
    ], string='Worker Classification Filter', default='all')

    farm_id = fields.Many2one('farm.farm', string='Farm')
    sub_unit_id = fields.Many2one('farm.sub.unit', string='Sub Unit')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and self.env.context.get('active_model') == 'hr.payslip.run':
            batch = self.env['hr.payslip.run'].browse(active_id)
            if batch:
                res['worker_type'] = batch.worker_type or 'all'
                res['farm_id'] = batch.farm_id.id if batch.farm_id else False
                res['sub_unit_id'] = batch.sub_unit_id.id if batch.sub_unit_id else False

                if batch.date_start and batch.date_end:
                    we_domain = [
                        ('date', '>=', batch.date_start),
                        ('date', '<=', batch.date_end),
                        ('state', '!=', 'cancelled'),
                        ('payment_status', 'in', ('unpaid', False)),
                    ]
                    if batch.farm_id:
                        we_domain.append(('farm_id', '=', batch.farm_id.id))
                    if batch.sub_unit_id:
                        we_domain.append(('sub_unit_id', '=', batch.sub_unit_id.id))
                    if batch.worker_type != 'all':
                        we_domain.append(('employee_id.farm_employee_type', '=', batch.worker_type))

                    unpaid_entries = self.env['farm.work.entry'].search(we_domain)
                    worker_ids = unpaid_entries.mapped('employee_id').ids
                    if worker_ids:
                        res['employee_ids'] = [(6, 0, worker_ids)]
        return res

    def compute_sheet(self):
        # Auto-ensure contract for temporary and zemach workers before standard compute_sheet
        for emp in self.employee_ids:
            if emp.farm_employee_type in ('temporary', 'zemach'):
                emp._get_or_create_farm_contract()
        return super().compute_sheet()
