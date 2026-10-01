# -*- coding: utf-8 -*-
import base64
import csv
import io
import logging
import re

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    openpyxl = None

_logger = logging.getLogger(__name__)

LEVEL_KEYS = ['base', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', 'max']

LEVEL_COLUMN_LABELS = [
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


def normalize_level_string(val):
    """Maps various level text inputs (English/Amharic/Numbers) to canonical LEVEL_KEYS."""
    if val is None:
        return None
    s = str(val).strip().lower()

    # 1. Base / Starting checks (contains 'base', 'መነሻ', or 'start')
    if 'base' in s or 'መነሻ' in s or 'start' in s:
        return 'base'

    # 2. Max / Ceiling checks (contains 'max', 'ጣሪያ', 'ceiling', or 'top')
    if 'max' in s or 'ጣሪያ' in s or 'ceiling' in s or 'top' in s:
        return 'max'

    # 3. Extract step/level numbers: "Step 1", "እርከን 1", "Level 1", "1"
    match = re.search(r'\d+', s)
    if match:
        num = int(match.group())
        if 1 <= num <= 12:
            return str(num)
        elif num == 0:
            return 'base'
        elif num == 13:
            return 'max'

    return None


def extract_grade_number(val):
    """Extracts integer grade number from a cell value (e.g. 1, 'Grade 1', 'ደረጃ 1')."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        try:
            return int(val)
        except (ValueError, TypeError):
            return None
    s = str(val).strip()
    match = re.search(r'\d+', s)
    if match:
        try:
            return int(match.group())
        except (ValueError, TypeError):
            return None
    return None


def parse_float_amount(val):
    """Cleans and converts raw cell text/numbers to a valid float."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(',', '').replace(' ', '').replace('ETB', '').replace('Birr', '').strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


class HrSalaryMatrixImportWizard(models.TransientModel):
    _name = 'hr.salary.matrix.import.wizard'
    _description = 'Import Salary Scale Wizard (Excel / CSV)'

    file = fields.Binary(
        string='Spreadsheet File',
        required=True,
        help='Upload an Excel file (.xlsx) or CSV file containing the salary matrix.',
    )
    filename = fields.Char(string='File Name')

    import_mode = fields.Selection([
        ('auto', 'Auto-Detect (2D Grid or Tabular List)'),
        ('grid', '2D Matrix Grid (Grades as rows, Steps as columns)'),
        ('tabular', 'Tabular List (Grade, Step/Level, Basic Wage)'),
    ], string='Import Mode / Format', default='auto', required=True)

    target_matrix = fields.Selection([
        ('existing', 'Update Current / Selected Salary Scale'),
        ('new', 'Create New Salary Scale'),
    ], string='Target Salary Scale', default='existing', required=True)

    matrix_id = fields.Many2one(
        'hr.salary.matrix',
        string='Target Salary Scale',
        help='Select which existing Salary Scale to update.',
    )

    new_matrix_name = fields.Char(
        string='New Scale Name',
    )
    new_matrix_type = fields.Selection([
        ('head_office', 'Head Office (ዋና መ/ቤት)'),
        ('cpw', 'CPW'),
        ('farm', 'Farm (የእርሻ ልማቶች)'),
        ('saudi_star', 'Saudi Star (ሳዑዲ ስታር)'),
        ('other', 'Other / Custom (ሌላ)'),
    ], string='Scale Category', default='head_office')

    new_effective_date = fields.Date(
        string='Effective Date',
        default=fields.Date.today,
    )

    sheet_name = fields.Char(
        string='Sheet to Import (Optional)',
        help='Name of the Excel sheet tab to read. If blank, auto-selects based on scale type or active sheet.',
    )

    template_format = fields.Selection([
        ('grid', '2D Matrix Grid Template (.xlsx)'),
        ('tabular', 'Tabular List Template (.xlsx)'),
    ], string='Template Format', default='grid', required=True)

    clear_existing_lines = fields.Boolean(
        string='Overwrite / Clear Existing Scale Lines',
        default=True,
        help='If checked, all previous lines for this scale will be replaced by the imported values.',
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
    ], default='draft')

    summary = fields.Html(
        string='Import Summary',
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Template Generation & Download
    # -------------------------------------------------------------------------
    def action_download_template(self):
        """Generates and downloads a beautifully styled Excel template (.xlsx)."""
        if not openpyxl:
            raise UserError(_("The 'openpyxl' Python library is required to generate Excel templates."))

        wb = openpyxl.Workbook()
        ws = wb.active

        # Styling constants
        navy_header_fill = PatternFill(start_color='1E3C72', end_color='1E3C72', fill_type='solid')
        sub_header_fill = PatternFill(start_color='2A5298', end_color='2A5298', fill_type='solid')
        header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        bold_font = Font(name='Calibri', size=11, bold=True)
        regular_font = Font(name='Calibri', size=11)
        zebra_fill = PatternFill(start_color='F8F9FA', end_color='F8F9FA', fill_type='solid')
        thin_border_side = Side(border_style='thin', color='DEE2E6')
        grid_border = Border(
            left=thin_border_side, right=thin_border_side,
            top=thin_border_side, bottom=thin_border_side
        )

        if self.template_format == 'grid':
            ws.title = 'Salary Scale Matrix'
            filename = 'salary_matrix_2d_grid_template.xlsx'

            # Headers
            headers = ['Grade / ደረጃ'] + [lbl for _, lbl in LEVEL_COLUMN_LABELS]
            ws.row_dimensions[1].height = 28
            for col_idx, h_text in enumerate(headers, start=1):
                cell = ws.cell(row=1, column=col_idx, value=h_text)
                cell.fill = navy_header_fill if col_idx == 1 else sub_header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
                cell.border = grid_border

            # Sample rows for Grades 1 to 22
            ws.column_dimensions['A'].width = 16
            for col_letter in [get_column_letter(i) for i in range(2, 16)]:
                ws.column_dimensions[col_letter].width = 13

            # Baseline reference numbers (Head Office baseline)
            from ..models.salary_matrix import HEAD_OFFICE_CPW_DATA
            for g in range(1, 23):
                row_idx = g + 1
                ws.row_dimensions[row_idx].height = 20
                grade_cell = ws.cell(row=row_idx, column=1, value=g)
                grade_cell.font = bold_font
                grade_cell.alignment = Alignment(horizontal='center', vertical='center')
                grade_cell.border = grid_border

                sample_vals = HEAD_OFFICE_CPW_DATA.get(g, [])
                for col_idx in range(2, 16):
                    val_idx = col_idx - 2
                    val = sample_vals[val_idx] if val_idx < len(sample_vals) else None
                    cell = ws.cell(row=row_idx, column=col_idx, value=val)
                    cell.font = regular_font
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                    cell.number_format = '#,##0.00'
                    cell.border = grid_border
                    if g % 2 == 0:
                        cell.fill = zebra_fill

        else:
            ws.title = 'Salary Scale Tabular'
            filename = 'salary_matrix_tabular_template.xlsx'

            headers = ['Grade (ደረጃ)', 'Step / Level (እርከን)', 'Basic Wage (መሰረታዊ ደመወዝ)']
            ws.row_dimensions[1].height = 28
            ws.column_dimensions['A'].width = 18
            ws.column_dimensions['B'].width = 22
            ws.column_dimensions['C'].width = 24

            for col_idx, h_text in enumerate(headers, start=1):
                cell = ws.cell(row=1, column=col_idx, value=h_text)
                cell.fill = navy_header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = grid_border

            # Sample rows for Grade 1 and Grade 2
            sample_rows = [
                (1, 'base', 6100.0),
                (1, '1', 7160.0),
                (1, '2', 7769.0),
                (1, '3', 8429.0),
                (1, 'max', 19060.0),
                (2, 'base', 7160.0),
                (2, '1', 7769.0),
                (2, '2', 8429.0),
                (2, 'max', 20680.0),
            ]
            for r_idx, (g, lvl, amt) in enumerate(sample_rows, start=2):
                ws.row_dimensions[r_idx].height = 20
                c1 = ws.cell(row=r_idx, column=1, value=g)
                c2 = ws.cell(row=r_idx, column=2, value=lvl)
                c3 = ws.cell(row=r_idx, column=3, value=amt)

                c1.alignment = Alignment(horizontal='center', vertical='center')
                c2.alignment = Alignment(horizontal='center', vertical='center')
                c3.alignment = Alignment(horizontal='right', vertical='center')
                c3.number_format = '#,##0.00'

                for c in [c1, c2, c3]:
                    c.border = grid_border
                    c.font = regular_font

        # Instructions Sheet
        ws_guide = wb.create_sheet(title='Instructions & Guide')
        ws_guide.column_dimensions['A'].width = 8
        ws_guide.column_dimensions['B'].width = 75
        ws_guide.cell(row=2, column=2, value='Salary Scale Import Instructions / የደመወዝ እስኬል አሞላል መመሪያ').font = Font(size=14, bold=True, color='1E3C72')
        instructions = [
            '1. In 2D Grid format, Column 1 contains Grade numbers (1, 2, 3... up to 22 or more).',
            '2. The top header columns represent Steps: Base (መነሻ), 1, 2, 3 ... 12, Max (ጣሪያ).',
            '3. In Tabular format, each row specifies: Grade, Step/Level (e.g. base, 1, 2, max), and Basic Wage in Birr.',
            '4. Both English and Amharic labels (መነሻ, እርከን 1, ጣሪያ) are automatically recognized.',
            '5. When imported, all associated employee contract grades and dropdowns are dynamically updated.',
            '6. You can create a new Salary Scale or update an existing one.',
        ]
        for idx, text in enumerate(instructions, start=4):
            ws_guide.cell(row=idx, column=2, value=text).font = regular_font

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        file_bytes = output.getvalue()

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(file_bytes),
            'res_model': self._name,
            'res_id': self.id,
            'type': 'binary',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # -------------------------------------------------------------------------
    # Import Execution Logic
    # -------------------------------------------------------------------------
    def action_import(self):
        """Parses the uploaded spreadsheet and creates/updates the salary scale."""
        self.ensure_one()
        if not self.file:
            raise UserError(_("Please select an Excel or CSV spreadsheet file to import."))

        if self.target_matrix == 'existing' and not self.matrix_id:
            raise UserError(_("Please select which Salary Scale to update."))

        if self.target_matrix == 'new' and not self.new_matrix_name:
            raise UserError(_("Please enter a name for the new Salary Scale."))

        decoded_data = base64.b64decode(self.file)
        m_type = self.matrix_id.matrix_type if self.target_matrix == 'existing' and self.matrix_id else self.new_matrix_type
        rows, loaded_sheet = self._read_rows_from_file(decoded_data, sheet_name=self.sheet_name, matrix_type=m_type)
        if not rows:
            raise UserError(_("The uploaded file contains no data or could not be read."))

        # Detect format
        mode = self.import_mode
        if mode == 'auto':
            mode = self._detect_import_mode(rows)

        # Parse rows into line dictionaries: [{'grade': int, 'level': str, 'amount': float}]
        if mode == 'grid':
            lines_data = self._parse_grid_format(rows)
        else:
            lines_data = self._parse_tabular_format(rows)

        if not lines_data:
            raise UserError(_(
                "No valid salary scale lines could be found in the uploaded file.\n"
                "Please verify that Grade numbers and valid Step/Level columns or rows exist."
            ))

        # Target matrix resolution
        if self.target_matrix == 'new':
            matrix = self.env['hr.salary.matrix'].create({
                'name': self.new_matrix_name,
                'matrix_type': self.new_matrix_type,
                'effective_date': self.new_effective_date or fields.Date.today(),
                'company_id': self.env.company.id,
                'notes': _("Imported from %s on %s") % (self.filename or 'file', fields.Date.today()),
            })
        else:
            matrix = self.matrix_id

        # Clear or replace lines
        if self.clear_existing_lines:
            matrix.line_ids.unlink()
        else:
            # Overwrite only matching (grade, level) pairs
            for l in lines_data:
                existing = matrix.line_ids.filtered(lambda x: x.grade == l['grade'] and x.level == l['level'])
                if existing:
                    existing.unlink()

        # Batch create lines
        matrix_lines = []
        for l in lines_data:
            matrix_lines.append({
                'matrix_id': matrix.id,
                'grade': l['grade'],
                'level': l['level'],
                'amount': l['amount'],
            })

        self.env['hr.salary.matrix.line'].create(matrix_lines)

        # Automatically synchronize grades into hr.salary.matrix.grade
        matrix.sync_grades_from_lines()

        # Statistics & Summary
        distinct_grades = sorted(list(set(l['grade'] for l in lines_data)))
        amounts = [l['amount'] for l in lines_data if l['amount'] > 0]
        min_wage = min(amounts) if amounts else 0.0
        max_wage = max(amounts) if amounts else 0.0

        summary_html = Markup(f"""
        <div class="alert alert-success shadow-sm mb-3">
            <h4 class="alert-heading mb-2"><i class="fa fa-check-circle me-2"></i>Salary Scale Successfully Imported!</h4>
            <p class="mb-2">Scale: <strong>{matrix.name}</strong> ({dict(matrix._fields['matrix_type'].selection).get(matrix.matrix_type)}) &nbsp;|&nbsp; Sheet: <strong>{loaded_sheet}</strong></p>
            <hr/>
            <div class="row text-center mt-3">
                <div class="col-4">
                    <div class="p-2 border rounded bg-white">
                        <div class="text-muted small">Total Grades</div>
                        <div class="fs-4 fw-bold text-primary">{len(distinct_grades)}</div>
                        <div class="small text-muted">Grades {min(distinct_grades)} to {max(distinct_grades)}</div>
                    </div>
                </div>
                <div class="col-4">
                    <div class="p-2 border rounded bg-white">
                        <div class="text-muted small">Scale Entries</div>
                        <div class="fs-4 fw-bold text-success">{len(matrix_lines)}</div>
                        <div class="small text-muted">Grade × Level Cells</div>
                    </div>
                </div>
                <div class="col-4">
                    <div class="p-2 border rounded bg-white">
                        <div class="text-muted small">Wage Range (Birr)</div>
                        <div class="fs-5 fw-bold text-dark">{min_wage:,.0f} - {max_wage:,.0f}</div>
                        <div class="small text-muted">Min to Max Scale Wage</div>
                    </div>
                </div>
            </div>
        </div>
        """)

        self.summary = summary_html
        self.state = 'done'

        return {
            'name': _('Import Summary - %s') % matrix.name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.salary.matrix.import.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_salary_matrix(self):
        """Redirects directly to the imported salary matrix record."""
        self.ensure_one()
        matrix = self.matrix_id if self.target_matrix == 'existing' else self.env['hr.salary.matrix'].search([
            ('name', '=', self.new_matrix_name),
            ('company_id', '=', self.env.company.id)
        ], limit=1, order='id desc')

        if not matrix:
            return {'type': 'ir.actions.act_window_close'}

        return {
            'name': matrix.name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.salary.matrix',
            'res_id': matrix.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # -------------------------------------------------------------------------
    # Parsing Helpers
    # -------------------------------------------------------------------------
    def _read_rows_from_file(self, data_bytes, sheet_name=None, matrix_type=None):
        """Reads rows from either Excel or CSV data with smart sheet resolution."""
        is_excel = False
        loaded_sheet_name = ""
        if openpyxl:
            try:
                wb = openpyxl.load_workbook(io.BytesIO(data_bytes), data_only=True)
                ws = None
                # 1. User specified sheet
                if sheet_name and sheet_name in wb.sheetnames:
                    ws = wb[sheet_name]
                # 2. Smart match based on target matrix_type
                elif matrix_type and len(wb.sheetnames) > 1:
                    m_type_lower = (matrix_type or '').lower()
                    for s_name in wb.sheetnames:
                        sn_lower = s_name.lower()
                        if m_type_lower == 'farm' and ('farm' in sn_lower or 'scale 2' in sn_lower or '21' in sn_lower):
                            ws = wb[s_name]
                            break
                        elif m_type_lower in ('head_office', 'cpw') and ('head' in sn_lower or 'scale 1' in sn_lower or '22' in sn_lower):
                            ws = wb[s_name]
                            break
                # 3. Fallback to first non-empty data sheet
                if ws is None:
                    for s_name in wb.sheetnames:
                        if 'note' not in s_name.lower() and wb[s_name].max_row and wb[s_name].max_row > 2:
                            ws = wb[s_name]
                            break
                    if ws is None:
                        ws = wb.active

                loaded_sheet_name = ws.title
                rows = []
                for r in ws.iter_rows(values_only=True):
                    if any(c is not None and str(c).strip() != '' for c in r):
                        rows.append(list(r))
                is_excel = True
                return rows, loaded_sheet_name
            except Exception as e:
                _logger.warning("openpyxl failed to read file: %s", e)
                is_excel = False

        if not is_excel:
            # Try CSV decoding
            for enc in ['utf-8-sig', 'utf-8', 'latin-1']:
                try:
                    text = data_bytes.decode(enc)
                    f = io.StringIO(text)
                    reader = csv.reader(f)
                    rows = [row for row in reader if any(c.strip() for c in row)]
                    if rows:
                        return rows, 'CSV'
                except UnicodeDecodeError:
                    continue

        return [], ''

    def _detect_import_mode(self, rows):
        """Auto-detects whether the sheet is a 2D Matrix Grid or Tabular List."""
        for r_idx in range(min(10, len(rows))):
            row = rows[r_idx]
            level_match_count = 0
            has_grade_col = False
            has_level_col = False
            has_amount_col = False

            for c in row:
                if c is None:
                    continue
                s = str(c).strip().lower()
                lvl = normalize_level_string(s)
                if lvl:
                    level_match_count += 1
                if 'grade' in s or 'ደረጃ' in s:
                    has_grade_col = True
                if 'level' in s or 'step' in s or 'እርከን' in s:
                    has_level_col = True
                if 'wage' in s or 'salary' in s or 'amount' in s or 'ደመወዝ' in s or 'ብር' in s:
                    has_amount_col = True

            # If 3 or more column headers match distinct levels -> 2D Grid
            if level_match_count >= 3:
                return 'grid'

            # If row has grade, level/step, and wage/amount headers -> Tabular List
            if has_grade_col and (has_level_col or has_amount_col):
                return 'tabular'

        # Fallback: check row length
        if len(rows) > 0 and len(rows[0]) >= 5:
            return 'grid'
        return 'tabular'

    def _parse_grid_format(self, rows):
        """Parses 2D Matrix Grid: rows are grades, columns are levels."""
        # Step 1: Find the header row that contains level designations
        header_row_idx = None
        col_to_level = {}
        grade_col_idx = 0

        for r_idx in range(min(15, len(rows))):
            row = rows[r_idx]
            matches = {}
            g_col = None
            for col_idx, cell in enumerate(row):
                if cell is None:
                    continue
                s_cell = str(cell).strip().lower()
                if 'grade' in s_cell or 'ደረጃ' in s_cell:
                    g_col = col_idx
                lvl = normalize_level_string(cell)
                if lvl:
                    matches[col_idx] = lvl

            if len(matches) >= 3:
                header_row_idx = r_idx
                col_to_level = matches
                if g_col is not None:
                    grade_col_idx = g_col
                else:
                    min_lvl_col = min(matches.keys())
                    grade_col_idx = max(0, min_lvl_col - 1)
                break

        if header_row_idx is None:
            # Fallback: assume row 0 has headers, mapping columns 1..14 to LEVEL_KEYS
            col_to_level = {i + 1: k for i, k in enumerate(LEVEL_KEYS)}
            header_row_idx = 0
            grade_col_idx = 0

        # Step 2: Iterate subsequent rows to extract Grade and amounts
        parsed_lines = []
        for r_idx in range(header_row_idx + 1, len(rows)):
            row = rows[r_idx]
            if not row or not any(row):
                continue

            # Extract Grade from identified grade column or first non-empty cell
            grade_val = None
            if grade_col_idx < len(row):
                g = extract_grade_number(row[grade_col_idx])
                if g and 1 <= g <= 60:
                    grade_val = g

            if not grade_val:
                for cell in row[:3]:
                    g = extract_grade_number(cell)
                    if g and 1 <= g <= 60:
                        grade_val = g
                        break

            if not grade_val:
                continue

            for col_idx, level_key in col_to_level.items():
                if col_idx < len(row):
                    raw_val = row[col_idx]
                    amt = parse_float_amount(raw_val)
                    if amt > 0:
                        parsed_lines.append({
                            'grade': grade_val,
                            'level': level_key,
                            'amount': amt,
                        })

        return parsed_lines

    def _parse_tabular_format(self, rows):
        """Parses Tabular List: rows contain Grade, Step/Level, and Basic Wage."""
        # Find header indices
        grade_col_idx = 0
        level_col_idx = 1
        amount_col_idx = 2
        header_row_idx = 0

        for r_idx in range(min(10, len(rows))):
            row = rows[r_idx]
            found = False
            for col_idx, cell in enumerate(row):
                if cell is None:
                    continue
                s = str(cell).strip().lower()
                if 'grade' in s or 'ደረጃ' in s:
                    grade_col_idx = col_idx
                    found = True
                elif 'level' in s or 'step' in s or 'እርከን' in s:
                    level_col_idx = col_idx
                    found = True
                elif 'wage' in s or 'salary' in s or 'amount' in s or 'ደመወዝ' in s or 'መጠን' in s:
                    amount_col_idx = col_idx
                    found = True
            if found:
                header_row_idx = r_idx
                break

        parsed_lines = []
        for r_idx in range(header_row_idx + 1, len(rows)):
            row = rows[r_idx]
            if not row or len(row) <= max(grade_col_idx, level_col_idx, amount_col_idx):
                continue

            grade_val = extract_grade_number(row[grade_col_idx])
            level_key = normalize_level_string(row[level_col_idx])
            amt = parse_float_amount(row[amount_col_idx])

            if grade_val and level_key and amt > 0:
                parsed_lines.append({
                    'grade': grade_val,
                    'level': level_key,
                    'amount': amt,
                })

        return parsed_lines
