# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrPayslipEmployees(models.TransientModel):
    _inherit = 'hr.payslip.employees'

    worker_type = fields.Selection([
        ('temporary', 'Temporary Workers (Daily Wage)'),
        ('zemach', 'Seasonal / Zemach Workers (Piece Rate)'),
        ('permanent', 'Farm Staff (Standard Salary)'),
        ('head_office', 'Head Office Staff (Standard Salary)'),
        ('all', 'All Workers'),
    ], string='Worker Classification Filter', default='all')

    farm_id = fields.Many2one('farm.farm', string='Farm')
    sub_farm_id = fields.Many2one('farm.sub.farm', string='Sub Farm')
    sub_unit_id = fields.Many2one('farm.sub.unit', string='Sub Unit')

    @api.onchange('farm_id')
    def _onchange_farm_id(self):
        if self.farm_id:
            if self.sub_farm_id and self.sub_farm_id.farm_id != self.farm_id:
                self.sub_farm_id = False
            if self.sub_unit_id and self.sub_unit_id.farm_id != self.farm_id:
                self.sub_unit_id = False
        return self._recompute_wizard_employees()

    @api.onchange('sub_farm_id')
    def _onchange_sub_farm_id(self):
        if self.sub_farm_id:
            self.farm_id = self.sub_farm_id.farm_id
            if self.sub_unit_id and self.sub_unit_id.sub_farm_id != self.sub_farm_id:
                self.sub_unit_id = False
        return self._recompute_wizard_employees()

    @api.onchange('sub_unit_id')
    def _onchange_sub_unit_id(self):
        if self.sub_unit_id:
            self.sub_farm_id = self.sub_unit_id.sub_farm_id
            self.farm_id = self.sub_unit_id.farm_id
        return self._recompute_wizard_employees()

    @api.onchange('worker_type', 'structure_id')
    def _onchange_worker_type_or_structure(self):
        return self._recompute_wizard_employees()

    def _recompute_wizard_employees(self):
        active_id = self.env.context.get('active_id')
        batch = False
        if active_id and self.env.context.get('active_model') == 'hr.payslip.run':
            batch = self.env['hr.payslip.run'].browse(active_id)

        date_start = batch.date_start if batch else fields.Date.today()
        date_end = batch.date_end if batch else fields.Date.today()

        domain = [('active', '=', True)]
        if self.farm_id:
            domain.extend(['|', ('current_farm_id', '=', self.farm_id.id), ('initial_farm_id', '=', self.farm_id.id)])
        if self.sub_farm_id:
            domain.extend(['|', ('current_sub_farm_id', '=', self.sub_farm_id.id), ('initial_sub_farm_id', '=', self.sub_farm_id.id)])
        if self.sub_unit_id:
            domain.extend(['|', ('current_sub_unit_id', '=', self.sub_unit_id.id), ('initial_sub_unit_id', '=', self.sub_unit_id.id)])
        if self.worker_type and self.worker_type != 'all':
            domain.append(('farm_employee_type', '=', self.worker_type))

        employees = self.env['hr.employee'].search(domain)
        if self.structure_id:
            employees = self._filter_employees_by_structure(employees, self.structure_id)

        self.employee_ids = [(6, 0, employees.ids)]

    def _filter_employees_by_structure(self, employees, target_struct):
        def _emp_matches(emp):
            contract = emp.contract_id
            if contract and contract.structure_type_id:
                st = contract.structure_type_id
                if st.default_struct_id == target_struct or target_struct in st.struct_ids:
                    return True
            emp_struct = False
            if emp.farm_employee_type == 'temporary':
                emp_struct = (
                    self.env.ref('farm_management.structure_farm_temporary', raise_if_not_found=False) or
                    self.env.ref('Farm-Management.structure_farm_temporary', raise_if_not_found=False) or
                    self.env.ref('Farm_Management.structure_farm_temporary', raise_if_not_found=False)
                )
            elif emp.farm_employee_type == 'zemach':
                emp_struct = (
                    self.env.ref('farm_management.structure_farm_zemach', raise_if_not_found=False) or
                    self.env.ref('Farm-Management.structure_farm_zemach', raise_if_not_found=False) or
                    self.env.ref('Farm_Management.structure_farm_zemach', raise_if_not_found=False)
                )
            elif emp.farm_employee_type in ('permanent', 'head_office'):
                emp_struct = (
                    self.env.ref('farm_management.structure_farm_permanent', raise_if_not_found=False) or
                    self.env.ref('Farm-Management.structure_farm_permanent', raise_if_not_found=False) or
                    self.env.ref('Farm_Management.structure_farm_permanent', raise_if_not_found=False)
                )
            return emp_struct == target_struct
        return employees.filtered(_emp_matches)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and self.env.context.get('active_model') == 'hr.payslip.run':
            batch = self.env['hr.payslip.run'].browse(active_id)
            if batch:
                res['worker_type'] = batch.worker_type or 'all'
                res['farm_id'] = batch.farm_id.id if batch.farm_id else False
                res['sub_farm_id'] = batch.sub_farm_id.id if batch.sub_farm_id else False
                res['sub_unit_id'] = batch.sub_unit_id.id if batch.sub_unit_id else False
                if batch.structure_id:
                    res['structure_id'] = batch.structure_id.id

                # Find eligible employees
                emp_domain = [('active', '=', True)]
                if batch.farm_id:
                    emp_domain.extend(['|', ('current_farm_id', '=', batch.farm_id.id), ('initial_farm_id', '=', batch.farm_id.id)])
                if batch.sub_farm_id:
                    emp_domain.extend(['|', ('current_sub_farm_id', '=', batch.sub_farm_id.id), ('initial_sub_farm_id', '=', batch.sub_farm_id.id)])
                if batch.sub_unit_id:
                    emp_domain.extend(['|', ('current_sub_unit_id', '=', batch.sub_unit_id.id), ('initial_sub_unit_id', '=', batch.sub_unit_id.id)])
                if batch.worker_type != 'all':
                    emp_domain.append(('farm_employee_type', '=', batch.worker_type))

                employees = self.env['hr.employee'].search(emp_domain)
                if batch.structure_id:
                    employees = self._filter_employees_by_structure(employees, batch.structure_id)

                if batch.date_start and batch.date_end and batch.worker_type in ('temporary', 'zemach'):
                    we_domain = [
                        ('date', '>=', batch.date_start),
                        ('date', '<=', batch.date_end),
                        ('state', '!=', 'cancelled'),
                        ('payment_status', 'in', ('unpaid', False)),
                    ]
                    if batch.farm_id:
                        we_domain.append(('farm_id', '=', batch.farm_id.id))
                    if batch.sub_farm_id:
                        we_domain.append(('sub_farm_id', '=', batch.sub_farm_id.id))
                    if batch.sub_unit_id:
                        we_domain.append(('sub_unit_id', '=', batch.sub_unit_id.id))
                    if batch.worker_type != 'all':
                        we_domain.append(('employee_id.farm_employee_type', '=', batch.worker_type))

                    unpaid_entries = self.env['farm.work.entry'].search(we_domain)
                    we_employee_ids = unpaid_entries.mapped('employee_id').ids
                    employees = employees.filtered(lambda e: e.id in we_employee_ids)

                if employees:
                    res['employee_ids'] = [(6, 0, employees.ids)]
        return res

    def compute_sheet(self):
        # Auto-ensure contract for all workers before standard compute_sheet
        for emp in self.employee_ids:
            emp._get_or_create_farm_contract()
        res = super().compute_sheet()
        # If wizard had a specific structure_id, update slips in this run that were just created
        active_id = self.env.context.get('active_id')
        if self.structure_id and active_id and self.env.context.get('active_model') == 'hr.payslip.run':
            batch = self.env['hr.payslip.run'].browse(active_id)
            for slip in batch.slip_ids.filtered(lambda s: s.employee_id in self.employee_ids):
                if slip.struct_id != self.structure_id:
                    slip.struct_id = self.structure_id
                    slip.compute_sheet()
        return res
