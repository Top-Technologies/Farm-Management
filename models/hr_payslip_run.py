# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    worker_type = fields.Selection([
        ('temporary', 'Temporary Workers (Daily Wage)'),
        ('zemach', 'Seasonal / Zemach Workers (Piece Rate)'),
        ('permanent', 'Farm Staff (Standard Salary)'),
        ('head_office', 'Head Office Staff (Standard Salary)'),
        ('all', 'All Workers'),
    ], string='Worker Classification', default='temporary', required=True,
       help='Select which category of workers this payroll batch is targeting.')

    structure_id = fields.Many2one(
        'hr.payroll.structure',
        string='Salary Structure',
        help='Optional: Divide and generate payslips targeting a specific salary structure.',
    )
    farm_id = fields.Many2one(
        'farm.farm',
        string='Farm Filter',
        help='Optional: Filter payroll batch to employees stationed at a specific farm.',
    )
    sub_farm_id = fields.Many2one(
        'farm.sub.farm',
        string='Sub Farm Filter',
        domain="[('farm_id', '=', farm_id)] if farm_id else []",
        help='Optional: Restrict batch to a specific sub farm.',
    )
    sub_unit_id = fields.Many2one(
        'farm.sub.unit',
        string='Sub Unit Filter',
        domain="[('sub_farm_id', '=', sub_farm_id)] if sub_farm_id else ([('farm_id', '=', farm_id)] if farm_id else [])",
        help='Optional: Further restrict batch to a specific sub unit.',
    )

    # Computed Farm Analytics
    farm_work_entry_count = fields.Integer(
        string='Total Work Entries',
        compute='_compute_farm_batch_stats',
        store=True,
    )
    farm_total_amount = fields.Float(
        string='Total Farm Amount (Birr)',
        compute='_compute_farm_batch_stats',
        store=True,
        digits=(16, 2),
        help='Sum total of all farm work entries across payslips in this batch.',
    )
    farm_worker_count = fields.Integer(
        string='Total Workers',
        compute='_compute_farm_batch_stats',
        store=True,
    )

    farm_work_entry_ids = fields.One2many(
        'farm.work.entry',
        'payslip_run_id',
        string='All Included Work Entries',
    )

    @api.onchange('farm_id')
    def _onchange_farm_id(self):
        if self.farm_id:
            if self.sub_farm_id and self.sub_farm_id.farm_id != self.farm_id:
                self.sub_farm_id = False
            if self.sub_unit_id and self.sub_unit_id.farm_id != self.farm_id:
                self.sub_unit_id = False
        self._update_batch_name()

    @api.onchange('sub_farm_id')
    def _onchange_sub_farm_id(self):
        if self.sub_farm_id:
            self.farm_id = self.sub_farm_id.farm_id
            if self.sub_unit_id and self.sub_unit_id.sub_farm_id != self.sub_farm_id:
                self.sub_unit_id = False
        self._update_batch_name()

    @api.onchange('sub_unit_id')
    def _onchange_sub_unit_id(self):
        if self.sub_unit_id:
            self.sub_farm_id = self.sub_unit_id.sub_farm_id
            self.farm_id = self.sub_unit_id.farm_id
        self._update_batch_name()

    @api.onchange('date_start', 'structure_id')
    def _onchange_batch_dates_or_structure(self):
        self._update_batch_name()

    def _update_batch_name(self):
        """Auto-generates payslip batch name based on sub unit / sub farm / farm and month."""
        month_str = ''
        if self.date_start:
            month_str = self.date_start.strftime('%B %Y')

        loc_label = ''
        if self.sub_unit_id:
            loc_label = f"{self.sub_unit_id.code} - {self.sub_unit_id.name}" if self.sub_unit_id.code else self.sub_unit_id.name
        elif self.sub_farm_id:
            loc_label = f"{self.sub_farm_id.code} - {self.sub_farm_id.name}" if self.sub_farm_id.code else self.sub_farm_id.name
        elif self.farm_id:
            loc_label = f"{self.farm_id.code} - {self.farm_id.name}" if self.farm_id.code else self.farm_id.name

        parts = []
        if loc_label:
            parts.append(loc_label)
        if month_str:
            parts.append(month_str)

        if parts:
            self.name = " - ".join(parts)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            name = vals.get('name')
            if not name or name.startswith('From ') or name in ('New', '/'):
                sub_unit_id = vals.get('sub_unit_id')
                sub_farm_id = vals.get('sub_farm_id')
                farm_id = vals.get('farm_id')
                date_start = vals.get('date_start')

                month_str = ''
                if date_start:
                    if isinstance(date_start, str):
                        date_start = fields.Date.from_string(date_start)
                    month_str = date_start.strftime('%B %Y')

                loc_label = ''
                if sub_unit_id:
                    su = self.env['farm.sub.unit'].browse(sub_unit_id)
                    loc_label = f"{su.code} - {su.name}" if su.code else su.name
                elif sub_farm_id:
                    sf = self.env['farm.sub.farm'].browse(sub_farm_id)
                    loc_label = f"{sf.code} - {sf.name}" if sf.code else sf.name
                elif farm_id:
                    f = self.env['farm.farm'].browse(farm_id)
                    loc_label = f"{f.code} - {f.name}" if f.code else f.name

                parts = []
                if loc_label:
                    parts.append(loc_label)
                if month_str:
                    parts.append(month_str)
                if parts:
                    vals['name'] = " - ".join(parts)

        return super().create(vals_list)

    @api.depends('slip_ids', 'slip_ids.farm_work_entry_ids', 'slip_ids.farm_work_total_amount')
    def _compute_farm_batch_stats(self):
        for batch in self:
            entries = batch.slip_ids.mapped('farm_work_entry_ids')
            batch.farm_work_entry_count = len(entries)
            batch.farm_total_amount = sum(batch.slip_ids.mapped('farm_work_total_amount'))
            batch.farm_worker_count = len(batch.slip_ids.mapped('employee_id'))

    def action_generate_farm_payslips(self):
        """Automatically generates and computes payslips for all workers matching batch criteria

        with active unpaid work entries in the period [date_start, date_end].
        """
        self.ensure_one()
        if not self.date_start or not self.date_end:
            raise UserError(_("Please define the Batch Start Date and End Date first!"))

        # 1. Search eligible unpaid work entries directly
        we_domain = [
            ('date', '>=', self.date_start),
            ('date', '<=', self.date_end),
            ('state', '!=', 'cancelled'),
            ('payment_status', 'in', ('unpaid', False)),
        ]
        if self.farm_id:
            we_domain.append(('farm_id', '=', self.farm_id.id))
        if self.sub_farm_id:
            we_domain.append(('sub_farm_id', '=', self.sub_farm_id.id))
        if self.sub_unit_id:
            we_domain.append(('sub_unit_id', '=', self.sub_unit_id.id))

        if self.worker_type != 'all':
            we_domain.append(('employee_id.farm_employee_type', '=', self.worker_type))

        unpaid_entries = self.env['farm.work.entry'].search(we_domain)

        # 2. Resolve eligible employees
        if self.worker_type in ('permanent', 'head_office'):
            emp_domain = [
                ('farm_employee_type', '=', self.worker_type),
                '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id)
            ]
            if self.farm_id and self.worker_type == 'permanent':
                emp_domain.extend(['|', ('current_farm_id', '=', self.farm_id.id), ('initial_farm_id', '=', self.farm_id.id)])
            if self.sub_farm_id and self.worker_type == 'permanent':
                emp_domain.extend(['|', ('current_sub_farm_id', '=', self.sub_farm_id.id), ('initial_sub_farm_id', '=', self.sub_farm_id.id)])
            if self.sub_unit_id and self.worker_type == 'permanent':
                emp_domain.extend(['|', ('current_sub_unit_id', '=', self.sub_unit_id.id), ('initial_sub_unit_id', '=', self.sub_unit_id.id)])
            eligible_employees = self.env['hr.employee'].search(emp_domain)
        elif self.worker_type == 'all':
            we_employees = unpaid_entries.mapped('employee_id')
            perm_domain = [
                ('farm_employee_type', 'in', ('permanent', 'head_office')),
                '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id)
            ]
            if self.farm_id:
                perm_domain.extend(['|', ('current_farm_id', '=', self.farm_id.id), ('initial_farm_id', '=', self.farm_id.id)])
            if self.sub_farm_id:
                perm_domain.extend(['|', ('current_sub_farm_id', '=', self.sub_farm_id.id), ('initial_sub_farm_id', '=', self.sub_farm_id.id)])
            if self.sub_unit_id:
                perm_domain.extend(['|', ('current_sub_unit_id', '=', self.sub_unit_id.id), ('initial_sub_unit_id', '=', self.sub_unit_id.id)])
            perm_employees = self.env['hr.employee'].search(perm_domain)
            eligible_employees = we_employees | perm_employees
        else:
            eligible_employees = unpaid_entries.mapped('employee_id')

        # Filter by structure_id if specified on batch
        if self.structure_id:
            def _emp_matches_structure(emp, target_struct):
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

            eligible_employees = eligible_employees.filtered(lambda e: _emp_matches_structure(e, self.structure_id))

        if not eligible_employees:
            worker_label = dict(self._fields['worker_type'].selection).get(self.worker_type, self.worker_type)
            struct_info = f" with structure '{self.structure_id.name}'" if self.structure_id else ""
            raise UserError(_(
                "No eligible employees or unpaid work entries found for %s%s in period from %s to %s.\n\n"
                "Please verify that work entries exist and are approved, or that active employees are configured."
            ) % (worker_label, struct_info, self.date_start, self.date_end))

        # 3. Exclude employees already having a payslip in this batch
        existing_emp_ids = self.slip_ids.mapped('employee_id').ids
        employees_to_process = eligible_employees.filtered(lambda e: e.id not in existing_emp_ids)

        if not employees_to_process:
            raise UserError(_("All eligible employees already have payslips generated in this batch."))

        # 4. Ensure contracts and salary structures exist
        payslip_vals = []
        Payslip = self.env['hr.payslip']

        for emp in employees_to_process:
            contract = emp._get_or_create_farm_contract()
            struct = self.structure_id
            if not struct:
                if emp.farm_employee_type == 'temporary':
                    struct = (
                        self.env.ref('farm_management.structure_farm_temporary', raise_if_not_found=False) or
                        self.env.ref('Farm-Management.structure_farm_temporary', raise_if_not_found=False) or
                        self.env.ref('Farm_Management.structure_farm_temporary', raise_if_not_found=False)
                    )
                elif emp.farm_employee_type == 'zemach':
                    struct = (
                        self.env.ref('farm_management.structure_farm_zemach', raise_if_not_found=False) or
                        self.env.ref('Farm-Management.structure_farm_zemach', raise_if_not_found=False) or
                        self.env.ref('Farm_Management.structure_farm_zemach', raise_if_not_found=False)
                    )
                elif emp.farm_employee_type in ('permanent', 'head_office'):
                    struct = (
                        self.env.ref('farm_management.structure_farm_permanent', raise_if_not_found=False) or
                        self.env.ref('Farm-Management.structure_farm_permanent', raise_if_not_found=False) or
                        self.env.ref('Farm_Management.structure_farm_permanent', raise_if_not_found=False)
                    )

                if not struct and contract and contract.structure_type_id:
                    struct = contract.structure_type_id.default_struct_id

            slip_name = _('Payslip - %s - %s', emp.name, self.name or '')
            vals = {
                'name': slip_name,
                'employee_id': emp.id,
                'payslip_run_id': self.id,
                'date_from': self.date_start,
                'date_to': self.date_end,
                'contract_id': contract.id if contract else False,
                'struct_id': struct.id if struct else False,
                'company_id': self.company_id.id,
            }
            payslip_vals.append(vals)

        # 5. Create payslips and compute sheet
        created_slips = Payslip.with_context(tracking_disable=True).create(payslip_vals)
        for slip in created_slips:
            slip._attach_farm_work_entries()
            slip.compute_sheet()

        self.state = 'verify'
        self.slip_ids.write({'state': 'verify'})

        # Immediately transition UI to view the generated payslips
        return {
            'name': _('Payslips - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', self.slip_ids.ids)],
            'context': {
                'default_payslip_run_id': self.id,
            },
        }


    def action_validate(self):
        res = super().action_validate() if hasattr(super(), 'action_validate') else True
        # Update all linked work entries to paid
        for batch in self:
            entries = batch.slip_ids.mapped('farm_work_entry_ids')
            if entries:
                entries.write({
                    'payment_status': 'paid',
                    'paid_date': fields.Date.today(),
                })
        return res

    def action_draft(self):
        res = super().action_draft() if hasattr(super(), 'action_draft') else True
        for batch in self:
            work_entries = self.env['farm.work.entry'].search([
                '|',
                ('payslip_run_id', '=', batch.id),
                ('payslip_id', 'in', batch.slip_ids.ids),
            ])
            if work_entries:
                work_entries.write({
                    'payment_status': 'unpaid',
                    'payslip_id': False,
                    'payslip_run_id': False,
                    'paid_date': False,
                })
        return res

    def unlink(self):
        # Release all work entries back to unpaid status upon deletion of batch
        for batch in self:
            work_entries = self.env['farm.work.entry'].search([
                '|',
                ('payslip_run_id', '=', batch.id),
                ('payslip_id', 'in', batch.slip_ids.ids),
            ])
            if work_entries:
                work_entries.write({
                    'payment_status': 'unpaid',
                    'payslip_id': False,
                    'payslip_run_id': False,
                    'paid_date': False,
                })
        return super().unlink()
