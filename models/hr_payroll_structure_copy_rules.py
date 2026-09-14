# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrPayrollStructure(models.Model):
    _inherit = 'hr.payroll.structure'

    def action_open_copy_rules_wizard(self):
        self.ensure_one()
        return {
            'name': _('Copy / Import Rules into %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.structure.copy.rules',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_target_structure_id': self.id,
                'active_id': self.id,
                'active_model': 'hr.payroll.structure',
            }
        }


class HrPayrollStructureCopyRules(models.TransientModel):
    _name = 'hr.payroll.structure.copy.rules'
    _description = 'Wizard: Copy Salary Rules Between Structures'

    target_structure_id = fields.Many2one(
        'hr.payroll.structure',
        string='Target Structure',
        required=True,
        readonly=True,
    )
    source_structure_id = fields.Many2one(
        'hr.payroll.structure',
        string='Source Structure',
        required=True,
        help='Select the salary structure from which to copy rules (e.g. Permanent & Head Office Employee Structure).',
    )
    rule_ids = fields.Many2many(
        'hr.salary.rule',
        string='Select Rules to Copy',
        help='Check or uncheck the specific rules you want to import into the target structure.',
    )
    copy_mode = fields.Selection([
        ('add_missing', 'Add Missing Rules (skip if rule with same code exists)'),
        ('overwrite', 'Overwrite / Replace Existing Rules with Same Code'),
    ], string='Copy Mode', default='add_missing', required=True)

    rules_count = fields.Integer(
        string='Selected Rules Count',
        compute='_compute_rules_count',
    )

    @api.depends('rule_ids')
    def _compute_rules_count(self):
        for rec in self:
            rec.rules_count = len(rec.rule_ids)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and self.env.context.get('active_model') == 'hr.payroll.structure':
            res['target_structure_id'] = active_id

            # Find default source structure: master permanent structure or one with highest rule count
            source_struct = self.env.ref('farm_management.structure_farm_permanent', raise_if_not_found=False)
            if not source_struct or source_struct.id == active_id:
                source_struct = self.env['hr.payroll.structure'].search([
                    ('id', '!=', active_id),
                    ('rule_ids', '!=', False)
                ], order='id asc', limit=1)

            if source_struct:
                res['source_structure_id'] = source_struct.id
                res['rule_ids'] = [(6, 0, source_struct.rule_ids.ids)]
        return res

    @api.onchange('source_structure_id')
    def _onchange_source_structure_id(self):
        if self.source_structure_id:
            self.rule_ids = [(6, 0, self.source_structure_id.rule_ids.ids)]
        else:
            self.rule_ids = [(5, 0, 0)]

    def action_select_all(self):
        self.ensure_one()
        if self.source_structure_id:
            self.rule_ids = [(6, 0, self.source_structure_id.rule_ids.ids)]
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_unselect_all(self):
        self.ensure_one()
        self.rule_ids = [(5, 0, 0)]
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_copy_rules(self):
        self.ensure_one()
        if not self.rule_ids:
            raise UserError(_("Please select at least one salary rule to copy."))

        target = self.target_structure_id
        existing_rules_by_code = {r.code: r for r in target.rule_ids if r.code}

        copied_count = 0
        updated_count = 0
        skipped_count = 0

        fields_to_copy = [
            'name', 'sequence', 'quantity', 'category_id', 'active',
            'appears_on_payslip', 'appears_on_employee_cost_dashboard',
            'appears_on_payroll_report', 'condition_select', 'condition_range',
            'condition_python', 'condition_range_min', 'condition_range_max',
            'amount_select', 'amount_fix', 'amount_percentage',
            'amount_python_compute', 'amount_percentage_base', 'partner_id', 'note'
        ]

        # Sort source rules by sequence to ensure correct calculation order
        sorted_rules = self.rule_ids.sorted(key=lambda r: (r.sequence, r.id))

        for rule in sorted_rules:
            vals = {}
            for fname in fields_to_copy:
                if fname in rule._fields:
                    val = getattr(rule, fname)
                    if hasattr(val, 'id'):  # Many2one
                        vals[fname] = val.id
                    else:
                        vals[fname] = val

            if rule.code in existing_rules_by_code:
                if self.copy_mode == 'overwrite':
                    existing = existing_rules_by_code[rule.code]
                    existing.write(vals)
                    updated_count += 1
                else:
                    skipped_count += 1
            else:
                vals['code'] = rule.code
                vals['struct_id'] = target.id
                self.env['hr.salary.rule'].create(vals)
                copied_count += 1

        msg = _("Successfully processed rules into '%s': %d created, %d updated, %d skipped.") % (
            target.name, copied_count, updated_count, skipped_count
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Salary Rules Copied'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }
