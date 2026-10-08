# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.osv import expression


class HrPayslipEmployees(models.TransientModel):
    _inherit = 'hr.payslip.employees'

    generation_mode = fields.Selection([
        ('all', 'All Employees (ለሁሉም ሰራተኞች)'),
        ('department', 'By Department (በክፍል / በዲፓርትመንት)'),
        ('worker_type', 'By Worker Classification / Farm (በሰራተኛ ዓይነት / እርሻ)'),
        ('custom', 'Custom / Advanced Filter (የተመረጡ ሰራተኞች)'),
    ], string='Selection Mode', default='all', required=True,
       help='Choose whether to generate payslips for all employees, by department, by worker classification, or custom.')

    selected_employee_count = fields.Integer(
        string='Selected Employees Count',
        compute='_compute_selected_employee_count',
    )

    worker_type = fields.Selection([
        ('temporary', 'Temporary Workers (Daily Wage)'),
        ('zemach', 'Seasonal / Zemach Workers (Piece Rate)'),
        ('permanent', 'Farm Staff (Standard Salary)'),
        ('head_office', 'Head Office Staff (Standard Salary)'),
        ('cpw', 'CPW Staff (Standard Salary)'),
        ('all', 'All Workers'),
    ], string='Worker Classification Filter', default='all')

    farm_id = fields.Many2one('farm.farm', string='Farm')
    sub_farm_id = fields.Many2one('farm.sub.farm', string='Sub Farm')
    sub_unit_id = fields.Many2one('farm.sub.unit', string='Sub Unit')

    @api.depends('employee_ids')
    def _compute_selected_employee_count(self):
        for wizard in self:
            wizard.selected_employee_count = len(wizard.employee_ids)

    def _get_mode_domain(self, mode='all', department_id=False, worker_type=False,
                         farm_id=False, sub_farm_id=False, sub_unit_id=False):
        """Constructs domain for active employees based on selected mode."""
        company_domain = ['|', ('company_id', '=', False), ('company_id', '=', self.env.company.id)]
        domain = [('active', '=', True)] + company_domain

        if mode == 'all':
            return domain

        elif mode == 'department':
            if department_id:
                dept_id = department_id if isinstance(department_id, int) else department_id.id
                domain = expression.AND([domain, [('department_id', 'child_of', dept_id)]])
            return domain

        elif mode == 'worker_type':
            if worker_type and worker_type != 'all':
                domain = expression.AND([domain, [('farm_employee_type', '=', worker_type)]])
            f_id = farm_id if isinstance(farm_id, int) else (farm_id.id if farm_id else False)
            if f_id:
                domain = expression.AND([domain, ['|', ('current_farm_id', '=', f_id), ('initial_farm_id', '=', f_id)]])
            sf_id = sub_farm_id if isinstance(sub_farm_id, int) else (sub_farm_id.id if sub_farm_id else False)
            if sf_id:
                domain = expression.AND([domain, ['|', ('current_sub_farm_id', '=', sf_id), ('initial_sub_farm_id', '=', sf_id)]])
            su_id = sub_unit_id if isinstance(sub_unit_id, int) else (sub_unit_id.id if sub_unit_id else False)
            if su_id:
                domain = expression.AND([domain, ['|', ('current_sub_unit_id', '=', su_id), ('initial_sub_unit_id', '=', su_id)]])
            return domain

        else:  # custom
            return self._get_available_contracts_domain()

    def get_employees_domain(self):
        mode = self.generation_mode or 'all'
        if mode in ('all', 'department', 'worker_type'):
            return self._get_mode_domain(
                mode=mode,
                department_id=self.department_id,
                worker_type=self.worker_type,
                farm_id=self.farm_id,
                sub_farm_id=self.sub_farm_id,
                sub_unit_id=self.sub_unit_id,
            )
        return super().get_employees_domain()

    @api.depends('generation_mode', 'structure_id', 'department_id', 'structure_type_id',
                 'job_id', 'worker_type', 'farm_id', 'sub_farm_id', 'sub_unit_id')
    def _compute_employee_ids(self):
        for wizard in self:
            domain = wizard.get_employees_domain()
            employees = self.env['hr.employee'].search(domain)
            if wizard.structure_id:
                employees = wizard._filter_employees_by_structure(employees, wizard.structure_id)

            # Exclude employees that already have a payslip in this batch
            active_id = self.env.context.get('active_id')
            if active_id and self.env.context.get('active_model') == 'hr.payslip.run':
                batch = self.env['hr.payslip.run'].browse(active_id)
                if batch.slip_ids:
                    employees -= batch.slip_ids.mapped('employee_id')

            wizard.employee_ids = [(6, 0, employees.ids)]

    @api.onchange('generation_mode')
    def _onchange_generation_mode(self):
        return self._recompute_wizard_employees()

    @api.onchange('department_id')
    def _onchange_department_id(self):
        return self._recompute_wizard_employees()

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
        mode = self.generation_mode or 'all'
        domain = self._get_mode_domain(
            mode=mode,
            department_id=self.department_id,
            worker_type=self.worker_type,
            farm_id=self.farm_id,
            sub_farm_id=self.sub_farm_id,
            sub_unit_id=self.sub_unit_id,
        )

        employees = self.env['hr.employee'].search(domain)
        if self.structure_id:
            employees = self._filter_employees_by_structure(employees, self.structure_id)

        # Exclude employees that already have a payslip in this batch
        active_id = self.env.context.get('active_id')
        if active_id and self.env.context.get('active_model') == 'hr.payslip.run':
            batch = self.env['hr.payslip.run'].browse(active_id)
            if batch.slip_ids:
                employees -= batch.slip_ids.mapped('employee_id')

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
            elif emp.farm_employee_type in ('permanent', 'head_office', 'cpw'):
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
                # Intelligent default mode
                if getattr(batch, 'department_id', False):
                    res['generation_mode'] = 'department'
                    res['department_id'] = batch.department_id.id
                elif batch.worker_type and batch.worker_type != 'all':
                    res['generation_mode'] = 'worker_type'
                    res['worker_type'] = batch.worker_type
                else:
                    res['generation_mode'] = 'all'

                res['farm_id'] = batch.farm_id.id if batch.farm_id else False
                res['sub_farm_id'] = batch.sub_farm_id.id if batch.sub_farm_id else False
                res['sub_unit_id'] = batch.sub_unit_id.id if batch.sub_unit_id else False
                if batch.structure_id:
                    res['structure_id'] = batch.structure_id.id

                # Find eligible employees for default_get
                domain = self._get_mode_domain(
                    mode=res.get('generation_mode', 'all'),
                    department_id=res.get('department_id'),
                    worker_type=res.get('worker_type', 'all'),
                    farm_id=res.get('farm_id'),
                    sub_farm_id=res.get('sub_farm_id'),
                    sub_unit_id=res.get('sub_unit_id'),
                )

                employees = self.env['hr.employee'].search(domain)
                if batch.structure_id:
                    employees = self._filter_employees_by_structure(employees, batch.structure_id)

                if (batch.date_start and batch.date_end and
                        res.get('generation_mode') == 'worker_type' and
                        batch.worker_type in ('temporary', 'zemach')):
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

                # Exclude employees that already have a payslip in this batch
                if batch.slip_ids:
                    employees -= batch.slip_ids.mapped('employee_id')

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
