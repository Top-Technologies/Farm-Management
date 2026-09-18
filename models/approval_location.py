# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class ApprovalLocation(models.Model):
    _name = 'approval.location'
    _description = 'Approval Operational Location'
    _order = 'sequence, name asc'

    name = fields.Char(string='Location / Farm Name', required=True)
    code = fields.Char(string='Location Code', copy=False)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)

    location_type = fields.Selection([
        ('farm', 'Farm (የእርሻ ቦታ)'),
        ('branch', 'Branch / Processing Unit (ቅርንጫፍ / ማቀነባበሪያ)'),
        ('head_office', 'Head Office (ዋና መ/ቤት)'),
    ], string='Location Type', default='farm', required=True)

    farm_id = fields.Many2one(
        'farm.farm',
        string='Linked Farm',
        ondelete='set null',
        help='The underlying farm associated with this operational location.',
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )

    approver_ids = fields.One2many(
        'approval.location.approver',
        'location_id',
        string='Default Approvers',
        copy=True,
    )

    approver_count = fields.Integer(
        string='Approvers Count',
        compute='_compute_approver_count',
    )

    @api.depends('approver_ids')
    def _compute_approver_count(self):
        for loc in self:
            loc.approver_count = len(loc.approver_ids)

    def name_get(self):
        """Display clear location name (e.g. 'Bebeka 1', 'Gomma 1') without raw codes."""
        result = []
        for rec in self:
            result.append((rec.id, rec.name))
        return result

    @api.depends('name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name

    def get_approvers(self, category_id=None):
        """
        Retrieves the list of approver dictionaries for this location.
        If category_id is provided, includes approvers configured specifically for this
        category as well as general approvers (category_id is False).
        """
        self.ensure_one()
        approvers = self.approver_ids.sorted(key=lambda a: (a.sequence, a.id))
        if category_id:
            cat_id = category_id.id if hasattr(category_id, 'id') else category_id
            filtered = approvers.filtered(lambda a: not a.category_id or a.category_id.id == cat_id)
            if filtered:
                approvers = filtered

        vals = []
        seen_users = set()
        for a in approvers:
            if a.user_id.id not in seen_users:
                seen_users.add(a.user_id.id)
                vals.append({
                    'user_id': a.user_id.id,
                    'required': a.required,
                    'sequence': a.sequence,
                })
        return vals

    def init(self):
        """
        Ensures standard locations exist:
        - Bebeka 1, Bebeka 2, Gomma 1, Gomma 2, Kossa (Farms)
        - CPW, Jimma HO (Branches)
        - Head Office (HQ)
        """
        super().init()
        try:
            with self.env.cr.savepoint():
                self._ensure_default_locations()
        except Exception as e:
            _logger.warning("Could not initialize default approval locations during init: %s", str(e))

    @api.model
    def _ensure_default_locations(self):
        """Creates or links default operational locations in Odoo."""
        # 1. Standard non-farm locations
        standard_non_farms = [
            ('Head Office', 'HQ', 'head_office'),
            ('CPW', 'CPW', 'branch'),
            ('Jimma HO', 'JHO', 'branch'),
        ]
        for name, code, loc_type in standard_non_farms:
            loc = self.search([
                '|', ('code', '=', code),
                     ('name', '=ilike', name)
            ], limit=1)
            if not loc:
                self.create({
                    'name': name,
                    'code': code,
                    'location_type': loc_type,
                    'company_id': self.env.company.id,
                })

        # 2. Sync all farm.farm records as approval locations
        farms = self.env['farm.farm'].search([])
        for farm in farms:
            loc = self.search([('farm_id', '=', farm.id)], limit=1)
            if not loc and farm.code:
                loc = self.search([('code', '=', farm.code), ('location_type', '=', 'farm')], limit=1)
            if not loc:
                loc = self.search([('name', '=ilike', farm.name), ('location_type', '=', 'farm')], limit=1)

            vals = {
                'name': farm.name,
                'code': farm.code,
                'location_type': 'farm',
                'farm_id': farm.id,
                'company_id': farm.company_id.id or self.env.company.id,
            }
            if loc:
                loc.write(vals)
            else:
                self.create(vals)


class ApprovalLocationApprover(models.Model):
    _name = 'approval.location.approver'
    _description = 'Approval Location Default Approver'
    _order = 'sequence, id'

    location_id = fields.Many2one(
        'approval.location',
        string='Location',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    user_id = fields.Many2one(
        'res.users',
        string='Approver',
        required=True,
        domain=[('share', '=', False)],
    )
    required = fields.Boolean(
        string='Required Approval',
        default=True,
        help='If checked, this approver must approve for the request to be validated.',
    )
    category_id = fields.Many2one(
        'approval.category',
        string='Specific Approval Type',
        help='Optional. If set, this approver only applies to requests under this specific category. If left empty, applies to all categories for this location.',
    )
    company_id = fields.Many2one(
        'res.company',
        related='location_id.company_id',
        store=True,
        readonly=True,
    )
