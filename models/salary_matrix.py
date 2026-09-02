# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)

LEVEL_SELECTION = [
    ('base', 'Base (መነሻ)'),
    ('1', '1'),
    ('2', '2'),
    ('3', '3'),
    ('4', '4'),
    ('5', '5'),
    ('6', '6'),
    ('7', '7'),
    ('8', '8'),
    ('9', '9'),
    ('10', '10'),
    ('11', '11'),
    ('12', '12'),
    ('max', 'Max (ጣሪያ)'),
]

LEVEL_KEYS = ['base', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', 'max']

# 1. Head Office & CPW Standard Salary Scale Data (Meskerem 01, 2018 E.C.)
HEAD_OFFICE_CPW_DATA = {
    1: [6100, 7160, 7769, 8429, 9146, 9923, 10767, 11682, 12675, 13752, 14921, 16190, 17567, 19060],
    2: [7160, 7769, 8429, 9146, 9923, 10767, 11682, 12675, 13752, 14921, 16190, 17567, 19060, 20680],
    3: [7769, 8429, 9146, 9923, 10767, 11682, 12675, 13752, 14921, 16190, 17567, 19060, 20680, 22438],
    4: [8429, 9146, 9923, 10767, 11682, 12675, 13752, 14921, 16190, 17567, 19060, 20680, 22438, 24345],
    5: [9923, 10767, 11682, 12675, 13752, 14921, 16190, 17567, 19060, 20680, 22438, 24345, 26413, 28658],
    6: [11682, 12675, 13752, 14921, 16190, 17567, 19060, 20680, 22438, 24345, 26413, 28658, 31094, 33740],
    7: [12675, 13753, 14922, 16190, 17566, 19059, 20679, 22437, 24344, 26413, 28658, 31094, 33740, 36605],
    8: [14923, 16191, 17567, 19060, 20680, 22438, 24346, 26415, 28660, 31096, 33740, 36605, 39718, 43094],
    9: [16216, 17595, 19090, 20713, 22473, 24384, 26456, 28705, 31145, 33792, 36665, 39781, 43094, 46755],
    10: [17567, 19060, 20680, 22438, 24345, 26414, 28659, 31095, 33738, 36606, 39718, 43094, 46755, 50729],
    11: [19059, 20679, 22437, 24344, 26413, 28659, 31095, 33738, 36605, 39717, 43093, 46756, 50731, 55043],
    12: [22437, 24344, 26413, 28658, 31094, 33737, 36605, 39716, 43092, 46755, 50729, 55041, 59721, 64798],
    13: [26414, 28659, 31095, 33738, 36606, 39718, 43093, 46756, 50731, 55043, 59721, 64798, 70306, 76282],
    14: [33738, 36606, 39718, 43093, 46756, 50731, 55043, 59721, 64798, 70306, 76282, 82766, 89801, 97434],
    15: [43093, 46756, 50731, 55043, 59721, 64798, 70306, 76282, 82766, 89801, 97434, 105716, 114702, 124452],
    16: [46875, 50859, 55182, 59873, 64962, 70484, 76475, 82975, 90028, 97680, 105983, 114992, 124452, 135030],
    17: [59722, 64798, 70306, 76282, 82766, 89801, 97434, 105716, 114702, 124452, 135030, 146508, 158960, 172471],
    18: [70306, 76282, 82766, 89801, 97434, 105716, 114701, 124451, 135029, 146507, 158960, 172471, 187133, 203039],
    19: [97434, 105716, 114702, 124452, 135030, 146508, 158961, 172472, 187133, 203039, 220297, 239022, 259339, 281383],
    20: [105716, 114702, 124451, 135030, 146507, 158961, 172472, 187132, 203039, 220297, 239022, 259339, 281383, 305300],
    21: [124452, 135030, 146507, 158961, 172472, 187132, 203039, 220297, 239022, 259339, 281383, 305300, 331252, 359409],
    22: [146507, 158961, 172472, 187132, 203039, 220297, 239022, 259339, 281383, 305300, 331252, 359409, 388402, 423550],
}

# 2. Farms Standard Salary Scale Data (የእርሻ ልማቶች - Grades 1 to 21)
FARMS_DATA = {
    1: [6100, 6619, 7181, 7791, 8454, 9172, 9952, 10798, 11716, 12712, 13792, 14964, 16236, 17616],
    2: [6619, 7182, 7792, 8454, 9173, 9953, 10799, 11717, 12712, 13793, 14965, 16238, 17618, 19115],
    3: [7182, 7792, 8455, 9173, 9953, 10799, 11717, 12713, 13794, 14966, 16238, 17619, 19116, 20741],
    4: [7792, 8454, 9173, 9953, 10799, 11716, 12712, 13793, 14965, 16237, 17618, 19115, 20740, 22503],
    5: [8454, 9173, 9952, 10798, 11716, 12712, 13792, 14965, 16237, 17617, 19114, 20739, 22502, 24415],
    6: [9952, 10798, 11716, 12712, 13792, 14964, 16236, 17616, 19114, 20739, 22501, 24414, 26489, 28741],
    7: [10798, 11716, 12712, 13792, 14965, 16236, 17617, 19114, 20739, 22501, 24414, 26489, 28741, 31184],
    8: [12712, 13793, 14965, 16237, 17617, 19114, 20739, 22502, 24415, 26490, 28742, 31185, 33835, 36711],
    9: [16237, 17617, 19115, 20739, 22502, 24415, 26490, 28742, 31185, 33836, 36712, 39832, 43218, 46891],
    10: [17617, 19114, 20739, 22502, 24415, 26490, 28742, 31185, 33835, 36711, 39832, 43217, 46891, 50877],
    11: [19114, 20739, 22501, 24414, 26489, 28741, 31184, 33834, 36710, 39831, 43216, 46890, 50875, 55200],
    12: [20739, 22502, 24414, 26490, 28741, 31184, 33835, 36711, 39831, 43217, 46891, 50876, 55201, 59893],
    13: [24414, 26489, 28741, 31184, 33834, 36710, 39831, 43216, 46890, 50875, 55200, 59892, 64982, 70506],
    14: [31184, 33835, 36711, 39831, 43217, 46890, 50876, 55200, 59892, 64983, 70507, 76500, 83002, 90057],
    15: [43217, 46890, 50876, 55201, 59893, 64984, 70507, 76500, 83003, 90058, 97713, 106019, 115030, 124808],
    16: [46890, 50876, 55200, 59892, 64983, 70506, 76500, 83002, 90057, 97712, 106018, 115029, 124806, 135415],
    17: [50876, 55200, 59892, 64983, 70507, 76500, 83003, 90058, 97713, 106018, 115030, 124807, 135416, 146926],
    18: [59892, 64983, 70506, 76499, 83002, 90057, 97712, 106017, 115029, 124806, 135415, 146925, 159414, 172964],
    19: [70506, 76499, 83001, 90057, 97711, 106017, 115028, 124806, 135414, 146924, 159413, 172963, 187665, 203616],
    20: [76499, 83001, 90057, 97711, 106017, 115028, 124806, 135414, 146924, 159413, 172963, 187665, 203616, 220924],
    21: [106017, 115028, 124806, 135414, 146925, 159413, 172963, 187665, 203617, 220924, 239703, 260077, 282184, 306170],
}


class HrSalaryMatrix(models.Model):
    _name = 'hr.salary.matrix'
    _description = 'Employee Salary Matrix (Grade & Level Scale)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'matrix_type asc, id desc'

    name = fields.Char(
        string='Scale Title / Name',
        required=True,
        tracking=True,
        help='Descriptive title for this salary scale, e.g. "Head Office Salary Scale 2018 E.C."'
    )
    matrix_type = fields.Selection([
        ('head_office', 'Head Office (ዋና መ/ቤት)'),
        ('cpw', 'CPW'),
        ('farm', 'Farm Permanent (የእርሻ ልማቶች - ቋሚ)'),
    ], string='Scale Type / Category', required=True, tracking=True, default='head_office')

    effective_date = fields.Date(
        string='Effective Date',
        default=fields.Date.today,
        required=True,
        tracking=True,
        help='Effective date of this salary scale (e.g. Meskerem 01, 2018 E.C.)'
    )
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
    )
    line_ids = fields.One2many(
        'hr.salary.matrix.line',
        'matrix_id',
        string='Salary Matrix Lines',
        copy=True,
    )
    line_count = fields.Integer(
        string='Entries Count',
        compute='_compute_line_count',
    )
    matrix_html_table = fields.Html(
        string='Matrix 2D Grid',
        compute='_compute_matrix_html_table',
        sanitize=False,
    )
    notes = fields.Text(string='Notes / Reference')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends('line_ids', 'line_ids.amount', 'line_ids.grade', 'line_ids.level')
    def _compute_matrix_html_table(self):
        for rec in self:
            if not rec.line_ids:
                rec.matrix_html_table = Markup('<div class="alert alert-info">No scale entries defined yet. Click <strong>"Populate Standard Scale"</strong> above to auto-load values.</div>')
                continue

            grid = {}
            grades = set()
            for line in rec.line_ids:
                grades.add(line.grade)
                if line.grade not in grid:
                    grid[line.grade] = {}
                grid[line.grade][line.level] = line.amount

            sorted_grades = sorted(list(grades))

            headers_html = '<th style="background:#1e3c72;color:#fff;text-align:center;padding:10px;position:sticky;left:0;z-index:2;">ደረጃ (Grade)</th>'
            for l_key in LEVEL_KEYS:
                label = 'መነሻ' if l_key == 'base' else ('ጣሪያ' if l_key == 'max' else l_key)
                headers_html += f'<th style="background:#2a5298;color:#fff;text-align:center;padding:10px;font-size:12px;min-width:75px;">{label}</th>'

            rows_html = ''
            for g in sorted_grades:
                row_cells = f'<td style="background:#f8f9fa;font-weight:bold;text-align:center;position:sticky;left:0;z-index:1;border-right:2px solid #dee2e6;">{g}</td>'
                for l_key in LEVEL_KEYS:
                    val = grid.get(g, {}).get(l_key, 0.0)
                    formatted_val = f'{val:,.0f}' if val else '-'
                    row_cells += f'<td style="text-align:right;padding:6px 10px;font-family:Consolas, monospace;font-size:12px;">{formatted_val}</td>'
                rows_html += f'<tr>{row_cells}</tr>'

            table_html = f'''
            <div class="table-responsive shadow-sm rounded" style="max-height: 540px; overflow-y: auto; border: 1px solid #dee2e6;">
                <table class="table table-sm table-bordered table-striped table-hover mb-0" style="font-size: 13px;">
                    <thead style="position: sticky; top: 0; z-index: 3;">
                        <tr>{headers_html}</tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
            '''
            rec.matrix_html_table = Markup(table_html)

    def action_populate_standard_scale(self):
        """Populates or overwrites current matrix with standard baseline numbers."""
        for rec in self:
            data_map = FARMS_DATA if rec.matrix_type == 'farm' else HEAD_OFFICE_CPW_DATA
            # Clear existing lines
            rec.line_ids.unlink()

            lines_to_create = []
            for grade, values in data_map.items():
                for idx, level_key in enumerate(LEVEL_KEYS):
                    if idx < len(values):
                        lines_to_create.append({
                            'matrix_id': rec.id,
                            'grade': grade,
                            'level': level_key,
                            'amount': float(values[idx]),
                        })
            if lines_to_create:
                self.env['hr.salary.matrix.line'].create(lines_to_create)

        return True

    @api.model
    def get_matrix_wage(self, matrix_type, grade, level, company_id=None):
        """
        Looks up the basic wage amount for a given matrix type, grade and level.
        Returns float amount in Birr, or 0.0 if not found.
        """
        if not matrix_type or not grade or not level:
            return 0.0

        domain = [
            ('matrix_id.matrix_type', '=', matrix_type),
            ('matrix_id.active', '=', True),
            ('grade', '=', int(grade)),
            ('level', '=', str(level)),
        ]
        if company_id:
            domain.append(('matrix_id.company_id', '=', company_id))

        line = self.env['hr.salary.matrix.line'].search(domain, limit=1, order='matrix_id desc')
        return line.amount if line else 0.0

    @api.model
    def load_default_matrices(self):
        """Ensures all 3 standard matrices (Head Office, CPW, Farm Permanent) exist and are populated."""
        definitions = [
            ('head_office', 'Head Office Salary Scale (ዋና መ/ቤት) - 2018 E.C.', HEAD_OFFICE_CPW_DATA),
            ('cpw', 'CPW Salary Scale - 2018 E.C.', HEAD_OFFICE_CPW_DATA),
            ('farm', 'Farm Permanent Salary Scale (የእርሻ ልማቶች - ቋሚ) - 2018 E.C.', FARMS_DATA),
        ]

        company = self.env.company
        for m_type, name, data_map in definitions:
            matrix = self.search([('matrix_type', '=', m_type), ('company_id', '=', company.id)], limit=1)
            if not matrix:
                matrix = self.create({
                    'name': name,
                    'matrix_type': m_type,
                    'company_id': company.id,
                    'notes': 'Standard salary scale effective Meskerem 01, 2018 E.C. (Horizon Plantations PLC / MIDROC Investment Group)'
                })

            if not matrix.line_ids:
                lines_to_create = []
                for grade, values in data_map.items():
                    for idx, level_key in enumerate(LEVEL_KEYS):
                        if idx < len(values):
                            lines_to_create.append({
                                'matrix_id': matrix.id,
                                'grade': grade,
                                'level': level_key,
                                'amount': float(values[idx]),
                            })
                if lines_to_create:
                    self.env['hr.salary.matrix.line'].create(lines_to_create)
                    _logger.info("Initialized %d scale lines for salary matrix '%s'", len(lines_to_create), name)


