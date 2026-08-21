# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools import html_escape
from markupsafe import Markup


class FarmEmployeeTransfer(models.Model):
    _name = 'farm.employee.transfer'
    _description = 'Farm Employee Transfer & Assignment History'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'transfer_date desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='employee_id.company_id',
        store=True,
        readonly=True,
    )

    # Relational Hierarchy with dynamic chaining
    farm_id = fields.Many2one(
        'farm.farm',
        string='Farm',
        required=True,
        index=True,
        tracking=True,
    )
    sub_farm_id = fields.Many2one(
        'farm.sub.farm',
        string='Sub Farm',
        domain="[('farm_id', '=', farm_id)]",
        index=True,
        tracking=True,
    )
    sub_unit_id = fields.Many2one(
        'farm.sub.unit',
        string='Sub Unit',
        domain="[('sub_farm_id', '=', sub_farm_id)]",
        index=True,
        tracking=True,
    )
    block_id = fields.Many2one(
        'farm.block',
        string='Block (Optional)',
        domain="[('sub_unit_id', '=', sub_unit_id)]",
        tracking=True,
    )

    # Transfer Dates & Status
    transfer_date = fields.Date(
        string='Transfer Date',
        default=fields.Date.today,
        required=True,
        tracking=True,
        help='The date when the employee transferred into this location.',
    )
    moving_date = fields.Date(
        string='Moving Date',
        tracking=True,
        help='The date when the employee transferred out / moved to another location. Left empty while active.',
    )
    is_current = fields.Boolean(
        string='Is Active Assignment',
        compute='_compute_status',
        store=True,
    )
    status = fields.Selection([
        ('active', 'Active'),
        ('completed', 'Transferred / Past'),
    ], string='Status', compute='_compute_status', store=True, tracking=True)

    notes = fields.Char(string='Notes / Reason for Transfer', tracking=True)

    @api.depends('moving_date')
    def _compute_status(self):
        for record in self:
            if not record.moving_date:
                record.status = 'active'
                record.is_current = True
            else:
                record.status = 'completed'
                record.is_current = False

    @api.onchange('farm_id')
    def _onchange_farm_id(self):
        if self.sub_farm_id and self.sub_farm_id.farm_id != self.farm_id:
            self.sub_farm_id = False
            self.sub_unit_id = False
            self.block_id = False

    @api.onchange('sub_farm_id')
    def _onchange_sub_farm_id(self):
        if self.sub_farm_id:
            self.farm_id = self.sub_farm_id.farm_id
            if self.sub_unit_id and self.sub_unit_id.sub_farm_id != self.sub_farm_id:
                self.sub_unit_id = False
                self.block_id = False

    @api.onchange('sub_unit_id')
    def _onchange_sub_unit_id(self):
        if self.sub_unit_id:
            self.sub_farm_id = self.sub_unit_id.sub_farm_id
            self.farm_id = self.sub_unit_id.farm_id
            if self.block_id and self.block_id.sub_unit_id != self.sub_unit_id:
                self.block_id = False

    @api.onchange('block_id')
    def _onchange_block_id(self):
        if self.block_id:
            self.sub_unit_id = self.block_id.sub_unit_id
            self.sub_farm_id = self.block_id.sub_farm_id
            self.farm_id = self.block_id.farm_id

    @api.constrains('transfer_date', 'moving_date')
    def _check_dates(self):
        for record in self:
            if record.moving_date and record.transfer_date and record.moving_date < record.transfer_date:
                raise ValidationError(_("The Moving Date (%s) cannot be earlier than the Transfer Date (%s)!") % (
                    record.moving_date, record.transfer_date
                ))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            # Auto-close previous open transfer for this employee if a new transfer is registered
            if not record.moving_date:
                previous_transfers = self.search([
                    ('employee_id', '=', record.employee_id.id),
                    ('id', '!=', record.id),
                    ('moving_date', '=', False),
                    ('transfer_date', '<=', record.transfer_date),
                ])
                for prev in previous_transfers:
                    prev.moving_date = record.transfer_date
                    if prev.employee_id:
                        prev_unit = html_escape(prev.sub_unit_id.name or 'N/A')
                        t_date = html_escape(str(record.transfer_date or ''))
                        msg = Markup(
                            "<div>"
                            "<strong>🚪 Transfer Relocation Logged:</strong><br/>"
                            "Employee moved out of <strong>%s</strong> on %s due to new transfer."
                            "</div>"
                        ) % (prev_unit, t_date)
                        prev.employee_id.message_post(
                            body=msg,
                            subtype_xmlid='mail.mt_note',
                        )

            # Log Note in Employee's Chatter
            if record.employee_id:
                destination_parts = []
                if record.sub_unit_id:
                    destination_parts.append(f"Sub Unit: <strong>{html_escape(record.sub_unit_id.name)}</strong>")
                if record.sub_farm_id:
                    destination_parts.append(f"Sub Farm: <strong>{html_escape(record.sub_farm_id.name)}</strong>")
                if record.farm_id:
                    destination_parts.append(f"Farm: <strong>{html_escape(record.farm_id.name)}</strong>")
                if record.block_id:
                    destination_parts.append(f"Block: <strong>{html_escape(record.block_id.name)}</strong>")

                dest_html = " &gt; ".join(destination_parts) if destination_parts else "N/A"
                notes_html = f"<br/><strong>Reason / Notes:</strong> {html_escape(record.notes)}" if record.notes else ""
                moving_html = f"<br/><strong>Moving Date:</strong> {html_escape(str(record.moving_date))}" if record.moving_date else ""
                t_date_html = html_escape(str(record.transfer_date or ''))

                msg = Markup(
                    "<div>"
                    "<strong>🌿 New Farm Transfer Registered</strong><br/>"
                    "<strong>Destination:</strong> %s<br/>"
                    "<strong>Transfer Date:</strong> %s%s%s"
                    "</div>"
                ) % (Markup(dest_html), t_date_html, Markup(moving_html), Markup(notes_html))

                record.employee_id.message_post(
                    body=msg,
                    subtype_xmlid='mail.mt_note',
                )
        return records

    def write(self, vals):
        # Track previous values for logging
        old_data = {}
        if 'moving_date' in vals or 'sub_unit_id' in vals or 'farm_id' in vals:
            for record in self:
                old_data[record.id] = {
                    'moving_date': record.moving_date,
                    'sub_unit': record.sub_unit_id.name or 'N/A',
                    'employee': record.employee_id,
                }

        res = super().write(vals)

        for record in self:
            if record.id in old_data and record.employee_id:
                old = old_data[record.id]
                # If moving date was added or changed
                if 'moving_date' in vals and vals.get('moving_date') and old['moving_date'] != record.moving_date:
                    unit_name = html_escape(record.sub_unit_id.name or old['sub_unit'])
                    m_date = html_escape(str(record.moving_date or ''))
                    msg = Markup(
                        "<div>"
                        "<strong>🚪 Transfer Departure Updated:</strong><br/>"
                        "Moving Date for location <strong>%s</strong> set to <strong>%s</strong>."
                        "</div>"
                    ) % (unit_name, m_date)
                    record.employee_id.message_post(
                        body=msg,
                        subtype_xmlid='mail.mt_note',
                    )
                # If destination location was changed
                if 'sub_unit_id' in vals or 'farm_id' in vals:
                    unit_name = html_escape(record.sub_unit_id.name or 'N/A')
                    t_date = html_escape(str(record.transfer_date or ''))
                    msg = Markup(
                        "<div>"
                        "<strong>✏️ Transfer Record Modified:</strong><br/>"
                        "Destination updated to <strong>%s</strong> (Transfer Date: %s)."
                        "</div>"
                    ) % (unit_name, t_date)
                    record.employee_id.message_post(
                        body=msg,
                        subtype_xmlid='mail.mt_note',
                    )
        return res

    def unlink(self):
        # Log note before deleting
        for record in self:
            if record.employee_id:
                unit_name = html_escape(record.sub_unit_id.name or record.farm_id.name or 'N/A')
                t_date = html_escape(str(record.transfer_date or 'N/A'))
                msg = Markup(
                    "<div>"
                    "<strong>🗑️ Farm Transfer Record Deleted:</strong><br/>"
                    "Transfer entry for <strong>%s</strong> (Transfer Date: %s) was deleted."
                    "</div>"
                ) % (unit_name, t_date)
                record.employee_id.message_post(
                    body=msg,
                    subtype_xmlid='mail.mt_note',
                )
        return super().unlink()
