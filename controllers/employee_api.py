# -*- coding: utf-8 -*-
import json
import logging
import datetime
import odoo
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class EmployeeAPI(http.Controller):

    def _get_db(self):
        """Resolves target database dynamically from URL query param, header, session, odoo.conf, or active DB list."""
        # 1. URL Query Parameter: ?db=your_db_name
        db_name = request.httprequest.args.get('db') or getattr(request, 'params', {}).get('db')
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
        body = json.dumps(data, default=str)
        response = request.make_response(
            body,
            headers=[
                ('Content-Type', 'application/json; charset=utf-8'),
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With, X-Odoo-Db, X-Database'),
            ],
        )
        response.status_code = status
        return response

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

                # Look up daily wage rate from active fixed farm activity
                temp_rate = False
                is_temp_worker = (emp.farm_employee_type == 'temporary') or ('T' in (emp.fms_employee_id or '').upper())
                if farm and is_temp_worker:
                    norm_rec = env['farm.activity.norm'].search([
                        ('activity_id.type', '=', 'fixed'),
                        ('farm_id', '=', farm.id),
                    ], limit=1)
                    if norm_rec:
                        temp_rate = {
                            "full_day_rate": norm_rec.norm_value,
                            "half_day_rate": round(norm_rec.norm_value / 2.0, 2),
                            "uom": norm_rec.uom_name or "Birr/Day",
                        }

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
                    "temporary_wage_rate": temp_rate,
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

        if not activity_identifier:
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'activity_code' (e.g. 'HARV01', 'DAILY'). Activity code is mandatory for all work entries."
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
                "message": "Field 'score' must be a positive number (e.g. 1.0, 0.5, 52.5)."
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
                return self._json_response({
                    "status": "error",
                    "message": f"Employee with ID '{emp_identifier}' not found in database '{db_name}'."
                }, status=404)

            # 2. Resolve Farm Location
            farm = emp.current_farm_id or emp.initial_farm_id
            sub_farm = emp.current_sub_farm_id or emp.initial_sub_farm_id
            sub_unit = emp.current_sub_unit_id or emp.initial_sub_unit_id
            block = emp.current_block_id or emp.initial_block_id

            if not farm:
                farm = env['farm.farm'].search([], limit=1)

            if not farm:
                return self._json_response({
                    "status": "error",
                    "message": "No farm found in the system to calculate rates."
                }, status=400)

            # 3. Resolve Activity
            activity = env['farm.activity'].search([
                ('code', '=ilike', str(activity_identifier).strip())
            ], limit=1)

            if not activity and str(activity_identifier).isdigit():
                activity = env['farm.activity'].browse(int(activity_identifier)).exists()

            if not activity:
                return self._json_response({
                    "status": "error",
                    "message": f"Activity with code '{activity_identifier}' not found. Use GET /api/activities to see all available activities and their codes."
                }, status=404)

            # 4. Check Activity Type (Fixed vs. Piece Rate) & Validate Score
            is_fixed = (activity.type == 'fixed')
            if is_fixed:
                if score_float not in (0.5, 1.0, 1.5, 2.0):
                    return self._json_response({
                        "status": "error",
                        "message": f"For fixed rate activity '{activity.code}' ({activity.name}), score must be strictly 0.5 (Half Day), 1.0 (Full Day), 1.5 (Day and a Half), or 2.0 (Two Days). Received: {score_float}. Custom scores are not permitted."
                    }, status=400)

                duration_map = {0.5: 'half_day', 1.0: 'full_day', 1.5: 'one_and_half_day', 2.0: 'two_days'}
                work_duration = duration_map.get(score_float, 'full_day')
                entry_type = 'fixed'
                uom_name = activity.uom_name or 'Birr/Day'
            else:
                entry_type = 'piece_rate'
                work_duration = False
                uom_name = activity.uom_name or 'Birr/Kg'

            # 5. Resolve Activity Norm / Daily Rate for Farm (with fallback to any configured norm)
            norm_rec = env['farm.activity.norm'].search([
                ('activity_id', '=', activity.id),
                ('farm_id', '=', farm.id)
            ], limit=1)

            norm_rate = 0.0
            if norm_rec and norm_rec.norm_value > 0:
                norm_rate = norm_rec.norm_value
                uom_name = norm_rec.uom_name or uom_name
            elif activity.farm_norm_ids:
                any_norm = activity.farm_norm_ids.filtered(lambda n: n.norm_value > 0)
                if any_norm:
                    norm_rate = any_norm[0].norm_value
                    uom_name = any_norm[0].uom_name or uom_name

            total_payment = round(score_float * norm_rate, 2)

            # 6. Create Work Entry Record
            vals = {
                'date': work_date,
                'employee_id': emp.id,
                'entry_type': entry_type,
                'work_duration': work_duration,
                'farm_id': farm.id,
                'sub_farm_id': sub_farm.id if sub_farm else False,
                'sub_unit_id': sub_unit.id if sub_unit else False,
                'block_id': block.id if block else False,
                'activity_id': activity.id,
                'norm_rate': norm_rate,
                'uom_name': uom_name,
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
                        "name": activity.name,
                        "type": activity.type,
                        "type_label": "Fixed (Daily Rate)" if activity.type == 'fixed' else "Piece Rate"
                    },
                    "calculation": {
                        "score": score_float,
                        "norm_rate": norm_rate,
                        "uom": uom_name,
                        "total_payment_birr": total_payment,
                        "formula": f"{score_float} days × {norm_rate} Birr/Day" if is_fixed else f"{score_float} × {norm_rate} {uom_name}"
                    },
                    "state": work_entry.state,
                    "payment_status": work_entry.payment_status
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
                    "type": act.type,
                    "type_label": "Fixed (Daily Rate)" if act.type == 'fixed' else "Piece Rate",
                    "category": act.category,
                    "crop_name": act.crop_name or "",
                    "cost_category": act.cost_category or "",
                    "main_activity": act.main_activity or "",
                    "sub_activity": act.sub_activity or "",
                    "standard_hours": act.standard_hours or 0.0,
                    "required_cost": act.required_cost or 0.0,
                    "activity_type": act.activity_type or "",
                    "requires_labor": act.requires_labor,
                    "requires_machine": act.requires_machine,
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
            fixed_acts = env['farm.activity'].search([('type', '=', 'fixed'), ('active', '=', True)])
            data = []
            for act in fixed_acts:
                for n in act.farm_norm_ids:
                    if farm_code and n.farm_id.code and n.farm_id.code.lower() != farm_code.lower():
                        continue
                    data.append({
                        "id": n.id,
                        "activity": {
                            "id": act.id,
                            "code": act.code,
                            "name": act.name,
                        },
                        "farm": {
                            "id": n.farm_id.id,
                            "code": n.farm_id.code or "",
                            "name": n.farm_id.name
                        },
                        "full_day_rate": n.norm_value,
                        "half_day_rate": round(n.norm_value / 2.0, 2),
                        "uom": n.uom_name or "Birr/Day",
                        "remarks": f"Unified Fixed Activity Rate ({act.name})"
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

    # -------------------------------------------------------------------------
    # GET /api/farms & /odoo/api/farms & /api/fms/farms
    # -------------------------------------------------------------------------
    @http.route([
        '/api/farms',
        '/odoo/api/farms',
        '/api/fms/farms',
        '/odoo/api/fms/farms'
    ], type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_farms(self, farm_id=None, code=None, company_id=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found or could not connect."}, status=500)

        try:
            domain = [('active', '=', True)]
            target_id = farm_id or kwargs.get('id')
            target_code = code or kwargs.get('farm_code')
            target_company = company_id or kwargs.get('company')

            if target_id:
                domain.append(('id', '=', int(target_id)))
            if target_code:
                domain.append(('code', '=ilike', str(target_code).strip()))
            if target_company:
                domain.append(('company_id', '=', int(target_company)))

            farms = env['farm.farm'].search(domain, order='code asc, id asc')

            data = []
            for farm in farms:
                sub_farms_data = []
                for sf in farm.sub_farm_ids.filtered(lambda s: s.active):
                    sub_units_data = []
                    for su in sf.sub_unit_ids.filtered(lambda u: u.active):
                        blocks_data = []
                        for bk in su.block_ids.filtered(lambda b: b.active):
                            blocks_data.append({
                                "id": bk.id,
                                "name": bk.name,
                                "code": bk.code or "",
                                "sub_unit_id": su.id,
                                "sub_unit_code": su.code or "",
                                "sub_farm_id": sf.id,
                                "sub_farm_code": sf.code or "",
                                "farm_id": farm.id,
                                "farm_code": farm.code or "",
                                "supervisor": {
                                    "id": bk.supervisor_id.id,
                                    "name": bk.supervisor_id.name,
                                    "employee_id": bk.supervisor_id.fms_employee_id or ""
                                } if bk.supervisor_id else None,
                                "area": bk.area,
                                "crop_name": bk.crop_name or bk.crop_type or "",
                                "crop_type": bk.crop_type or bk.crop_name or "",
                                "size_ha": bk.size_ha or bk.area or 0.0,
                                "net_area": bk.net_area or 0.0,
                                "plantation_year": bk.plantation_year or None,
                                "variety": bk.variety or "",
                                "population": bk.population or 0.0,
                                "productivity_quarter": bk.productivity_quarter or "",
                                "stumping_year": bk.stumping_year or None,
                                "uprooting_year": bk.uprooting_year or None,
                                "soil_type": bk.soil_type or "",
                                "status": bk.status or "active"
                            })

                        sub_units_data.append({
                            "id": su.id,
                            "name": su.name,
                            "code": su.code or "",
                            "hudad_number": su.hudad_number or "",
                            "sub_farm_id": sf.id,
                            "sub_farm_code": sf.code or "",
                            "farm_id": farm.id,
                            "farm_code": farm.code or "",
                            "manager": {
                                "id": su.manager_id.id,
                                "name": su.manager_id.name,
                                "employee_id": su.manager_id.fms_employee_id or ""
                            } if su.manager_id else None,
                            "area": su.area,
                            "total_gross_area": su.total_gross_area or su.area or 0.0,
                            "total_net_area": su.total_net_area or 0.0,
                            "total_population": su.total_population or 0.0,
                            "blocks_count": len(blocks_data),
                            "assigned_workers_count": len(su.assigned_employee_ids),
                            "blocks": blocks_data
                        })

                    sub_farms_data.append({
                        "id": sf.id,
                        "name": sf.name,
                        "code": sf.code or "",
                        "farm_id": farm.id,
                        "farm_code": farm.code or "",
                        "manager": {
                            "id": sf.manager_id.id,
                            "name": sf.manager_id.name,
                            "employee_id": sf.manager_id.fms_employee_id or ""
                        } if sf.manager_id else None,
                        "area": sf.area,
                        "sub_units_count": len(sub_units_data),
                        "blocks_count": sum(len(u["blocks"]) for u in sub_units_data),
                        "sub_units": sub_units_data
                    })

                data.append({
                    "id": farm.id,
                    "name": farm.name,
                    "code": farm.code or "",
                    "company": {
                        "id": farm.company_id.id,
                        "name": farm.company_id.name
                    } if farm.company_id else None,
                    "manager": {
                        "id": farm.manager_id.id,
                        "name": farm.manager_id.name,
                        "employee_id": farm.manager_id.fms_employee_id or ""
                    } if farm.manager_id else None,
                    "location": farm.location or "",
                    "address": farm.address or "",
                    "total_area": farm.total_area,
                    "sub_farms_count": len(sub_farms_data),
                    "sub_units_count": sum(len(s["sub_units"]) for s in sub_farms_data),
                    "blocks_count": sum(s["blocks_count"] for s in sub_farms_data),
                    "sub_farms": sub_farms_data
                })

            return self._json_response({
                "status": "success",
                "database": db_name,
                "count": len(data),
                "data": data
            }, status=200)

        except Exception as e:
            _logger.error("Error retrieving farms in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Server error: {str(e)}"}, status=500)
        finally:
            if cr:
                cr.close()