class HrSalaryMatrixLine(models.Model):
    _name = 'hr.salary.matrix.line'
    _description = 'Salary Matrix Line (Grade x Level Amount)'
    _order = 'grade asc, sequence asc, id asc'

    matrix_id = fields.Many2one(
        'hr.salary.matrix',
        string='Salary Scale',
        required=True,
        ondelete='cascade',
        index=True,
    )
    matrix_type = fields.Selection(
        related='matrix_id.matrix_type',
        string='Scale Category',
        store=True,
        index=True,
    )
    grade = fields.Integer(
        string='Grade (ደረጃ)',
        required=True,
        index=True,
    )
    level = fields.Selection(
        LEVEL_SELECTION,
        string='Step / Level',
        required=True,
        index=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        compute='_compute_sequence',
        store=True,
        index=True,
        help='Calculated sorting order: Grade 1 Base, Grade 1 Steps 1..12, Grade 1 Max, Grade 2 Base...',
    )
    amount = fields.Float(
        string='Basic Wage (Birr)',
        required=True,
        digits=(16, 2),
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='matrix_id.currency_id',
    )

    @api.depends('grade', 'level')
    def _compute_sequence(self):
        level_order_map = {k: i for i, k in enumerate(LEVEL_KEYS)}
        for line in self:
            lvl_seq = level_order_map.get(line.level, 99) if line.level else 99
            grade_val = line.grade or 0
            line.sequence = (grade_val * 100) + lvl_seq

    @api.constrains('matrix_id', 'grade', 'level')
    def _check_unique_grade_level(self):
        for line in self:
            domain = [
                ('id', '!=', line.id),
                ('matrix_id', '=', line.matrix_id.id),
                ('grade', '=', line.grade),
                ('level', '=', line.level),
            ]
            if self.search_count(domain) > 0:
                raise ValidationError(_(
                    "Duplicate Entry: Grade %s and Level '%s' already exists in this Salary Scale!"
                ) % (line.grade, line.level))


class HrSalaryMatrixGrade(models.Model):
    _name = 'hr.salary.matrix.grade'
    _description = 'Salary Matrix Scale Grade'
    _order = 'matrix_type asc, grade asc'

    name = fields.Char(
        string='Grade',
        compute='_compute_name',
        store=True,
    )
    grade = fields.Integer(
        string='Grade Number',
        required=True,
    )
    matrix_type = fields.Selection([
        ('head_office', 'Head Office (ዋና መ/ቤት)'),
        ('cpw', 'CPW'),
        ('farm', 'Farm Permanent (የእርሻ ልማቶች - ቋሚ)'),
    ], string='Scale Type / Category', required=True, default='head_office')

    @api.depends('grade')
    def _compute_name(self):
        for rec in self:
            rec.name = f"Grade {rec.grade} (ደረጃ {rec.grade})"

    def init(self):
        super().init()
        for m_type, max_g in [('head_office', 22), ('cpw', 22), ('farm', 21)]:
            for g in range(1, max_g + 1):
                existing = self.search([('matrix_type', '=', m_type), ('grade', '=', g)], limit=1)
                if not existing:
                    self.create({
                        'matrix_type': m_type,
                        'grade': g,
                        'name': f"Grade {g} (ደረጃ {g})"
                    })

