# -*- coding: utf-8 -*-
import base64
import csv
import io
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import openpyxl
except ImportError:
    openpyxl = None


def _clean_str(val):
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val)).strip()
    return str(val).strip()


def _parse_float(val):
    if val is None or val == '':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(',', '').replace(' ', '').strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _parse_int(val):
    if val is None or val == '':
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).replace(',', '').replace(' ', '').strip()
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _parse_bool(val, default=False):
    if val is None or val == '':
        return default
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ('true', '1', 'yes', 'y', 't')


def _normalize_col(name):
    if not name:
        return ""
    clean = str(name).strip().lower()
    clean = clean.replace('/', '_').replace('(', '').replace(')', '').replace(' ', '_').replace('-', '_')
    while '__' in clean:
        clean = clean.replace('__', '_')
    return clean


class FarmDataImportWizard(models.TransientModel):
    _name = 'farm.data.import.wizard'
    _description = 'Farm & Activity Data Import Wizard'

    import_type = fields.Selection([
        ('land_structure', 'Farms, Sub Farms, Sub Units / Hudads & Blocks'),
        ('activities', 'Farm Activities & Operations'),
    ], string='Import Type', required=True, default='land_structure')

    data_file = fields.Binary(
        string='Spreadsheet File (.xlsx, .csv)',
        help='Upload an Excel file (.xlsx) or CSV file exported from Excel.',
    )
    filename = fields.Char(string='Filename')

    data_text = fields.Text(
        string='Or Paste Spreadsheet Data (TSV / CSV)',
        help='Alternatively, copy rows directly from Excel and paste here (Tab or Comma separated).',
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    summary = fields.Html(string='Import Summary', readonly=True)

    def _read_rows(self):
        """Reads rows from either data_file (Excel/CSV) or data_text (pasted text). Returns list of dicts."""
        rows = []

        if self.data_file:
            content = base64.b64decode(self.data_file)
            fn = (self.filename or '').lower()

            if fn.endswith('.xlsx') or fn.endswith('.xls'):
                if not openpyxl:
                    raise UserError(_("The openpyxl library is required to read Excel files. Please paste as text or install openpyxl."))
                wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
                sheet = wb.active
                header = []
                for idx, row in enumerate(sheet.iter_rows(values_only=True)):
                    if not row or all(v is None for v in row):
                        continue
                    if not header:
                        header = [_normalize_col(c) for c in row]
                        continue
                    row_dict = {}
                    for col_idx, col_name in enumerate(header):
                        if col_name and col_idx < len(row):
                            row_dict[col_name] = row[col_idx]
                    if any(v is not None and v != '' for v in row_dict.values()):
                        rows.append(row_dict)
                return rows

            # Otherwise treat data_file as text/CSV
            try:
                text_content = content.decode('utf-8-sig')
            except UnicodeDecodeError:
                text_content = content.decode('latin-1')
        elif self.data_text:
            text_content = self.data_text.strip()
        else:
            raise UserError(_("Please upload a spreadsheet file or paste data into the text box."))

        # Parse text_content (could be tab-separated or comma-separated)
        first_line = text_content.split('\n')[0] if text_content else ''
        delimiter = '\t' if '\t' in first_line else ','
        reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)

        header = []
        for row in reader:
            if not row or all(not v.strip() for v in row):
                continue
            if not header:
                header = [_normalize_col(c) for c in row]
                continue
            row_dict = {}
            for col_idx, col_name in enumerate(header):
                if col_name and col_idx < len(row):
                    row_dict[col_name] = row[col_idx]
            if any(v is not None and v != '' for v in row_dict.values()):
                rows.append(row_dict)

        return rows

    def action_import(self):
        self.ensure_one()
        rows = self._read_rows()
        if not rows:
            raise UserError(_("No valid data rows found in the uploaded file or pasted text."))

        if self.import_type == 'land_structure':
            return self._import_land_structure(rows)
        else:
            return self._import_activities(rows)

    def _import_land_structure(self, rows):
        """Imports Farms, Sub Farms, Sub Units / Hudads, and Blocks with agronomic fields."""
        FarmObj = self.env['farm.farm']
        SubFarmObj = self.env['farm.sub.farm']
        SubUnitObj = self.env['farm.sub.unit']
        BlockObj = self.env['farm.block']

        created_farms = set()
        created_sub_farms = set()
        created_sub_units = set()
        created_blocks = 0
        updated_blocks = 0

        for row in rows:
            # 1. Farm
            # Expected raw: 1, 2, 3, 4 or Gomma2 (1)...
            raw_farm = _clean_str(row.get('farm_name') or row.get('farm') or '')
            if not raw_farm:
                continue

            # Standardize farm name to 'Gomma2 (1)', 'Gomma2 (2)' etc.
            if raw_farm.isdigit():
                farm_name = f"Gomma2 ({raw_farm})"
            elif raw_farm.startswith('Gomma2'):
                farm_name = raw_farm
            else:
                # If e.g. "1.0"
                try:
                    f_int = int(float(raw_farm))
                    farm_name = f"Gomma2 ({f_int})"
                except Exception:
                    farm_name = f"Gomma2 ({raw_farm})"

            farm = FarmObj.search([
                ('name', '=', farm_name),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            if not farm:
                farm = FarmObj.create({
                    'name': farm_name,
                    'company_id': self.company_id.id,
                })
                created_farms.add(farm_name)

            # 2. Sub Farm
            # Expected raw: 1, 2, Sub Farm 1...
            raw_sub_farm = _clean_str(row.get('sub_farm') or row.get('subfarm') or '1')
            if raw_sub_farm.isdigit():
                sub_farm_name = f"Sub Farm {raw_sub_farm}"
            elif not raw_sub_farm:
                sub_farm_name = "Sub Farm 1"
            elif raw_sub_farm.lower().startswith('sub'):
                sub_farm_name = raw_sub_farm
            else:
                sub_farm_name = f"Sub Farm {raw_sub_farm}"

            sub_farm = SubFarmObj.search([
                ('farm_id', '=', farm.id),
                ('name', '=', sub_farm_name),
            ], limit=1)
            if not sub_farm:
                sub_farm = SubFarmObj.create({
                    'name': sub_farm_name,
                    'farm_id': farm.id,
                })
                created_sub_farms.add(f"{farm_name} -> {sub_farm_name}")

            # 3. Sub Unit / Hudad
            # Expected raw: 1.1, 1.2, 2.1...
            raw_hudad = _clean_str(row.get('hudad') or row.get('sub_unit') or row.get('subunit') or '')
            if not raw_hudad:
                raw_hudad = "1.1"

            sub_unit_name = f"Hudad {raw_hudad}" if not raw_hudad.lower().startswith('hudad') else raw_hudad

            sub_unit = SubUnitObj.search([
                ('sub_farm_id', '=', sub_farm.id),
                '|', ('name', '=', sub_unit_name), ('hudad_number', '=', raw_hudad),
            ], limit=1)
            if not sub_unit:
                sub_unit = SubUnitObj.create({
                    'name': sub_unit_name,
                    'hudad_number': raw_hudad,
                    'sub_farm_id': sub_farm.id,
                })
                created_sub_units.add(f"{farm_name} -> {sub_farm_name} -> {sub_unit_name}")
            elif not sub_unit.hudad_number:
                sub_unit.hudad_number = raw_hudad

            # 4. Block
            # Expected raw: G1, G3, G5, G9, G10...
            raw_block = _clean_str(row.get('block_name') or row.get('block') or '')
            if not raw_block:
                continue

            crop_name = _clean_str(row.get('crop_name') or '')
            size_ha = _parse_float(row.get('size_ha') or row.get('size') or row.get('area') or 0.0)
            net_area = _parse_float(row.get('net_area') or 0.0)
            plantation_year = _parse_int(row.get('plantation_year') or row.get('plantation__year') or 0)
            soil_type = _clean_str(row.get('soil_type') or '')
            variety = _clean_str(row.get('variety') or '')
            population = _parse_float(row.get('population') or 0.0)
            productivity_quarter = _clean_str(row.get('productivity_quarter') or '')
            stumping_year = _parse_int(row.get('stumping_year') or 0)
            uprooting_year = _parse_int(row.get('uprooting_year') or 0)

            block_vals = {
                'name': raw_block,
                'sub_unit_id': sub_unit.id,
                'crop_name': crop_name,
                'crop_type': crop_name,
                'size_ha': size_ha,
                'net_area': net_area,
                'area': size_ha or net_area,
                'plantation_year': plantation_year if plantation_year > 0 else False,
                'soil_type': soil_type,
                'variety': variety,
                'population': population,
                'productivity_quarter': productivity_quarter,
                'stumping_year': stumping_year if stumping_year > 0 else False,
                'uprooting_year': uprooting_year if uprooting_year > 0 else False,
                'status': 'active',
            }

            block = BlockObj.search([
                ('sub_unit_id', '=', sub_unit.id),
                ('name', '=', raw_block),
            ], limit=1)

            if block:
                block.write(block_vals)
                updated_blocks += 1
            else:
                BlockObj.create(block_vals)
                created_blocks += 1

        summary_html = f"""
        <div class="alert alert-success">
            <h4><i class="fa fa-check-circle me-2"></i> Land Structure Import Completed Successfully!</h4>
            <ul class="mb-0">
                <li><strong>Farms Created:</strong> {len(created_farms)}</li>
                <li><strong>Sub Farms Created:</strong> {len(created_sub_farms)}</li>
                <li><strong>Sub Units (Hudads) Created:</strong> {len(created_sub_units)}</li>
                <li><strong>Blocks Created:</strong> {created_blocks}</li>
                <li><strong>Blocks Updated:</strong> {updated_blocks}</li>
            </ul>
        </div>
        """
        self.summary = summary_html
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _import_activities(self, rows):
        """Imports Farm Activities & Operations with UoM, costs, hours, and auto-generated codes."""
        ActivityObj = self.env['farm.activity']
        created_acts = 0
        updated_acts = 0

        for row in rows:
            activity_name = _clean_str(row.get('activity_name') or row.get('name') or '')
            if not activity_name:
                continue

            crop_name = _clean_str(row.get('crop_name') or '')
            cost_category = _clean_str(row.get('cost_catagory') or row.get('cost_category') or '')
            main_activity = _clean_str(row.get('main_activity') or '')
            sub_activity = _clean_str(row.get('sub_activity') or '')
            uom = _clean_str(row.get('unit_measurement') or row.get('unitmeasurement') or row.get('unit') or row.get('uom') or 'Birr/Kg')
            standard_hours = _parse_float(row.get('standard_hours') or 0.0)
            required_cost = _parse_float(row.get('required_amount_cost') or row.get('required_cost') or row.get('cost') or 0.0)
            activity_type = _clean_str(row.get('activity_type') or '')
            requires_labor = _parse_bool(row.get('requires_labor'), default=True)
            requires_machine = _parse_bool(row.get('requires_machine'), default=False)

            # Determine piece_rate vs fixed
            is_fixed = 'day' in uom.lower() or 'fixed' in activity_type.lower()
            act_type = 'fixed' if is_fixed else 'piece_rate'

            # Determine category
            category = 'crop_care'
            m_lower = main_activity.lower()
            if 'prep' in m_lower or 'land' in m_lower or 'clearing' in m_lower:
                category = 'land_prep'
            elif 'plant' in m_lower or 'sowing' in m_lower:
                category = 'planting'
            elif 'irrigat' in m_lower or 'water' in m_lower:
                category = 'irrigation'
            elif 'harvest' in m_lower or 'pick' in m_lower:
                category = 'harvest'
            elif 'maint' in m_lower or 'protect' in m_lower or 'weed' in m_lower:
                category = 'crop_care'

            vals = {
                'name': activity_name,
                'crop_name': crop_name,
                'cost_category': cost_category,
                'main_activity': main_activity,
                'sub_activity': sub_activity,
                'uom_name': uom,
                'standard_hours': standard_hours,
                'required_cost': required_cost,
                'activity_type': activity_type,
                'requires_labor': requires_labor,
                'requires_machine': requires_machine,
                'type': act_type,
                'category': category,
                'company_id': self.company_id.id,
            }

            # Search by name (and optionally main_activity)
            domain = [
                ('name', '=', activity_name),
                ('company_id', '=', self.company_id.id),
            ]
            if main_activity:
                domain.append(('main_activity', '=', main_activity))

            activity = ActivityObj.search(domain, limit=1)
            if not activity:
                # Search by name only
                activity = ActivityObj.search([('name', '=', activity_name), ('company_id', '=', self.company_id.id)], limit=1)

            if activity:
                activity.write(vals)
                updated_acts += 1
            else:
                ActivityObj.create(vals)
                created_acts += 1

        summary_html = f"""
        <div class="alert alert-success">
            <h4><i class="fa fa-check-circle me-2"></i> Activities Import Completed Successfully!</h4>
            <ul class="mb-0">
                <li><strong>Activities Created:</strong> {created_acts}</li>
                <li><strong>Activities Updated:</strong> {updated_acts}</li>
            </ul>
        </div>
        """
        self.summary = summary_html
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
