# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    allowed_farm_ids = fields.Many2many(
        'farm.farm',
        'res_users_farm_rel',
        'user_id',
        'farm_id',
        string='Allowed Farms / የተፈቀደላቸው እርሻዎች',
        help='Farms this user is permitted to view and manage. Leave empty to allow all farms (for Admin/HQ) or auto-restrict to their linked employee assigned farm.',
    )

    def _get_allowed_farm_ids(self):
        """ Return list of farm IDs accessible by this user.
            Used dynamically in record rules for farm.farm, farm.sub.farm, farm.sub.unit,
            farm.block, hr.employee, hr.payslip, etc.
        """
        self.ensure_one()
        # 1. Explicitly configured allowed farms on the user record take top precedence
        if self.allowed_farm_ids:
            return self.allowed_farm_ids.ids

        # 2. Superuser or explicit All Classifications group sees all farms
        if self._is_superuser() or self._has_farm_group('group_employee_classification_all'):
            return self.env['farm.farm'].sudo().search([]).ids

        # 3. Fallback to linked employee assigned farm
        emp = self.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', self.id)], limit=1)
        if emp:
            farm = emp.current_farm_id or emp.initial_farm_id
            if farm:
                return [farm.id]

        # 4. If admin user without explicit restriction, default to all farms
        if self._is_admin():
            return self.env['farm.farm'].sudo().search([]).ids

        # 5. Default: no farm accessible
        return []

    def _is_farm_restricted(self):
        """ Returns True if the user is restricted to specific farms, False if they can see all farms. """
        self.ensure_one()
        if self.allowed_farm_ids:
            all_farm_count = self.env['farm.farm'].sudo().search_count([])
            return len(self.allowed_farm_ids) < all_farm_count
        if self._is_superuser() or self._has_farm_group('group_employee_classification_all'):
            return False
        emp = self.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', self.id)], limit=1)
        if emp and (emp.current_farm_id or emp.initial_farm_id):
            return True
        if self._is_admin():
            return False
        return True

    def _has_farm_group(self, xml_name):
        """Helper to check group membership regardless of whether module
        is registered as farm_management, Farm-Management, or Farm_Management."""
        return (
            self.has_group(f'farm_management.{xml_name}') or
            self.has_group(f'Farm-Management.{xml_name}') or
            self.has_group(f'Farm_Management.{xml_name}')
        )

    def _get_allowed_farm_employee_types(self):
        """ Return list of employee classifications accessible by this user.
            Used dynamically in record rules for hr.employee, hr.contract, hr.payslip, etc.
        """
        self.ensure_one()
        # Superuser or explicit All Classifications group sees all classifications
        if self._is_superuser() or self._has_farm_group('group_employee_classification_all'):
            return ['head_office', 'jimma_head_office', 'bebeka_head_office', 'permanent', 'temporary', 'zemach', 'cpw']

        allowed = []
        if self._has_farm_group('group_employee_classification_cpw'):
            allowed.append('cpw')
        if self._has_farm_group('group_employee_classification_farm'):
            allowed.append('permanent')
        if self._has_farm_group('group_employee_classification_temporary'):
            allowed.append('temporary')
        if self._has_farm_group('group_employee_classification_zemach'):
            allowed.append('zemach')
        if self._has_farm_group('group_employee_classification_head_office'):
            allowed.append('head_office')
        if self._has_farm_group('group_employee_classification_jimma_head_office'):
            allowed.append('jimma_head_office')
        if self._has_farm_group('group_employee_classification_bebeka_head_office'):
            allowed.append('bebeka_head_office')

        # Backward compatibility for existing general group assignments
        if self._has_farm_group('group_employee_classification_general'):
            for t in ['head_office', 'jimma_head_office', 'bebeka_head_office', 'permanent', 'temporary', 'zemach']:
                if t not in allowed:
                    allowed.append(t)

        if allowed:
            return allowed

        # Fallback only if no classification groups are selected on the user:
        if self._is_admin():
            return ['head_office', 'jimma_head_office', 'bebeka_head_office', 'permanent', 'temporary', 'zemach', 'cpw']

        return []

    def _get_allowed_salary_matrix_types(self):
        """ Return list of salary matrix scale types accessible by this user.
            Used dynamically in record rules for hr.salary.matrix.
        """
        self.ensure_one()
        if self._is_superuser() or self._has_farm_group('group_employee_classification_all'):
            return ['head_office', 'farm', 'saudi_star', 'cpw', 'other']

        allowed_types = []
        if self._has_farm_group('group_employee_classification_cpw'):
            allowed_types.append('cpw')
        if self._has_farm_group('group_employee_classification_farm'):
            allowed_types.extend(['farm', 'saudi_star'])
        if self._has_farm_group('group_employee_classification_head_office'):
            allowed_types.append('head_office')
        if self._has_farm_group('group_employee_classification_jimma_head_office'):
            allowed_types.append('head_office')
        if self._has_farm_group('group_employee_classification_bebeka_head_office'):
            allowed_types.append('head_office')
        if self._has_farm_group('group_employee_classification_general'):
            allowed_types.extend(['head_office', 'farm', 'saudi_star', 'other'])
        if (self._has_farm_group('group_employee_classification_temporary') or
                self._has_farm_group('group_employee_classification_zemach')):
            if 'farm' not in allowed_types:
                allowed_types.append('farm')

        if allowed_types:
            return list(set(allowed_types))

        if self._is_admin():
            return ['head_office', 'farm', 'saudi_star', 'cpw', 'other']

        return []

    def _get_allowed_payslip_run_classifications(self):
        """ Return list of worker classifications for payslip batches accessible by this user.
            Used dynamically in record rules for hr.payslip.run.
        """
        self.ensure_one()
        allowed_emp = self._get_allowed_farm_employee_types()
        if not allowed_emp:
            return []
        if set(allowed_emp) >= {'head_office', 'permanent', 'temporary', 'zemach', 'cpw'}:
            return ['temporary', 'zemach', 'permanent', 'head_office', 'jimma_head_office', 'bebeka_head_office', 'cpw', 'all']

        res = list(allowed_emp)
        if set(['temporary', 'zemach', 'permanent']).issubset(set(allowed_emp)):
            res.append('all')
        return res
