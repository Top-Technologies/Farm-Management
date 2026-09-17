# -*- coding: utf-8 -*-
from odoo import api, Command, fields, models, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class ApprovalCategory(models.Model):
    _inherit = 'approval.category'

    has_employee_type = fields.Selection([
        ('no', 'No'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], default='no', string='Employee Level', required=True,
       help='Whether to prompt for Employee Level (Normal Employee vs Executive).')

    def init(self):
        super().init()
        try:
            self._setup_standard_categories()
        except Exception as e:
            _logger.warning("Could not setup standard approval categories during init: %s", str(e))

    @api.model
    def _setup_standard_categories(self):
        """
        Configures the standard 6 HR & Operational categories:
        - Medical, Payslip: has_location = 'required'
        - Recruitment, Promotion, Resignation, Transfer: has_location = 'required', has_employee_type = 'required'
        """
        configs = {
            'Medical Request': {'has_location': 'required', 'has_employee_type': 'no'},
            'Recruitment Request': {'has_location': 'required', 'has_employee_type': 'required'},
            'Promotion Request': {'has_location': 'required', 'has_employee_type': 'required'},
            'Resignation Request': {'has_location': 'required', 'has_employee_type': 'required'},
            'Transfer Request': {'has_location': 'required', 'has_employee_type': 'required'},
            'Paylip Request': {'has_location': 'required', 'has_employee_type': 'no'},
            'Payslip Request': {'has_location': 'required', 'has_employee_type': 'no'},
        }
        for name, vals in configs.items():
            cat = self.search([('name', '=ilike', name)], limit=1)
            if cat:
                cat.write(vals)


class ApprovalRequest(models.Model):
    _inherit = 'approval.request'

    has_employee_type = fields.Selection(
        related='category_id.has_employee_type',
        string='Has Employee Type Setting',
        readonly=True,
    )

    approval_location_id = fields.Many2one(
        'approval.location',
        string='Farm / Location',
        tracking=True,
        check_company=True,
        default=lambda self: self._default_approval_location_id(),
        help='Operational farm or facility for which this approval request is submitted.',
    )

    employee_level = fields.Selection([
        ('normal', 'Normal Employee (መደበኛ ሠራተኛ)'),
        ('executive', 'Executive (ሥራ አስፈፃሚ / ከፍተኛ አመራር)'),
    ], string='Employee Level', default='normal', tracking=True,
       help='Normal employee requests are approved by Farm/Branch approvers; Executive requests are routed to Head Office.')

    routing_location_id = fields.Many2one(
        'approval.location',
        string='Effective Approving Location',
        compute='_compute_routing_location',
        store=True,
        help='The location whose approvers will review this request (Head Office for Executives; Farm/Branch for Normal).',
    )

    routing_notes = fields.Char(
        string='Routing Notice',
        compute='_compute_routing_location',
        store=True,
    )

    @api.model
    def _default_approval_location_id(self):
        """Defaults to the requester employee's assigned farm location if available."""
        emp = self.env.user.employee_id
        if emp:
            farm = emp.current_farm_id or emp.initial_farm_id
            if farm:
                loc = self.env['approval.location'].search([('farm_id', '=', farm.id)], limit=1)
                if loc:
                    return loc.id
            if emp.farm_employee_type == 'head_office':
                hq = self.env['approval.location'].search([('location_type', '=', 'head_office')], limit=1)
                if hq:
                    return hq.id
        return False

    @api.depends('approval_location_id', 'employee_level', 'category_id')
    def _compute_routing_location(self):
        hq_loc = self.env['approval.location'].search([('location_type', '=', 'head_office')], limit=1)
        for req in self:
            if req.employee_level == 'executive':
                req.routing_location_id = hq_loc.id if hq_loc else req.approval_location_id.id
                req.routing_notes = _("★ Routed to Head Office (Executive Level Decision)")
            else:
                req.routing_location_id = req.approval_location_id.id
                if req.approval_location_id:
                    req.routing_notes = _("✓ Routed to %s (Normal Employee)") % req.approval_location_id.name
                else:
                    req.routing_notes = False

    @api.onchange('approval_location_id', 'employee_level', 'category_id')
    def _onchange_location_or_level(self):
        """Immediately updates default approvers in real-time on form interaction."""
        self._compute_approver_ids()

    @api.depends('category_id', 'request_owner_id', 'approval_location_id', 'employee_level')
    def _compute_approver_ids(self):
        hq_loc = self.env['approval.location'].search([('location_type', '=', 'head_office')], limit=1)
        for request in self:
            # Check if this category uses location routing
            has_location = request.category_id.has_location != 'no'
            target_location = False
            if has_location:
                if request.employee_level == 'executive':
                    target_location = hq_loc or request.approval_location_id
                else:
                    target_location = request.approval_location_id

            location_approver_vals = target_location.get_approvers(category_id=request.category_id) if target_location else []

            if not location_approver_vals:
                # Standard base Odoo approvers resolution
                super(ApprovalRequest, request)._compute_approver_ids()
                continue

            # Build approver records from the resolved location
            approver_id_vals = [Command.clear()]
            existing_user_ids = set()

            # Include manager approval if required by category
            if request.category_id.manager_approval:
                employee = self.env['hr.employee'].search([('user_id', '=', request.request_owner_id.id)], limit=1)
                if employee.parent_id.user_id:
                    mgr_uid = employee.parent_id.user_id.id
                    approver_id_vals.append(Command.create({
                        'user_id': mgr_uid,
                        'status': 'new',
                        'required': request.category_id.manager_approval == 'required',
                        'sequence': 9,
                    }))
                    existing_user_ids.add(mgr_uid)

            for app in location_approver_vals:
                uid = app['user_id']
                if uid not in existing_user_ids:
                    approver_id_vals.append(Command.create({
                        'user_id': uid,
                        'status': 'new',
                        'required': app.get('required', True),
                        'sequence': app.get('sequence', 10),
                    }))
                    existing_user_ids.add(uid)

            request.update({'approver_ids': approver_id_vals})
