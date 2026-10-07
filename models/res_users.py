# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

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
        # Admin, superuser, or explicit All Classifications group sees all classifications
        if self._is_admin() or self._has_farm_group('group_employee_classification_all'):
            return ['head_office', 'permanent', 'temporary', 'zemach', 'cpw']

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

        # Backward compatibility for existing general group assignments
        if self._has_farm_group('group_employee_classification_general'):
            for t in ['head_office', 'permanent', 'temporary', 'zemach']:
                if t not in allowed:
                    allowed.append(t)

        return allowed

    def _get_allowed_salary_matrix_types(self):
        """ Return list of salary matrix scale types accessible by this user.
            Used dynamically in record rules for hr.salary.matrix.
        """
        self.ensure_one()
        if self._is_admin() or self._has_farm_group('group_employee_classification_all'):
            return ['head_office', 'farm', 'saudi_star', 'cpw', 'other']

        allowed_types = []
        if self._has_farm_group('group_employee_classification_cpw'):
            allowed_types.append('cpw')
        if self._has_farm_group('group_employee_classification_farm'):
            allowed_types.extend(['farm', 'saudi_star'])
        if self._has_farm_group('group_employee_classification_head_office'):
            allowed_types.append('head_office')
        if self._has_farm_group('group_employee_classification_general'):
            allowed_types.extend(['head_office', 'farm', 'saudi_star', 'other'])
        if (self._has_farm_group('group_employee_classification_temporary') or
                self._has_farm_group('group_employee_classification_zemach')):
            if 'farm' not in allowed_types:
                allowed_types.append('farm')

        return list(set(allowed_types))

    def _get_allowed_payslip_run_classifications(self):
        """ Return list of worker classifications for payslip batches accessible by this user.
            Used dynamically in record rules for hr.payslip.run.
        """
        self.ensure_one()
        allowed_emp = self._get_allowed_farm_employee_types()
        if not allowed_emp:
            return []
        if set(allowed_emp) >= {'head_office', 'permanent', 'temporary', 'zemach', 'cpw'}:
            return ['temporary', 'zemach', 'permanent', 'head_office', 'cpw', 'all']

        res = list(allowed_emp)
        if set(['temporary', 'zemach', 'permanent']).issubset(set(allowed_emp)):
            res.append('all')
        return res
