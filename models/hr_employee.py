# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools import html_escape
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Agricultural Employee Classification (Mandatory)
    farm_employee_type = fields.Selection([
        ('permanent', 'Permanent'),
        ('temporary', 'Temporary'),
        ('zemach', 'Zemach'),
    ], string='Employee Classification', default='temporary', required=True, tracking=True)

    # Agricultural Placement Fields
    initial_farm_id = fields.Many2one(
        'farm.farm',
        string='Assigned Farm',
        help='The farm to which this employee is assigned for ID generation and baseline placement.',
        tracking=True,
    )
    initial_sub_farm_id = fields.Many2one(
        'farm.sub.farm',
        string='Assigned Sub Farm',
        domain="[('farm_id', '=', initial_farm_id)]",
        help='The sub farm to which this employee is assigned.',
        tracking=True,
    )
    initial_sub_unit_id = fields.Many2one(
        'farm.sub.unit',
        string='Assigned Sub Unit',
        domain="[('sub_farm_id', '=', initial_sub_farm_id)]",
        help='The sub unit where this field worker operates.',
        tracking=True,
    )
    initial_block_id = fields.Many2one(
        'farm.block',
        string='Assigned Block (Optional)',
        domain="[('sub_unit_id', '=', initial_sub_unit_id)]",
        help='Optional specific block assignment.',
        tracking=True,
    )

    # FMS & Employee Identifiers (Format: [FarmCode][TypeCode][Seq] e.g. FM01T0001)
    employee_code = fields.Char(
        string='Employee ID / Number',
        copy=False,
        readonly=True,
        help='Unique employee sequential code e.g. FM01T0001, FM03Z5283',
    )
    fms_employee_id = fields.Char(
        string='Employee ID',
        copy=False,
        readonly=True,
        index=True,
        tracking=True,
        help='Auto-generated identifier in format: [FarmCode][TypeCode][SequentialNumber] (e.g. FM01T0001, FM03Z5283)',
    )

    # Relational management linkages
    managed_farm_ids = fields.One2many(
        'farm.farm',
        'manager_id',
        string='Managed Farms',
    )
    managed_sub_farm_ids = fields.One2many(
        'farm.sub.farm',
        'manager_id',
        string='Managed Sub Farms',
    )
    managed_sub_unit_ids = fields.One2many(
        'farm.sub.unit',
        'manager_id',
        string='Managed Sub Units',
    )
    supervised_block_ids = fields.One2many(
        'farm.block',
        'supervisor_id',
        string='Supervised Blocks',
    )

    # Transfer & Assignment History
    transfer_history_ids = fields.One2many(
        'farm.employee.transfer',
        'employee_id',
        string='Transfer & Assignment History',
    )

    # Work Entries & Productivity Tracking
    work_entry_ids = fields.One2many(
        'farm.work.entry',
        'employee_id',
        string='Work Entries',
    )
    work_entry_count = fields.Integer(
        string='Work Entries Count',
        compute='_compute_work_entry_stats',
    )
    total_earned_amount = fields.Float(
        string='Total Earnings (Birr)',
        compute='_compute_work_entry_stats',
        digits=(16, 2),
    )
    unpaid_work_entry_count = fields.Integer(
        string='Unpaid Work Entries',
        compute='_compute_work_entry_stats',
    )
    unpaid_work_entry_amount = fields.Float(
        string='Unpaid Earnings (Birr)',
        compute='_compute_work_entry_stats',
        digits=(16, 2),
    )
    paid_work_entry_amount = fields.Float(
        string='Paid Earnings (Birr)',
        compute='_compute_work_entry_stats',
        digits=(16, 2),
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
    )

    # Permanent Employee Salary Matrix (Grade & Level Scale)
    salary_matrix_type = fields.Selection([
        ('head_office', 'Head Office (ዋና መ/ቤት)'),
        ('cpw', 'CPW'),
        ('farm', 'Farm Permanent (የእርሻ ልማቶች - ቋሚ)'),
    ], string='Salary Scale Category', tracking=True, help='Select which Salary Matrix applies to this permanent employee.')

    salary_grade = fields.Selection([
        (str(i), f'Grade {i} (ደረጃ {i})') for i in range(1, 23)
    ], string='Salary Grade (ደረጃ)', tracking=True, help='Employee grade from Grade 1 to Grade 22.')

    salary_level = fields.Selection([
        ('base', 'Base (መነሻ)'),
        ('1', 'Step 1'),
        ('2', 'Step 2'),
        ('3', 'Step 3'),
        ('4', 'Step 4'),
        ('5', 'Step 5'),
        ('6', 'Step 6'),
        ('7', 'Step 7'),
        ('8', 'Step 8'),
        ('9', 'Step 9'),
        ('10', 'Step 10'),
        ('11', 'Step 11'),
        ('12', 'Step 12'),
        ('max', 'Max / Ceiling (ጣሪያ)'),
    ], string='Salary Step / Level', tracking=True, help='Step / Level from Base to Step 12 to Max.')

    matrix_basic_wage = fields.Float(
        string='Matrix Basic Wage (Birr)',
        compute='_compute_matrix_basic_wage',
        store=True,
        digits=(16, 2),
        tracking=True,
        help='Monthly basic wage determined automatically by the Salary Matrix.',
    )

    @api.depends('salary_matrix_type', 'salary_grade', 'salary_level', 'company_id', 'farm_employee_type')
    def _compute_matrix_basic_wage(self):
        for emp in self:
            # Salary matrix applies only to permanent staff, not daily/piece-rate temporary/zemach workers
            if emp.farm_employee_type in ('temporary', 'zemach'):
                emp.matrix_basic_wage = 0.0
                continue

            if emp.salary_matrix_type and emp.salary_grade and emp.salary_level:
                try:
                    wage = self.env['hr.salary.matrix'].get_matrix_wage(
                        matrix_type=emp.salary_matrix_type,
                        grade=int(emp.salary_grade),
                        level=emp.salary_level,
                        company_id=emp.company_id.id if emp.company_id else None,
                    )
                    emp.matrix_basic_wage = wage
                except Exception as e:
                    _logger.warning("Failed to compute matrix basic wage for employee %s: %s", emp.name, str(e))
                    emp.matrix_basic_wage = 0.0
            else:
                emp.matrix_basic_wage = 0.0

    @api.onchange('farm_employee_type')
    def _onchange_farm_employee_type_matrix(self):
        if self.farm_employee_type == 'permanent' and not self.salary_matrix_type:
            self.salary_matrix_type = 'farm'
        elif self.farm_employee_type in ('temporary', 'zemach'):
            self.salary_matrix_type = False
            self.salary_grade = False
            self.salary_level = False

    # Current Assignment from Latest Active Transfer
    current_transfer_id = fields.Many2one(
        'farm.employee.transfer',
        string='Current Active Transfer',
        compute='_compute_current_transfer',
        store=True,
    )
    current_farm_id = fields.Many2one(
        'farm.farm',
        string='Current Farm',
        compute='_compute_current_location',
        store=True,
        readonly=True,
    )
    current_sub_farm_id = fields.Many2one(
        'farm.sub.farm',
        string='Current Sub Farm',
        compute='_compute_current_location',
        store=True,
        readonly=True,
    )
    current_sub_unit_id = fields.Many2one(
        'farm.sub.unit',
        string='Current Sub Unit',
        compute='_compute_current_location',
        store=True,
        readonly=True,
    )
    current_block_id = fields.Many2one(
        'farm.block',
        string='Current Block',
        compute='_compute_current_location',
        store=True,
        readonly=True,
    )

    # Computed Counts & Visibility Flags
    managed_farm_count = fields.Integer(
        string='Managed Farms Count',
        compute='_compute_farm_counts',
    )
    transfer_count = fields.Integer(
        string='Transfers Count',
        compute='_compute_farm_counts',
    )

    has_farm_management_scope = fields.Boolean(
        string='Has Farm Management Scope',
        compute='_compute_farm_counts',
    )
    has_block_supervision_scope = fields.Boolean(
        string='Has Block Supervision Scope',
        compute='_compute_farm_counts',
    )
    has_management_role = fields.Boolean(
        string='Has Management Role',
        compute='_compute_farm_counts',
    )
    has_transfer_history = fields.Boolean(
        string='Has Transfer History',
        compute='_compute_farm_counts',
    )
    has_any_farm_assignment = fields.Boolean(
        string='Has Any Farm Assignment',
        compute='_compute_farm_counts',
    )

    # Hierarchical Placement Breakdown
    farm_structure_hierarchy_display = fields.Html(
        string='Farm Structure & Assignments',
        compute='_compute_farm_hierarchy_display',
        sanitize=False,
    )

    # Cascading Location Onchanges
    @api.onchange('initial_farm_id')
    def _onchange_initial_farm_id(self):
        if self.initial_sub_farm_id and self.initial_sub_farm_id.farm_id != self.initial_farm_id:
            self.initial_sub_farm_id = False
            self.initial_sub_unit_id = False
            self.initial_block_id = False
        self._update_preview_id()

    @api.onchange('initial_sub_farm_id')
    def _onchange_initial_sub_farm_id(self):
        if self.initial_sub_farm_id:
            self.initial_farm_id = self.initial_sub_farm_id.farm_id
            if self.initial_sub_unit_id and self.initial_sub_unit_id.sub_farm_id != self.initial_sub_farm_id:
                self.initial_sub_unit_id = False
                self.initial_block_id = False
        self._update_preview_id()

    @api.onchange('initial_sub_unit_id')
    def _onchange_initial_sub_unit_id(self):
        if self.initial_sub_unit_id:
            self.initial_sub_farm_id = self.initial_sub_unit_id.sub_farm_id
            self.initial_farm_id = self.initial_sub_unit_id.farm_id
            if self.initial_block_id and self.initial_block_id.sub_unit_id != self.initial_sub_unit_id:
                self.initial_block_id = False
        self._update_preview_id()

    @api.onchange('initial_block_id')
    def _onchange_initial_block_id(self):
        if self.initial_block_id:
            self.initial_sub_unit_id = self.initial_block_id.sub_unit_id
            self.initial_sub_farm_id = self.initial_block_id.sub_farm_id
            self.initial_farm_id = self.initial_block_id.farm_id
        self._update_preview_id()

    @api.onchange('farm_employee_type')
    def _onchange_farm_employee_type(self):
        self._update_preview_id()

    def _update_preview_id(self):
        farm = self.initial_farm_id or self.current_farm_id
        if farm and self.farm_employee_type:
            new_id = self._generate_farm_employee_id(farm, self.farm_employee_type)
            self.fms_employee_id = new_id
            self.employee_code = new_id

    def _generate_farm_employee_id(self, farm, emp_type):
        """Generates sequential ID in format [FarmCode][TypeCode][SequentialNumber] (e.g. FM01T0001)."""
        type_map = {'permanent': 'P', 'temporary': 'T', 'zemach': 'Z'}
        type_code = type_map.get(emp_type or 'temporary', 'T')
        if farm:
            farm_code = farm.code or (farm.name[:4].upper() if farm.name else 'FM01')
        else:
            default_farm = self.env['farm.farm'].search([], limit=1)
            farm_code = (default_farm.code or default_farm.name[:4].upper()) if default_farm else 'FM01'

        prefix = f"{farm_code}{type_code}"
        existing_domain = [('fms_employee_id', '=like', f"{prefix}%")]
        if self.id:
            existing_domain.append(('id', '!=', self.id))

        existing_records = self.env['hr.employee'].search(existing_domain)
        max_num = 0
        for rec in existing_records:
            code_val = rec.fms_employee_id or ''
            num_part = code_val[len(prefix):]
            if num_part.isdigit():
                num = int(num_part)
                if num > max_num:
                    max_num = num
        next_num = max_num + 1
        return f"{prefix}{next_num:04d}"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            emp_type = vals.get('farm_employee_type', 'temporary')
            vals['farm_employee_type'] = emp_type

            farm_id = vals.get('initial_farm_id')
            farm = self.env['farm.farm'].browse(farm_id) if farm_id else self.env['farm.farm'].search([], limit=1)

            if not vals.get('fms_employee_id') or '_' in str(vals.get('fms_employee_id', '')):
                new_id = self._generate_farm_employee_id(farm, emp_type)
                vals['fms_employee_id'] = new_id
                vals['employee_code'] = new_id

        employees = super().create(vals_list)

        # Auto-create initial transfer record if placement is specified
        for emp in employees:
            if emp.initial_farm_id and not emp.transfer_history_ids:
                self.env['farm.employee.transfer'].create({
                    'employee_id': emp.id,
                    'farm_id': emp.initial_farm_id.id,
                    'sub_farm_id': emp.initial_sub_farm_id.id if emp.initial_sub_farm_id else False,
                    'sub_unit_id': emp.initial_sub_unit_id.id if emp.initial_sub_unit_id else False,
                    'block_id': emp.initial_block_id.id if emp.initial_block_id else False,
                    'transfer_date': fields.Date.today(),
                    'notes': _('Initial baseline placement upon employee registration'),
                })
        return employees

    def write(self, vals):
        if 'farm_employee_type' in vals or 'initial_farm_id' in vals:
            for employee in self:
                new_type = vals.get('farm_employee_type', employee.farm_employee_type)
                farm_id = vals.get('initial_farm_id', employee.initial_farm_id.id if employee.initial_farm_id else False)
                new_farm = self.env['farm.farm'].browse(farm_id) if farm_id else (employee.current_farm_id or employee.initial_farm_id)

                if new_type != employee.farm_employee_type or (farm_id and farm_id != (employee.initial_farm_id.id if employee.initial_farm_id else False)):
                    new_id = employee._generate_farm_employee_id(new_farm, new_type)
                    vals['fms_employee_id'] = new_id
                    vals['employee_code'] = new_id
        return super().write(vals)

    @api.depends('work_entry_ids', 'work_entry_ids.total_amount', 'work_entry_ids.state', 'work_entry_ids.payment_status')
    def _compute_work_entry_stats(self):
        for employee in self:
            entries = employee.work_entry_ids.filtered(lambda e: e.state != 'cancelled')
            employee.work_entry_count = len(entries)
            employee.total_earned_amount = sum(entries.mapped('total_amount'))
            unpaid = entries.filtered(lambda e: e.payment_status == 'unpaid' and e.state in ('confirmed', 'approved'))
            employee.unpaid_work_entry_count = len(unpaid)
            employee.unpaid_work_entry_amount = sum(unpaid.mapped('total_amount'))
            paid = entries.filtered(lambda e: e.payment_status == 'paid')
            employee.paid_work_entry_amount = sum(paid.mapped('total_amount'))

    @api.depends('transfer_history_ids', 'transfer_history_ids.moving_date', 'transfer_history_ids.transfer_date')
    def _compute_current_transfer(self):
        for employee in self:
            # Active transfer is the latest transfer where moving_date is False
            active_transfers = employee.transfer_history_ids.filtered(lambda t: not t.moving_date)
            if active_transfers:
                employee.current_transfer_id = active_transfers[0]
            elif employee.transfer_history_ids:
                employee.current_transfer_id = employee.transfer_history_ids[0]
            else:
                employee.current_transfer_id = False

    @api.depends('current_transfer_id', 'initial_farm_id', 'initial_sub_farm_id', 'initial_sub_unit_id', 'initial_block_id')
    def _compute_current_location(self):
        for employee in self:
            curr = employee.current_transfer_id
            if curr and not curr.moving_date:
                employee.current_farm_id = curr.farm_id
                employee.current_sub_farm_id = curr.sub_farm_id
                employee.current_sub_unit_id = curr.sub_unit_id
                employee.current_block_id = curr.block_id
            else:
                employee.current_farm_id = employee.initial_farm_id
                employee.current_sub_farm_id = employee.initial_sub_farm_id
                employee.current_sub_unit_id = employee.initial_sub_unit_id
                employee.current_block_id = employee.initial_block_id

    @api.depends(
        'managed_farm_ids',
        'managed_sub_farm_ids',
        'managed_sub_unit_ids',
        'supervised_block_ids',
        'transfer_history_ids',
    )
    def _compute_farm_counts(self):
        for employee in self:
            farm_cnt = len(employee.managed_farm_ids)
            sub_farm_cnt = len(employee.managed_sub_farm_ids)
            sub_unit_cnt = len(employee.managed_sub_unit_ids)
            super_cnt = len(employee.supervised_block_ids)
            transfer_cnt = len(employee.transfer_history_ids)

            employee.managed_farm_count = farm_cnt
            employee.transfer_count = transfer_cnt

            has_fm = bool(farm_cnt or sub_farm_cnt or sub_unit_cnt)
            has_sup = bool(super_cnt)
            has_transfers = bool(transfer_cnt)

            employee.has_farm_management_scope = has_fm
            employee.has_block_supervision_scope = has_sup
            employee.has_management_role = has_fm or has_sup
            employee.has_transfer_history = has_transfers
            employee.has_any_farm_assignment = has_fm or has_sup or has_transfers

    @api.depends(
        'name',
        'farm_employee_type',
        'fms_employee_id',
        'current_farm_id.name',
        'current_sub_farm_id.name',
        'current_sub_unit_id.name',
        'current_block_id.name',
        'managed_farm_ids.name',
        'managed_sub_farm_ids.name',
        'managed_sub_unit_ids.name',
        'supervised_block_ids.name',
    )
    def _compute_farm_hierarchy_display(self):
        for employee in self:
            items = []
            emp_name = employee.name or _('This Employee')

            # Classification & ID Card
            type_label = dict(self._fields['farm_employee_type'].selection).get(employee.farm_employee_type, 'Temporary')
            badge_color = 'primary' if employee.farm_employee_type == 'permanent' else ('warning text-dark' if employee.farm_employee_type == 'temporary' else 'info')
            id_str = employee.fms_employee_id or _('Unassigned')

            items.append(f"""
                <div class="d-flex justify-content-between align-items-center mb-2 p-2 border rounded bg-white shadow-sm">
                    <div>
                        <span class="badge text-bg-{badge_color} me-2"><i class="fa fa-id-badge me-1"></i>{html_escape(type_label)}</span>
                        <span>Employee ID: <strong class="text-primary font-monospace fs-6">{html_escape(id_str)}</strong></span>
                    </div>
                </div>
            """)

            # Current Field Location / Active Assignment
            farm = employee.current_farm_id or employee.initial_farm_id
            sub_farm = employee.current_sub_farm_id or employee.initial_sub_farm_id
            sub_unit = employee.current_sub_unit_id or employee.initial_sub_unit_id
            block = employee.current_block_id or employee.initial_block_id

            if farm or sub_unit:
                su_name = sub_unit.name if sub_unit else _('Unassigned Sub Unit')
                sf_name = sub_farm.name if sub_farm else _('Unassigned Sub Farm')
                farm_name = farm.name if farm else _('Unassigned Farm')
                block_info = f", Block: <strong>{html_escape(block.name)}</strong>" if block else ""
                items.append(f"""
                    <div class="d-flex align-items-center mb-2 p-2 border rounded bg-light border-success">
                        <span class="badge text-bg-success me-2"><i class="fa fa-map-marker me-1"></i>Active Field Assignment</span>
                        <span><strong>{html_escape(emp_name)}</strong> is deployed in Sub Unit <strong>{html_escape(su_name)}</strong>{block_info} of Sub Farm <em>{html_escape(sf_name)}</em> of Farm <em>{html_escape(farm_name)}</em></span>
                    </div>
                """)

            # Management Scopes
            for farm_m in employee.managed_farm_ids:
                items.append(f"""
                    <div class="d-flex align-items-center mb-2 p-2 border rounded bg-light">
                        <span class="badge text-bg-primary me-2"><i class="fa fa-university me-1"></i>Farm Manager</span>
                        <span><strong>{html_escape(emp_name)}</strong> is the <strong>Farm Manager</strong> of <strong>{html_escape(farm_m.name or '')}</strong></span>
                    </div>
                """)

            for sf_m in employee.managed_sub_farm_ids:
                items.append(f"""
                    <div class="d-flex align-items-center mb-2 p-2 border rounded bg-light">
                        <span class="badge text-bg-info me-2"><i class="fa fa-th-large me-1"></i>Sub Farm Manager</span>
                        <span><strong>{html_escape(emp_name)}</strong> is the <strong>Sub Farm Manager</strong> of <strong>{html_escape(sf_m.name or '')}</strong></span>
                    </div>
                """)

            for su_m in employee.managed_sub_unit_ids:
                items.append(f"""
                    <div class="d-flex align-items-center mb-2 p-2 border rounded bg-light">
                        <span class="badge text-bg-success me-2"><i class="fa fa-th me-1"></i>Sub Unit Manager</span>
                        <span><strong>{html_escape(emp_name)}</strong> is the <strong>Sub Unit Manager</strong> of <strong>{html_escape(su_m.name or '')}</strong></span>
                    </div>
                """)

            for blk_m in employee.supervised_block_ids:
                items.append(f"""
                    <div class="d-flex align-items-center mb-2 p-2 border rounded bg-light">
                        <span class="badge text-bg-warning text-dark me-2"><i class="fa fa-shield me-1"></i>Block Supervisor</span>
                        <span><strong>{html_escape(emp_name)}</strong> is the <strong>Supervisor</strong> of Block <strong>{html_escape(blk_m.name or '')}</strong></span>
                    </div>
                """)

            employee.farm_structure_hierarchy_display = Markup("".join(items))

    def action_view_managed_farms(self):
        self.ensure_one()
        return {
            'name': _('Managed Farms: %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'farm.farm',
            'view_mode': 'list,kanban,form',
            'domain': [('manager_id', '=', self.id)],
            'context': {'default_manager_id': self.id},
        }

    def action_view_transfers(self):
        self.ensure_one()
        return {
            'name': _('Transfer History for %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'farm.employee.transfer',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def action_view_work_entries(self):
        self.ensure_one()
        return {
            'name': _('Work Entries: %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'farm.work.entry',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def action_view_unpaid_work_entries(self):
        self.ensure_one()
        return {
            'name': _('Unpaid Work Entries: %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'farm.work.entry',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id), ('payment_status', '=', 'unpaid')],
            'context': {'default_employee_id': self.id, 'search_default_unpaid': 1},
        }

    def _get_or_create_farm_contract(self):
        """Ensures an active contract exists for Temporary/Zemach workers to allow seamless payslip computation."""
        self.ensure_one()
        Contract = self.env['hr.contract']
        existing = Contract.search([
            ('employee_id', '=', self.id),
            ('state', 'in', ('open', 'draft', 'close')),
        ], order='date_start desc', limit=1)
        if existing:
            return existing

        struct_type = self.env.ref('farm_management.structure_type_farm_worker', raise_if_not_found=False)
        if not struct_type:
            struct_type = self.env['hr.payroll.structure.type'].search([], limit=1)

        struct = False
        if self.farm_employee_type == 'temporary':
            struct = self.env.ref('farm_management.structure_farm_temporary', raise_if_not_found=False)
        elif self.farm_employee_type == 'zemach':
            struct = self.env.ref('farm_management.structure_farm_zemach', raise_if_not_found=False)

        type_name = dict(self._fields['farm_employee_type'].selection).get(self.farm_employee_type, self.farm_employee_type or 'Worker')
        contract_vals = {
            'name': f"Farm Contract - {self.name} ({type_name})",
            'employee_id': self.id,
            'company_id': self.company_id.id,
            'structure_type_id': struct_type.id if struct_type else False,
            'wage': 0.0,
            'state': 'open',
            'date_start': fields.Date.today(),
        }
        if struct and hasattr(Contract, 'struct_id'):
            contract_vals['struct_id'] = struct.id
        return Contract.create(contract_vals)
