# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrSalaryAttachmentSchedule(models.Model):
    _name = 'hr.salary.attachment.schedule'
    _description = 'Salary Attachment Repayment Schedule'
    _order = 'date asc, sequence asc, id asc'

    attachment_id = fields.Many2one(
        'hr.salary.attachment',
        string='Salary Attachment',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string='No.', default=1)
    date = fields.Date(
        string='Scheduled Month / Date',
        required=True,
        help='Repayment month for this installment.',
    )
    amount = fields.Monetary(
        string='Installment Amount',
        required=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='attachment_id.currency_id',
    )
    state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('skipped', 'Skipped / Deferred'),
        ('paid', 'Paid / Deducted'),
    ], string='Status', default='scheduled', required=True)

    notes = fields.Char(string='Remarks / Reason')
    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Deducted On Payslip',
        readonly=True,
    )
    is_current_month = fields.Boolean(
        string='Is Current Month',
        compute='_compute_is_current_month',
    )

    @api.depends('date')
    def _compute_is_current_month(self):
        today = fields.Date.today()
        for line in self:
            if line.date:
                line.is_current_month = (line.date.year == today.year and line.date.month == today.month)
            else:
                line.is_current_month = False

    def action_adjust_this_line(self):
        self.ensure_one()
        month_label = self.date.strftime('%B %Y') if self.date else ''
        return {
            'name': _('Adjust Repayment: %s') % month_label,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.salary.attachment.adjust.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_attachment_id': self.attachment_id.id,
                'default_schedule_line_id': self.id,
            },
        }
