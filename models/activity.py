# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class FarmActivity(models.Model):
    _name = 'farm.activity'
    _description = 'Farm Activity'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(
        string='Activity Name',
        required=True,
        tracking=True,
        help='Name of the agricultural activity, e.g. Soil Preparation, Cultivating, Harvesting, Irrigation...',
    )
    code = fields.Char(
        string='Activity ID / Code',
        required=True,
        copy=False,
        tracking=True,
        help='Short unique identifier for the activity, e.g. SP, CULT, HARV...',
    )
    active = fields.Boolean(default=True, tracking=True)
    color = fields.Integer(string='Color Index')

    type = fields.Selection([
        ('piece_rate', 'Piece Rate'),
        ('fixed', 'Fixed (Daily Rate)'),
    ], string='Type', default='piece_rate', required=True, tracking=True)

    category = fields.Selection([
        ('land_prep', 'Land Preparation'),
        ('planting', 'Planting & Sowing'),
        ('crop_care', 'Crop Care & Fertilization'),
        ('irrigation', 'Irrigation'),
        ('harvest', 'Harvesting'),
        ('maintenance', 'Maintenance & Other'),
    ], string='Category', default='land_prep', tracking=True)

    uom_name = fields.Char(
        string='Unit of Measure',
        default='Birr/Kg',
        help='Measurement unit, e.g. Birr/Kg for piece rate, Birr/Day for fixed rate...',
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    description = fields.Html(string='Activity Description & Standard Operating Procedures')

    # Relational link to Farm Norms Table
    farm_norm_ids = fields.One2many(
        'farm.activity.norm',
        'activity_id',
        string='Farm Norms',
        copy=True,
    )
    farm_norm_count = fields.Integer(
        string='Configured Farms Count',
        compute='_compute_farm_norm_count',
    )

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'The Activity ID / Code must be unique per company!'),
    ]

    @api.onchange('type')
    def _onchange_type(self):
        if self.type == 'fixed' and (not self.uom_name or self.uom_name == 'Birr/Kg'):
            self.uom_name = 'Birr/Day'
        elif self.type == 'piece_rate' and (not self.uom_name or self.uom_name == 'Birr/Day'):
            self.uom_name = 'Birr/Kg'

    @api.depends('farm_norm_ids')
    def _compute_farm_norm_count(self):
        for act in self:
            act.farm_norm_count = len(act.farm_norm_ids)

    def init(self):
        super().init()
        try:
            # 1. Ensure standard Fixed Activity 'DAILY' exists
            self.env.cr.execute("SELECT id FROM farm_activity WHERE code = 'DAILY' LIMIT 1;")
            row = self.env.cr.fetchone()
            daily_act_id = row[0] if row else None

            if not daily_act_id:
                self.env.cr.execute("""
                    INSERT INTO farm_activity (
                        name, code, type, category, uom_name, active, company_id, create_date, write_date, create_uid, write_uid
                    ) VALUES (
                        'Daily Labor / Attendance', 'DAILY', 'fixed', 'maintenance', 'Birr/Day', TRUE, 1, NOW(), NOW(), 1, 1
                    ) RETURNING id;
                """)
                daily_act_id = self.env.cr.fetchone()[0]

            # 2. If farm_temporary_rate table exists, migrate rates to farm_activity_norm
            self.env.cr.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'farm_temporary_rate'
                );
            """)
            has_temp_table = self.env.cr.fetchone()[0]
            if has_temp_table and daily_act_id:
                self.env.cr.execute("""
                    INSERT INTO farm_activity_norm (
                        activity_id, farm_id, norm_value, create_date, write_date, create_uid, write_uid
                    )
                    SELECT 
                        %s, farm_id, full_day_rate, NOW(), NOW(), 1, 1
                    FROM farm_temporary_rate
                    WHERE farm_id IS NOT NULL AND full_day_rate > 0
                    ON CONFLICT (activity_id, farm_id) DO UPDATE
                    SET norm_value = EXCLUDED.norm_value;
                """, (daily_act_id,))

            # 3. For any existing work entries without activity_id, assign daily_act_id
            if daily_act_id:
                self.env.cr.execute("""
                    UPDATE farm_work_entry
                    SET activity_id = %s,
                        entry_type = 'fixed'
                    WHERE activity_id IS NULL;
                """, (daily_act_id,))
        except Exception:
            pass


class FarmActivityNorm(models.Model):
    _name = 'farm.activity.norm'
    _description = 'Farm Activity Norm'
    _order = 'farm_id asc'

    activity_id = fields.Many2one(
        'farm.activity',
        string='Activity',
        required=True,
        ondelete='cascade',
    )
    farm_id = fields.Many2one(
        'farm.farm',
        string='Farm',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='farm_id.company_id',
        store=True,
        readonly=True,
    )
    norm_value = fields.Float(
        string='Standard Norm',
        required=True,
        digits=(16, 2),
        help='The standard target / productivity norm value for this activity at this specific farm (e.g. 6.0, 7.5).',
    )
    activity_type = fields.Selection(
        related='activity_id.type',
        string='Activity Type',
        readonly=True,
    )
    uom_name = fields.Char(
        string='Unit',
        related='activity_id.uom_name',
        readonly=True,
    )

    _sql_constraints = [
        ('activity_farm_uniq', 'unique(activity_id, farm_id)', 'A norm for this activity on this farm is already configured!'),
    ]
