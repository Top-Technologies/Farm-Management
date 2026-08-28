# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

RELATIONSHIP_SELECTION = [
    ('wife', 'Wife'),
    ('children', 'Children'),
    ('mother', 'Mother'),
    ('father', 'Father'),
    ('grandmother', 'Grandmother'),
    ('grandfather', 'Grandfather'),
    ('uncle', 'Uncle'),
    ('aunt', 'Aunt'),
]


class HrEmployeeFamilyMember(models.Model):
    _name = 'hr.employee.family.member'
    _description = 'Employee Family Member'
    _order = 'relationship asc, name asc, id asc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(
        string='Name',
        required=True,
        help='Full name of the family member.',
    )
    relationship = fields.Selection(
        RELATIONSHIP_SELECTION,
        string='Relationship',
        required=True,
        help='Relationship with the employee.',
    )
    birthday = fields.Date(
        string='Date of Birth',
        help='Date of birth (applicable for children).',
    )
    age = fields.Integer(
        string='Age',
        compute='_compute_age',
        store=True,
        help='Calculated age in years from Date of Birth.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='employee_id.company_id',
        store=True,
        readonly=True,
    )

    @api.depends('birthday', 'relationship')
    def _compute_age(self):
        today = fields.Date.today()
        for rec in self:
            if rec.relationship == 'children' and rec.birthday:
                d_birth = rec.birthday
                age = today.year - d_birth.year - ((today.month, today.day) < (d_birth.month, d_birth.day))
                rec.age = max(0, age)
            else:
                rec.age = 0

    @api.onchange('relationship')
    def _onchange_relationship(self):
        if self.relationship != 'children':
            self.birthday = False
            self.age = 0

    @api.onchange('birthday')
    def _onchange_birthday(self):
        if self.birthday and self.relationship == 'children':
            today = fields.Date.today()
            d_birth = self.birthday
            age = today.year - d_birth.year - ((today.month, today.day) < (d_birth.month, d_birth.day))
            self.age = max(0, age)
        else:
            self.age = 0

