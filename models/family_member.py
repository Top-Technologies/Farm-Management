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
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='employee_id.company_id',
        store=True,
        readonly=True,
    )
