# -*- coding: utf-8 -*-
import json
import base64
import logging
import datetime
import odoo
from odoo import http, api, SUPERUSER_ID, fields, _
from odoo.http import request
import odoo.modules.registry

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

        auth_header = request.httprequest.headers.get('Authorization')
        uid = None

        if auth_header:
            try:
                auth_parts = auth_header.split(' ', 1)
                if len(auth_parts) == 2:
                    auth_type, auth_val = auth_parts
                    auth_type = auth_type.lower()

                    if auth_type == 'bearer':
                        token = auth_val.strip()
                        with registry.cursor() as check_cr:
                            check_env = api.Environment(check_cr, SUPERUSER_ID, {})
                            uid = check_env['res.users.apikeys']._check_credentials(scope='rpc', key=token)

                    elif auth_type == 'basic':
                        decoded = base64.b64decode(auth_val).decode('utf-8')
                        username, password = decoded.split(':', 1) if ':' in decoded else (decoded, '')
                        with registry.cursor() as check_cr:
                            check_env = api.Environment(check_cr, SUPERUSER_ID, {})
                            uid = check_env['res.users.apikeys']._check_credentials(scope='rpc', key=password)
                            if not uid:
                                uid = check_env['res.users.apikeys']._check_credentials(scope='rpc', key=username)
                            if not uid:
                                try:
                                    uid = check_env['res.users'].authenticate(
                                        db_name, username, password, {'interactive': False}
                                    )
                                except Exception:
                                    pass
            except Exception as e:
                _logger.error("Authentication error in REST API: %s", str(e))

        # If no specific user authenticated, default to SUPERUSER_ID for API operations
        if not uid:
            uid = SUPERUSER_ID

        env = api.Environment(cr, uid, {})
        return env, cr, db_name

    def _json_response(self, data, status=200):
        """Helper to return formatted JSON responses with CORS headers."""
        return request.make_response(
            json.dumps(data, default=str),
            headers=[
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Headers', 'Authorization, Content-Type, Accept, X-Odoo-Db, X-Database'),
                ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            ],
            status=status
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
                "message": "Database not found or could not be loaded."
            }, status=500)

        try:
            farm_code = request.httprequest.args.get('farm_code') or kwargs.get('farm_code')
            employee_type = request.httprequest.args.get('employee_type') or kwargs.get('employee_type')
            search_query = request.httprequest.args.get('search') or kwargs.get('search')

            domain = []
            if farm_code:
                domain.append('|')
                domain.append(('current_farm_id.code', '=ilike', farm_code.strip()))
                domain.append(('initial_farm_id.code', '=ilike', farm_code.strip()))

            if employee_type:
                domain.append(('farm_employee_type', '=', employee_type.strip().lower()))

            if search_query:
                domain.append('|')
                domain.append(('name', 'ilike', search_query.strip()))
                domain.append(('fms_employee_id', 'ilike', search_query.strip()))

            employees = env['hr.employee'].search(domain, order='id asc')

            data = []
            for emp in employees:
                farm = emp.current_farm_id or emp.initial_farm_id
                sub_farm = emp.current_sub_farm_id or emp.initial_sub_farm_id
                sub_unit = emp.current_sub_unit_id or emp.initial_sub_unit_id
                block = emp.current_block_id or emp.initial_block_id

                classification_labels = dict(emp._fields['farm_employee_type'].selection) if 'farm_employee_type' in emp._fields else {}
                class_label = classification_labels.get(emp.farm_employee_type, emp.farm_employee_type or 'Temporary')

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
        if request.httprequest.content_type == 'application/json':
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

        emp_identifier = payload.get('employee_id')
        activity_identifier = payload.get('activity_id')
        score_val = payload.get('score', payload.get('score_value'))
        date_str = payload.get('date')
        notes = payload.get('notes', '')

        # Validations
        if not emp_identifier:
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'employee_id' (e.g. 'FM01T0001')."
            }, status=400)

        if not activity_identifier:
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'activity_id' (e.g. 'SP')."
            }, status=400)

        if score_val is None:
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'score'."
            }, status=400)

        try:
            score_float = float(score_val)
            if score_float <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": "Field 'score' must be a positive number."
            }, status=400)

        work_date = fields.Date.context_today(env['farm.work.entry'])
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

            # 2. Resolve Activity
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

            # 3. Resolve Location
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
                    "message": "No farm found in the system to calculate activity norm."
                }, status=400)

            # 4. Resolve Activity Norm Rate
            norm_rec = env['farm.activity.norm'].search([
                ('activity_id', '=', activity.id),
                ('farm_id', '=', farm.id)
            ], limit=1)

            norm_rate = norm_rec.norm_value if norm_rec else 0.0
            total_payment = round(score_float * norm_rate, 2)

            # 5. Create Work Entry
            vals = {
                'date': work_date,
                'employee_id': emp.id,
                'farm_id': farm.id,
                'sub_farm_id': sub_farm.id if sub_farm else False,
                'sub_unit_id': sub_unit.id if sub_unit else False,
                'block_id': block.id if block else False,
                'activity_id': activity.id,
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
                    },
                    "calculation": {
                        "score": score_float,
                        "norm_rate": norm_rate,
                        "uom": activity.uom_name,
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
                for n in act.norm_ids:
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
                    "uom": act.uom_name,
                    "norms": norms
                })

            return self._json_response({
                "status": "success",
                "count": len(data),
                "data": data
            }, status=200)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, status=500)
        finally:
            if cr:
                cr.close()
