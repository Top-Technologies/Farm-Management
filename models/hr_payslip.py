# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    farm_employee_type = fields.Selection(
        related='employee_id.farm_employee_type',
        string='Worker Classification',
        store=True,
        readonly=True,
    )
    farm_id = fields.Many2one(
        'farm.farm',
        related='employee_id.current_farm_id',
        string='Farm Location',
        store=True,
        readonly=True,
    )
    sub_unit_id = fields.Many2one(
        'farm.sub.unit',
        related='employee_id.current_sub_unit_id',
        string='Sub Unit Location',
        store=True,
        readonly=True,
    )

    # Linked Farm Work Entries
    farm_work_entry_ids = fields.One2many(
        'farm.work.entry',
        'payslip_id',
        string='Farm Work Entries',
        help='Field work entries included in this payslip for daily or piece-rate wage calculation.',
    )
    farm_work_entries_count = fields.Integer(
        string='Work Entries Count',
        compute='_compute_farm_work_entry_stats',
        store=True,
    )
    farm_work_total_amount = fields.Float(
        string='Farm Total Amount (Birr)',
        compute='_compute_farm_work_entry_stats',
        store=True,
        digits=(16, 2),
        help='Total gross earnings calculated directly from attached farm work entries.',
    )
    farm_work_days_count = fields.Float(
        string='Total Work Days',
        compute='_compute_farm_work_entry_stats',
        digits=(16, 2),
        help='Total full days and half days worked by temporary worker.',
    )

    @api.depends('farm_work_entry_ids', 'farm_work_entry_ids.total_amount', 'farm_work_entry_ids.score_value')
    def _compute_farm_work_entry_stats(self):
        for slip in self:
            entries = slip.farm_work_entry_ids
            slip.farm_work_entries_count = len(entries)
            slip.farm_work_total_amount = sum(entries.mapped('total_amount'))
            slip.farm_work_days_count = sum(entries.mapped('score_value'))

    def _attach_farm_work_entries(self):
        """Finds and attaches unpaid non-cancelled work entries for Temporary & Zemach workers."""
        for slip in self:
            emp = slip.employee_id
            if emp.farm_employee_type in ('temporary', 'zemach'):
                domain = [
                    ('employee_id', '=', emp.id),
                    ('date', '>=', slip.date_from),
                    ('date', '<=', slip.date_to),
                    ('state', '!=', 'cancelled'),
                    ('payment_status', 'in', ('unpaid', 'in_payroll', False)),
                    '|',
                    ('payslip_id', '=', False),
                    ('payslip_id', '=', slip.id),
                ]
                work_entries = self.env['farm.work.entry'].search(domain)
                if work_entries:
                    work_entries.write({
                        'payslip_id': slip.id,
                        'payslip_run_id': slip.payslip_run_id.id if slip.payslip_run_id else False,
                        'payment_status': 'in_payroll',
                    })

    def compute_sheet(self):
        # Attach farm work entries before computing salary rules
        self._attach_farm_work_entries()
        return super().compute_sheet()

    def action_payslip_done(self):
        res = super().action_payslip_done()
        for slip in self:
            if slip.farm_work_entry_ids:
                slip.farm_work_entry_ids.write({
                    'payment_status': 'paid',
                    'paid_date': fields.Date.today(),
                })
        return res

    def action_payslip_paid(self):
        res = super().action_payslip_paid()
        for slip in self:
            if slip.farm_work_entry_ids:
                slip.farm_work_entry_ids.write({
                    'payment_status': 'paid',
                    'paid_date': fields.Date.today(),
                })
        return res

    def action_payslip_cancel(self):
        work_entries = self.env['farm.work.entry'].search([('payslip_id', 'in', self.ids)])
        if work_entries:
            work_entries.write({
                'payment_status': 'unpaid',
                'payslip_id': False,
                'payslip_run_id': False,
                'paid_date': False,
            })
        return super().action_payslip_cancel()

    def action_payslip_draft(self):
        work_entries = self.env['farm.work.entry'].search([('payslip_id', 'in', self.ids)])
        if work_entries:
            work_entries.write({
                'payment_status': 'unpaid',
                'payslip_id': False,
                'payslip_run_id': False,
                'paid_date': False,
            })
        return super().action_payslip_draft()

    def unlink(self):
        # Release all work entries back to unpaid status upon deletion of payslips
        work_entries = self.env['farm.work.entry'].search([('payslip_id', 'in', self.ids)])
        if work_entries:
            work_entries.write({
                'payment_status': 'unpaid',
                'payslip_id': False,
                'payslip_run_id': False,
                'paid_date': False,
            })
        return super().unlink()
