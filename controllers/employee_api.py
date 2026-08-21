# -*- coding: utf-8 -*-
import json
import logging
import datetime
import werkzeug.wrappers
import odoo
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class EmployeeAPI(http.Controller):

    def _get_db(self):
        """Resolves target database dynamically from URL query param, header, session, odoo.conf, or active DB list."""
        # 1. URL Query Parameter: ?db=your_db_name
        db_name = request.httprequest.args.get('db') or request.params.get('db')
        # 2. HTTP Custom Header: X-Odoo-Db or X-Database
        if not db_name:
            db_name = request.httprequest.headers.get('X-Odoo-Db') or request.httprequest.headers.get('X-Database')
        # 3. Active Session DB
        if not db_name and getattr(request, 'session', None) and request.session.db:
            db_name = request.session.db
        # 4. Production odoo.conf setting (db_name / dbfilter)
        if not db_name and odoo.tools.config.get('db_name'):
            db_name = odoo.tools.config['db_name']
        # 5. Standard request DB if already resolved
        if not db_name and getattr(request, 'db', None):
            db_name = request.db
        # 6. Automatic discovery from PostgreSQL active databases
        if not db_name:
            try:
                dbs = http.db_list()
                if dbs:
                    db_name = dbs[0]
            except Exception:
                pass
        return db_name

    def _get_env_and_user(self):
        """Initializes database environment and authenticates user via API Key, Bearer, Basic, or Sudo."""
        db_name = self._get_db()
        if not db_name:
            return None, None, None

        try:
            registry = odoo.modules.registry.Registry(db_name)
            cr = registry.cursor()
        except Exception as e:
            _logger.error("Failed to connect to database '%s': %s", db_name, str(e))
            return None, None, None

        uid = odoo.SUPERUSER_ID

        # Try API Key / Bearer Auth
        auth_header = request.httprequest.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
            try:
                env_root = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
                checked_uid = env_root['res.users.apikeys']._check_credentials(scope='rpc', key=token)
                if checked_uid:
                    uid = checked_uid
            except Exception as e:
                _logger.warning("API key authentication check failed: %s", str(e))

        env = odoo.api.Environment(cr, uid, {})
        return env, cr, db_name

    def _json_response(self, data, status=200):
        """Helper to build standard HTTP JSON Response with CORS headers."""
        headers = [
            ('Content-Type', 'application/json; charset=utf-8'),
            ('Access-Control-Allow-Origin', '*'),
            ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
            ('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With, X-Odoo-Db, X-Database'),
        ]
        return werkzeug.wrappers.Response(
            json.dumps(data, default=str),
            status=status,
            headers=headers
        )

    # -------------------------------------------------------------------------
    # GET /api/employees & /odoo/api/employees & /api/fms/employees
    # -------------------------------------------------------------------------
    @http.route([
        '/api/employees',
        '/odoo/api/employees',
        '/api/fms/employees',
        '/odoo/api/fms/employees'
    ], type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_employees(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({
                "status": "error",
                "message": "Database not found or could not connect."
            }, status=500)

        try:
            emp_id = kwargs.get('id') or kwargs.get('employee_id')
            farm_code = kwargs.get('farm') or kwargs.get('farm_code')
            employee_type = kwargs.get('type') or kwargs.get('classification')

            domain = [('active', '=', True)]
            if emp_id:
                domain = ['|', ('fms_employee_id', '=ilike', f'%{emp_id}%'),
                               ('employee_code', '=ilike', f'%{emp_id}%')]
            if employee_type:
                domain.append(('farm_employee_type', '=', employee_type.lower()))

            employees = env['hr.employee'].search(domain, order='fms_employee_id asc, id asc')

            data = []
            for emp in employees:
                farm = emp.current_farm_id or emp.initial_farm_id
                sub_farm = emp.current_sub_farm_id or emp.initial_sub_farm_id
                sub_unit = emp.current_sub_unit_id or emp.initial_sub_unit_id
                block = emp.current_block_id or emp.initial_block_id

                if farm_code and farm and farm.code and farm.code.lower() != farm_code.lower():
                    continue

                classification_labels = dict(emp._fields['farm_employee_type'].selection) if 'farm_employee_type' in emp._fields else {}
                class_label = classification_labels.get(emp.farm_employee_type, emp.farm_employee_type or 'Temporary')

                # Only temporary workers get the temporary wage rate
                temp_rate = False
                is_temp_worker = (emp.farm_employee_type == 'temporary') or ('T' in (emp.fms_employee_id or '').upper())
                if farm and is_temp_worker:
                    temp_rate = env['farm.temporary.rate'].search([
                        ('farm_id', '=', farm.id),
                        ('active', '=', True)
                    ], limit=1)

                data.append({
                    "id": emp.id,
                    "employee_id": emp.fms_employee_id or emp.employee_code or "",
                    "name": emp.name,
                    "classification": class_label,
                    "classification_code": emp.farm_employee_type or "temporary",
                    "farm": {
                        "id": farm.id if farm else None,
                        "code": farm.code if farm else "",
                        "name": farm.name if farm else ""
                    } if farm else None,
                    "sub_farm": {
                        "id": sub_farm.id if sub_farm else None,
                        "code": sub_farm.code if sub_farm else "",
                        "name": sub_farm.name if sub_farm else ""
                    } if sub_farm else None,
                    "sub_unit": {
                        "id": sub_unit.id if sub_unit else None,
                        "code": sub_unit.code if sub_unit else "",
                        "name": sub_unit.name if sub_unit else ""
                    } if sub_unit else None,
                    "block": {
                        "id": block.id if block else None,
                        "code": block.code if block else "",
                        "name": block.name if block else ""
                    } if block else None,
                    "temporary_wage_rate": {
                        "full_day_rate": temp_rate.full_day_rate if temp_rate else None,
                        "half_day_rate": temp_rate.half_day_rate if temp_rate else None,
                        "uom": temp_rate.uom_name if temp_rate else "Birr/Day"
                    } if temp_rate else None,
                    "job_title": emp.job_title or (emp.job_id.name if emp.job_id else ""),
                    "department": emp.department_id.name if emp.department_id else "",
                    "work_phone": emp.work_phone or emp.mobile_phone or "",
                    "work_email": emp.work_email or "",
                    "total_work_entries": emp.work_entry_count,
                    "total_earned_amount": emp.total_earned_amount
                })

            return self._json_response({
                "status": "success",
                "database": db_name,
                "count": len(data),
                "data": data
            }, status=200)

        except Exception as e:
            _logger.error("Error retrieving employees in REST API: %s", str(e), exc_info=True)
            return self._json_response({
                "status": "error",
                "message": f"Server error: {str(e)}"
            }, status=500)
        finally:
            if cr:
                cr.close()

    # -------------------------------------------------------------------------
    # POST /api/work_entries & /odoo/api/work_entries & /api/fms/work_entries
    # -------------------------------------------------------------------------
    @http.route([
        '/api/work_entries',
        '/odoo/api/work_entries',
        '/api/fms/work_entries',
        '/odoo/api/fms/work_entries'
    ], type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def create_work_entry(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({
                "status": "error",
                "message": "Database not found."
            }, status=500)

        # Parse request body (JSON or form data)
        payload = {}
        if request.httprequest.content_type and 'application/json' in request.httprequest.content_type:
            try:
                raw_body = request.httprequest.data.decode('utf-8')
                payload = json.loads(raw_body) if raw_body else {}
            except Exception as e:
                if cr: cr.close()
                return self._json_response({
                    "status": "error",
                    "message": "Invalid JSON payload."
                }, status=400)
        else:
            payload = kwargs

        emp_identifier = payload.get('employee_id') or payload.get('emp_id')
        activity_identifier = payload.get('activity_id') or payload.get('activity_code')
        score_val = payload.get('score', payload.get('score_value'))
        date_str = payload.get('date')
        entry_type_req = payload.get('entry_type')
        duration_req = payload.get('work_duration') or payload.get('duration')
        notes = payload.get('notes', '')

        # Validations
        if not emp_identifier:
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'employee_id' (e.g. 'FM01T0001')."
            }, status=400)

        if score_val is None:
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'score' (e.g. 1.0 for Full Day, 0.5 for Half Day, or piece-rate score)."
            }, status=400)

        try:
            score_float = float(score_val)
            if score_float <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": "Field 'score' must be a positive number (e.g. 1.0, 0.5, 6.0)."
            }, status=400)

        work_date = fields.Date.today()
        if date_str:
            try:
                work_date = datetime.datetime.strptime(str(date_str).strip(), '%Y-%m-%d').date()
            except ValueError:
                if cr: cr.close()
                return self._json_response({
                    "status": "error",
                    "message": "Invalid date format. Expected YYYY-MM-DD."
                }, status=400)

        try:
            # 1. Resolve Employee
            emp = env['hr.employee'].search([
                '|', ('fms_employee_id', '=ilike', str(emp_identifier).strip()),
                     ('employee_code', '=ilike', str(emp_identifier).strip())
            ], limit=1)

            if not emp and str(emp_identifier).isdigit():
                emp = env['hr.employee'].browse(int(emp_identifier)).exists()

            if not emp:
                if cr: cr.close()
                return self._json_response({
                    "status": "error",
                    "message": f"Employee with ID '{emp_identifier}' not found in database '{db_name}'."
                }, status=404)

            emp_code = (emp.fms_employee_id or emp.employee_code or '').upper()
            is_temp_worker = (emp.farm_employee_type == 'temporary') and ('T' in emp_code if emp_code else True)

            # 2. Resolve Farm Location
            farm = emp.current_farm_id or emp.initial_farm_id
            sub_farm = emp.current_sub_farm_id or emp.initial_sub_farm_id
            sub_unit = emp.current_sub_unit_id or emp.initial_sub_unit_id
            block = emp.current_block_id or emp.initial_block_id

            if not farm:
                farm = env['farm.farm'].search([], limit=1)

            if not farm:
                if cr: cr.close()
                return self._json_response({
                    "status": "error",
                    "message": "No farm found in the system to calculate rates."
                }, status=400)

            # 3. Determine Entry Type & Enforce Restrictions
            is_temporary_rate = False
            if entry_type_req in ('temporary_rate', 'daily_rate', 'temporary'):
                is_temporary_rate = True
            elif not activity_identifier:
                # If no activity is passed, check if temporary worker
                if is_temp_worker:
                    is_temporary_rate = True
                else:
                    if cr: cr.close()
                    return self._json_response({
                        "status": "error",
                        "message": f"Work entries without an 'activity_id' (Temporary Worker Rates) are ONLY permitted for Temporary Workers whose ID contains 'T'. Employee '{emp.name}' (ID: {emp.fms_employee_id or emp.id}) is classified as '{emp.farm_employee_type}'. Please specify an 'activity_id' (e.g. 'SP', 'CULT', 'HARV')."
                    }, status=400)
            elif str(activity_identifier).upper() in ('TEMP', 'TEMPORARY', 'DAILY', 'ATTENDANCE'):
                is_temporary_rate = True

            # If temporary rate is requested for a non-temporary worker, REJECT
            if is_temporary_rate and not is_temp_worker:
                if cr: cr.close()
                return self._json_response({
                    "status": "error",
                    "message": f"Temporary Worker Daily Rate entries are ONLY permitted for Temporary Workers (IDs containing 'T'). Employee '{emp.name}' (ID: {emp.fms_employee_id or emp.id}) is classified as '{emp.farm_employee_type}'. Please submit a standard piece-rate work entry with 'activity_id'."
                }, status=400)

            activity = False
            norm_rate = 0.0
            total_payment = 0.0
            uom_name = 'Birr/Day'
            work_duration = 'full_day' if score_float == 1.0 else ('half_day' if score_float == 0.5 else 'custom')
            if duration_req:
                work_duration = 'half_day' if str(duration_req).lower() in ('half', 'half_day', '0.5') else 'full_day'

            if is_temporary_rate:
                entry_type = 'temporary_rate'
                # Look up temporary rate for farm
                temp_rate = env['farm.temporary.rate'].search([
                    ('farm_id', '=', farm.id),
                    ('active', '=', True)
                ], limit=1)

                if temp_rate:
                    if score_float == 0.5 or work_duration == 'half_day':
                        norm_rate = temp_rate.half_day_rate
                        total_payment = round(temp_rate.half_day_rate, 2)
                        uom_name = 'Birr/Half-Day'
                    elif score_float == 1.0 or work_duration == 'full_day':
                        norm_rate = temp_rate.full_day_rate
                        total_payment = round(temp_rate.full_day_rate, 2)
                        uom_name = 'Birr/Day'
                    else:
                        norm_rate = temp_rate.full_day_rate
                        total_payment = round(score_float * temp_rate.full_day_rate, 2)
                        uom_name = 'Birr/Day'
                else:
                    # Fallback to custom fixed wage passed in payload if any
                    fixed_wage = float(payload.get('wage', payload.get('rate', 0.0)))
                    norm_rate = fixed_wage
                    total_payment = round(score_float * fixed_wage, 2)

            else:
                entry_type = 'piece_rate'
                if not activity_identifier:
                    if cr: cr.close()
                    return self._json_response({
                        "status": "error",
                        "message": "Missing required field: 'activity_id' (e.g. 'SP', 'CULT', 'HARV') for piece-rate work entries."
                    }, status=400)

                activity = env['farm.activity'].search([
                    ('code', '=ilike', str(activity_identifier).strip())
                ], limit=1)

                if not activity and str(activity_identifier).isdigit():
                    activity = env['farm.activity'].browse(int(activity_identifier)).exists()

                if not activity:
                    if cr: cr.close()
                    return self._json_response({
                        "status": "error",
                        "message": f"Activity '{activity_identifier}' not found."
                    }, status=404)

                norm_rec = env['farm.activity.norm'].search([
                    ('activity_id', '=', activity.id),
                    ('farm_id', '=', farm.id)
                ], limit=1)

                norm_rate = norm_rec.norm_value if norm_rec else 0.0
                uom_name = activity.uom_name or 'Birr/Kg'
                total_payment = round(score_float * norm_rate, 2)

            # 4. Create Work Entry Record
            vals = {
                'date': work_date,
                'employee_id': emp.id,
                'entry_type': entry_type,
                'work_duration': work_duration,
                'farm_id': farm.id,
                'sub_farm_id': sub_farm.id if sub_farm else False,
                'sub_unit_id': sub_unit.id if sub_unit else False,
                'block_id': block.id if block else False,
                'activity_id': activity.id if activity else False,
                'norm_rate': norm_rate,
                'score_value': score_float,
                'total_amount': total_payment,
                'notes': str(notes).strip() if notes else "Submitted via FMS REST API",
                'state': 'confirmed',
            }

            work_entry = env['farm.work.entry'].create(vals)
            cr.commit()

            return self._json_response({
                "status": "success",
                "message": "Work entry recorded successfully.",
                "data": {
                    "id": work_entry.id,
                    "reference": work_entry.name,
                    "date": str(work_entry.date),
                    "payment_type": "Temporary Worker Daily Rate" if entry_type == 'temporary_rate' else "Activity Piece Rate (Norm)",
                    "employee": {
                        "id": emp.id,
                        "employee_id": emp.fms_employee_id or emp.employee_code,
                        "name": emp.name,
                        "classification": emp.farm_employee_type
                    },
                    "location": {
                        "farm_id": farm.id,
                        "farm_code": farm.code,
                        "farm_name": farm.name,
                        "sub_farm_name": sub_farm.name if sub_farm else None,
                        "sub_unit_name": sub_unit.name if sub_unit else None,
                        "block_name": block.name if block else None
                    },
                    "activity": {
                        "id": activity.id,
                        "code": activity.code,
                        "name": activity.name
                    } if activity else None,
                    "calculation": {
                        "score_or_days": score_float,
                        "duration": work_duration,
                        "applied_rate": norm_rate,
                        "uom": uom_name,
                        "total_payment_birr": total_payment
                    },
                    "state": work_entry.state
                }
            }, status=201)

        except Exception as e:
            if cr: cr.rollback()
            _logger.error("Error creating work entry in REST API: %s", str(e), exc_info=True)
            return self._json_response({
                "status": "error",
                "message": f"Failed to record work entry: {str(e)}"
            }, status=500)
        finally:
            if cr:
                cr.close()

    # -------------------------------------------------------------------------
    # GET /api/activities & /odoo/api/activities & /api/fms/activities
    # -------------------------------------------------------------------------
    @http.route([
        '/api/activities',
        '/odoo/api/activities',
        '/api/fms/activities',
        '/odoo/api/fms/activities'
    ], type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_activities(self, farm_code=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found."}, status=500)

        try:
            activities = env['farm.activity'].search([], order='code asc')
            data = []
            for act in activities:
                norms = []
                for n in act.farm_norm_ids:
                    if not farm_code or (n.farm_id.code and n.farm_id.code.lower() == farm_code.lower()):
                        norms.append({
                            "farm_id": n.farm_id.id,
                            "farm_code": n.farm_id.code,
                            "farm_name": n.farm_id.name,
                            "norm_value": n.norm_value,
                            "uom": n.uom_name
                        })
                data.append({
                    "id": act.id,
                    "code": act.code,
                    "name": act.name,
                    "category": act.category,
                    "uom_name": act.uom_name,
                    "norms": norms
                })

            return self._json_response({
                "status": "success",
                "database": db_name,
                "count": len(data),
                "data": data
            }, status=200)

        except Exception as e:
            _logger.error("Error retrieving activities in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Server error: {str(e)}"}, status=500)
        finally:
            if cr:
                cr.close()

    # -------------------------------------------------------------------------
    # GET /api/temporary_rates & /odoo/api/temporary_rates & /api/fms/temporary_rates
    # -------------------------------------------------------------------------
    @http.route([
        '/api/temporary_rates',
        '/odoo/api/temporary_rates',
        '/api/fms/temporary_rates',
        '/odoo/api/fms/temporary_rates'
    ], type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_temporary_rates(self, farm_code=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found."}, status=500)

        try:
            domain = [('active', '=', True)]
            rates = env['farm.temporary.rate'].search(domain, order='farm_id asc')
            data = []
            for r in rates:
                if farm_code and r.farm_id.code and r.farm_id.code.lower() != farm_code.lower():
                    continue
                data.append({
                    "id": r.id,
                    "farm": {
                        "id": r.farm_id.id,
                        "code": r.farm_id.code or "",
                        "name": r.farm_id.name
                    },
                    "full_day_rate": r.full_day_rate,
                    "half_day_rate": r.half_day_rate,
                    "uom": r.uom_name or "Birr/Day",
                    "remarks": r.notes or ""
                })

            return self._json_response({
                "status": "success",
                "database": db_name,
                "count": len(data),
                "data": data
            }, status=200)

        except Exception as e:
            _logger.error("Error retrieving temporary rates in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Server error: {str(e)}"}, status=500)
        finally:
            if cr:
                cr.close()
