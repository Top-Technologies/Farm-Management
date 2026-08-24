# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    worker_type = fields.Selection([
        ('temporary', 'Temporary Workers (Daily Wage)'),
        ('zemach', 'Seasonal / Zemach Workers (Piece Rate)'),
        ('permanent', 'Permanent Employees (Standard Salary)'),
        ('all', 'All Workers'),
    ], string='Worker Classification', default='temporary', required=True,
       help='Select which category of workers this payroll batch is targeting.')

    farm_id = fields.Many2one(
        'farm.farm',
        string='Farm Filter',
        help='Optional: Filter payroll batch to employees stationed at a specific farm.',
    )
    sub_unit_id = fields.Many2one(
        'farm.sub.unit',
        string='Sub Unit Filter',
        domain="[('farm_id', '=', farm_id)]",
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
        if self.sub_unit_id:
            we_domain.append(('sub_unit_id', '=', self.sub_unit_id.id))

        if self.worker_type != 'all':
            we_domain.append(('employee_id.farm_employee_type', '=', self.worker_type))

        unpaid_entries = self.env['farm.work.entry'].search(we_domain)

        # 2. Resolve eligible employees
        if self.worker_type == 'permanent':
            emp_domain = [
                ('farm_employee_type', '=', 'permanent'),
                '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id)
            ]
            if self.farm_id:
                emp_domain.extend(['|', ('current_farm_id', '=', self.farm_id.id), ('initial_farm_id', '=', self.farm_id.id)])
            eligible_employees = self.env['hr.employee'].search(emp_domain)
        else:
            eligible_employees = unpaid_entries.mapped('employee_id')

        if not eligible_employees:
            worker_label = dict(self._fields['worker_type'].selection).get(self.worker_type, self.worker_type)
            raise UserError(_(
                "No unpaid work entries found for %s in period from %s to %s.\n\n"
                "Please verify that:\n"
                "1. Work entries have dates between %s and %s.\n"
                "2. The employee classification is set to '%s'.\n"
                "3. The work entries are not in 'Cancelled' or 'Paid' status."
            ) % (worker_label, self.date_start, self.date_end, self.date_start, self.date_end, worker_label))

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
            struct = False
            if emp.farm_employee_type == 'temporary':
                struct = self.env.ref('farm_management.structure_farm_temporary', raise_if_not_found=False)
            elif emp.farm_employee_type == 'zemach':
                struct = self.env.ref('farm_management.structure_farm_zemach', raise_if_not_found=False)

            if not struct and contract:
                struct = contract.structure_type_id.default_struct_id or contract.struct_id

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Farm Payslips Generated'),
                'message': _('Successfully generated %d payslips for %d work entries totaling %.2f Birr.',
                             len(created_slips), self.farm_work_entry_count, self.farm_total_amount),
                'type': 'success',
                'sticky': False,
            }
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
