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
                ('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, PATCH, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With, X-Odoo-Db, X-Database'),
            ],
        )
        response.status_code = status
        return response

    # -------------------------------------------------------------------------
    # Helper Methods for Employee & Contract Resolution
    # -------------------------------------------------------------------------
    def _find_employee(self, env, identifier=None, kwargs=None):
        """Helper to resolve an hr.employee by fms_employee_id, employee_code, database ID, barcode, or name."""
        kwargs = kwargs or {}
        target = identifier or kwargs.get('employee_id') or kwargs.get('id') or kwargs.get('emp_id') or kwargs.get('code')
        if not target:
            return env['hr.employee'].browse()

        target_str = str(target).strip()
        # 1. Search by fms_employee_id or employee_code
        emp = env['hr.employee'].search([
            '|', ('fms_employee_id', '=ilike', target_str),
                 ('employee_code', '=ilike', target_str)
        ], limit=1)

        # 2. Search by numeric database ID if digits
        if not emp and target_str.isdigit():
            emp = env['hr.employee'].browse(int(target_str)).exists()

        # 3. Search by barcode
        if not emp and hasattr(env['hr.employee'], 'barcode'):
            emp = env['hr.employee'].search([('barcode', '=ilike', target_str)], limit=1)

        # 4. Search by exact or case-insensitive name
        if not emp:
            emp = env['hr.employee'].search([('name', '=ilike', target_str)], limit=1)

        return emp

    def _get_employee_contract(self, emp):
        """Resolves the current active (open/draft) or latest contract for an employee."""
        # 1. Current contract relation on hr.employee
        if emp.contract_id:
            return emp.contract_id

        # 2. Search running 'open' contracts
        contract = emp.env['hr.contract'].search([
            ('employee_id', '=', emp.id),
            ('state', '=', 'open'),
        ], order='date_start desc, id desc', limit=1)
        if contract:
            return contract

        # 3. Search 'draft' contracts
        contract = emp.env['hr.contract'].search([
            ('employee_id', '=', emp.id),
            ('state', '=', 'draft'),
        ], order='date_start desc, id desc', limit=1)
        if contract:
            return contract

        # 4. Fallback to latest contract (including expired)
        return emp.env['hr.contract'].search([
            ('employee_id', '=', emp.id),
        ], order='date_start desc, id desc', limit=1)

    def _format_contract_wage_data(self, emp):
        """Builds structured contract and basic monthly wage payload for an employee."""
        contract = self._get_employee_contract(emp)
        farm = emp.current_farm_id or emp.initial_farm_id

        basic_wage = 0.0
        matrix_basic_wage = 0.0
        gross_wage = 0.0
        net_wage = 0.0
        contract_info = None

        if contract:
            basic_wage = float(contract.wage or 0.0)
            if hasattr(contract, 'matrix_basic_wage') and contract.matrix_basic_wage:
                matrix_basic_wage = float(contract.matrix_basic_wage)
            elif hasattr(emp, 'matrix_basic_wage') and emp.matrix_basic_wage:
                matrix_basic_wage = float(emp.matrix_basic_wage)

            if basic_wage == 0.0 and matrix_basic_wage > 0.0:
                basic_wage = matrix_basic_wage

            gross_wage = float(getattr(contract, 'gross_monthly_wage', 0.0) or basic_wage)
            net_wage = float(getattr(contract, 'net_wage_after_deductions', 0.0) or 0.0)

            grade_name = ""
            if hasattr(contract, 'salary_grade_id') and contract.salary_grade_id:
                grade_name = contract.salary_grade_id.name
            elif hasattr(contract, 'salary_grade') and contract.salary_grade:
                grade_name = str(contract.salary_grade)

            scale_name = ""
            if hasattr(contract, 'salary_matrix_id') and contract.salary_matrix_id:
                scale_name = contract.salary_matrix_id.name

            level_name = ""
            if hasattr(contract, 'salary_level') and contract.salary_level:
                level_name = dict(contract._fields['salary_level'].selection).get(contract.salary_level, contract.salary_level) if 'salary_level' in contract._fields else str(contract.salary_level)

            currency_name = contract.currency_id.name if (hasattr(contract, 'currency_id') and contract.currency_id) else (contract.company_id.currency_id.name if contract.company_id else 'ETB')

            contract_info = {
                "id": contract.id,
                "name": contract.name,
                "state": contract.state,
                "is_running": contract.state == 'open',
                "date_start": contract.date_start.isoformat() if contract.date_start else None,
                "date_end": contract.date_end.isoformat() if contract.date_end else None,
                "basic_monthly_wage": round(basic_wage, 2),
                "matrix_basic_wage": round(matrix_basic_wage, 2),
                "gross_monthly_wage": round(gross_wage, 2),
                "estimated_net_wage": round(net_wage, 2),
                "currency": currency_name,
                "salary_scale": scale_name,
                "salary_grade": grade_name,
                "salary_level": level_name,
                "structure_type": contract.structure_type_id.name if hasattr(contract, 'structure_type_id') and contract.structure_type_id else None,
            }
        else:
            if hasattr(emp, 'matrix_basic_wage') and emp.matrix_basic_wage:
                basic_wage = float(emp.matrix_basic_wage)
                matrix_basic_wage = float(emp.matrix_basic_wage)

        classification_labels = dict(emp._fields['farm_employee_type'].selection) if 'farm_employee_type' in emp._fields else {}
        class_label = classification_labels.get(emp.farm_employee_type, emp.farm_employee_type or 'Permanent')

        return {
            "id": emp.id,
            "employee_id": emp.fms_employee_id or emp.employee_code or "",
            "name": emp.name,
            "classification": class_label,
            "classification_code": emp.farm_employee_type or "permanent",
            "job_title": emp.job_title or (emp.job_id.name if emp.job_id else ""),
            "department": emp.department_id.name if emp.department_id else "",
            "farm": {
                "id": farm.id,
                "code": farm.code or "",
                "name": farm.name
            } if farm else None,
            "has_active_contract": bool(contract and contract.state == 'open'),
            "basic_monthly_wage": round(basic_wage, 2),
            "currency": contract_info["currency"] if contract_info else "ETB",
            "contract": contract_info
        }

    # -------------------------------------------------------------------------
    # GET /api/employees & /api/employees/<employee_identifier>
    # -------------------------------------------------------------------------
    @http.route([
        '/api/employees/<employee_identifier>',
        '/odoo/api/employees/<employee_identifier>',
        '/api/fms/employees/<employee_identifier>',
        '/odoo/api/fms/employees/<employee_identifier>',
        '/api/employees',
        '/odoo/api/employees',
        '/api/fms/employees',
        '/odoo/api/fms/employees'
    ], type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_employees(self, employee_identifier=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({
                "status": "error",
                "message": "Database not found or could not connect."
            }, status=500)

        try:
            target = employee_identifier or kwargs.get('id') or kwargs.get('employee_id')
            if target:
                emp = self._find_employee(env, identifier=target, kwargs=kwargs)
                if not emp:
                    return self._json_response({
                        "status": "error",
                        "message": f"Employee with code or ID '{target}' not found in database '{db_name}'."
                    }, status=404)

                # Format single employee
                farm = emp.current_farm_id or emp.initial_farm_id
                sub_farm = emp.current_sub_farm_id or emp.initial_sub_farm_id
                sub_unit = emp.current_sub_unit_id or emp.initial_sub_unit_id
                block = emp.current_block_id or emp.initial_block_id

                classification_labels = dict(emp._fields['farm_employee_type'].selection) if 'farm_employee_type' in emp._fields else {}
                class_label = classification_labels.get(emp.farm_employee_type, emp.farm_employee_type or 'Temporary')

                contract_wage_data = self._format_contract_wage_data(emp)

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

                emp_data = {
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
                    "contract_basic_wage": contract_wage_data["basic_monthly_wage"],
                    "has_active_contract": contract_wage_data["has_active_contract"],
                    "contract": contract_wage_data["contract"],
                    "temporary_wage_rate": temp_rate,
                    "job_title": emp.job_title or (emp.job_id.name if emp.job_id else ""),
                    "department": emp.department_id.name if emp.department_id else "",
                    "work_phone": emp.work_phone or emp.mobile_phone or "",
                    "work_email": emp.work_email or "",
                    "total_work_entries": emp.work_entry_count,
                    "total_earned_amount": emp.total_earned_amount
                }
                return self._json_response({
                    "status": "success",
                    "database": db_name,
                    "data": emp_data
                }, status=200)

            farm_code = kwargs.get('farm') or kwargs.get('farm_code')
            employee_type = kwargs.get('type') or kwargs.get('classification')

            domain = [('active', '=', True)]
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

                # Contract basic wage calculation
                contract_wage = float(emp.contract_id.wage or getattr(emp, 'matrix_basic_wage', 0.0) or 0.0)
                has_active_contract = bool(emp.contract_id and emp.contract_id.state == 'open')

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
                    "contract_basic_wage": round(contract_wage, 2),
                    "has_active_contract": has_active_contract,
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
    # GET /api/employees/<employee_identifier>/contract_wage & /api/employees/contract_wage
    # -------------------------------------------------------------------------
    @http.route([
        '/api/employees/<employee_identifier>/contract_wage',
        '/api/employees/<employee_identifier>/wage',
        '/api/employees/<employee_identifier>/contract',
        '/odoo/api/employees/<employee_identifier>/contract_wage',
        '/odoo/api/employees/<employee_identifier>/wage',
        '/api/fms/employees/<employee_identifier>/contract_wage',
        '/odoo/api/fms/employees/<employee_identifier>/contract_wage',
        '/api/employees/contract_wage',
        '/odoo/api/employees/contract_wage',
        '/api/fms/employees/contract_wage',
        '/odoo/api/fms/employees/contract_wage',
        '/api/contracts/basic_wage',
        '/odoo/api/contracts/basic_wage',
        '/api/fms/contracts/basic_wage',
        '/odoo/api/fms/contracts/basic_wage',
    ], type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_employee_contract_wage(self, employee_identifier=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({
                "status": "error",
                "message": "Database not found or could not connect."
            }, status=500)

        try:
            target = employee_identifier or kwargs.get('employee_id') or kwargs.get('id') or kwargs.get('emp_id') or kwargs.get('code')
            if target:
                emp = self._find_employee(env, identifier=target, kwargs=kwargs)
                if not emp:
                    return self._json_response({
                        "status": "error",
                        "message": f"Employee with code or ID '{target}' not found in database '{db_name}'."
                    }, status=404)

                return self._json_response({
                    "status": "success",
                    "database": db_name,
                    "data": self._format_contract_wage_data(emp)
                }, status=200)

            # Filtered list of all employee contract wages
            farm_code = kwargs.get('farm') or kwargs.get('farm_code')
            employee_type = kwargs.get('type') or kwargs.get('classification')
            has_contract_param = kwargs.get('has_contract')

            domain = [('active', '=', True)]
            if employee_type:
                domain.append(('farm_employee_type', '=', employee_type.lower()))

            employees = env['hr.employee'].search(domain, order='fms_employee_id asc, id asc')

            data = []
            for emp in employees:
                farm = emp.current_farm_id or emp.initial_farm_id
                if farm_code and farm and farm.code and farm.code.lower() != farm_code.lower():
                    continue

                formatted = self._format_contract_wage_data(emp)

                if has_contract_param is not None:
                    filter_has_contract = str(has_contract_param).lower() in ('1', 'true', 'yes')
                    if formatted['has_active_contract'] != filter_has_contract:
                        continue

                data.append(formatted)

            return self._json_response({
                "status": "success",
                "database": db_name,
                "count": len(data),
                "data": data
            }, status=200)

        except Exception as e:
            _logger.error("Error retrieving contract wage in REST API: %s", str(e), exc_info=True)
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
            emp = self._find_employee(env, identifier=emp_identifier)

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

    def _format_activity(self, act, farm_code=None):
        """Helper to format a farm.activity record into a JSON-friendly dict."""
        norms = []
        for n in act.farm_norm_ids:
            if not farm_code or (n.farm_id.code and n.farm_id.code.lower() == str(farm_code).lower()):
                norms.append({
                    "id": n.id,
                    "farm_id": n.farm_id.id,
                    "farm_code": n.farm_id.code or "",
                    "farm_name": n.farm_id.name or "",
                    "norm_value": n.norm_value,
                    "uom": n.uom_name or act.uom_name or ""
                })
        return {
            "id": act.id,
            "code": act.code or "",
            "name": act.name,
            "active": act.active,
            "type": act.type,
            "type_label": "Fixed (Daily Rate)" if act.type == 'fixed' else "Piece Rate",
            "category": act.category or "",
            "crop_name": act.crop_name or "",
            "cost_category": act.cost_category or "",
            "main_activity": act.main_activity or "",
            "sub_activity": act.sub_activity or "",
            "standard_hours": act.standard_hours or 0.0,
            "required_cost": act.required_cost or 0.0,
            "activity_type": act.activity_type or "",
            "requires_labor": act.requires_labor,
            "requires_machine": act.requires_machine,
            "uom_name": act.uom_name or "",
            "description": act.description or "",
            "company_id": act.company_id.id if act.company_id else None,
            "norms_count": len(norms),
            "norms": norms
        }

    def _parse_payload(self, kwargs):
        """Helper to parse request payload from JSON body and merge with query params."""
        payload = {}
        if request.httprequest.data:
            try:
                raw_body = request.httprequest.data.decode('utf-8')
                if raw_body.strip():
                    payload = json.loads(raw_body)
            except Exception:
                pass
        if not isinstance(payload, dict):
            payload = {}
        for k, v in kwargs.items():
            if k not in payload:
                payload[k] = v
        return payload

    def _find_activity(self, env, identifier=None, payload=None, kwargs=None):
        """Resolves a farm.activity record by code, database ID, or name."""
        payload = payload or {}
        kwargs = kwargs or {}
        target = (
            identifier
            or payload.get('code')
            or payload.get('activity_code')
            or payload.get('id')
            or payload.get('activity_id')
            or kwargs.get('code')
            or kwargs.get('activity_code')
            or kwargs.get('id')
            or kwargs.get('activity_id')
        )
        if not target:
            return None

        target_str = str(target).strip()
        # 1. Search by Activity Code (case-insensitive)
        act = env['farm.activity'].search([('code', '=ilike', target_str)], limit=1)
        if act:
            return act

        # 2. Search by Database ID if numeric
        if target_str.isdigit():
            try:
                act = env['farm.activity'].browse(int(target_str)).exists()
                if act:
                    return act
            except Exception:
                pass

        # 3. Search by Activity Name (case-insensitive)
        act = env['farm.activity'].search([('name', '=ilike', target_str)], limit=1)
        return act or None

    def _resolve_farm(self, env, norm_item):
        """Resolves a farm record by id, code, or name."""
        farm = None
        farm_id = norm_item.get('farm_id')
        farm_code = norm_item.get('farm_code')
        farm_name = norm_item.get('farm_name') or norm_item.get('farm')

        if farm_id:
            try:
                farm = env['farm.farm'].browse(int(farm_id)).exists()
            except (ValueError, TypeError):
                pass
        if not farm and farm_code:
            farm = env['farm.farm'].search([('code', '=ilike', str(farm_code).strip())], limit=1)
        if not farm and farm_name:
            farm = env['farm.farm'].search([('name', '=ilike', str(farm_name).strip())], limit=1)
        return farm

    # -------------------------------------------------------------------------
    # READ: GET /api/activities & /api/activities/<code_or_id>
    # -------------------------------------------------------------------------
    @http.route([
        '/api/activities/<activity_identifier>',
        '/odoo/api/activities/<activity_identifier>',
        '/api/fms/activities/<activity_identifier>',
        '/odoo/api/fms/activities/<activity_identifier>',
        '/api/activities',
        '/odoo/api/activities',
        '/api/fms/activities',
        '/odoo/api/fms/activities',
    ], type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_activities(self, activity_identifier=None, farm_code=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found."}, status=500)

        try:
            # Check if a single activity is requested by code, ID, or query parameter
            activity = self._find_activity(env, identifier=activity_identifier, kwargs=kwargs)
            if activity:
                return self._json_response({
                    "status": "success",
                    "database": db_name,
                    "data": self._format_activity(activity, farm_code=farm_code)
                }, status=200)

            # If an explicit identifier was given but not found
            target = activity_identifier or kwargs.get('code') or kwargs.get('id')
            if target:
                return self._json_response({
                    "status": "error",
                    "message": f"Activity with code or ID '{target}' not found."
                }, status=404)

            # Otherwise, list activities with optional filters
            domain = []
            if 'active' in kwargs:
                val = str(kwargs['active']).lower() in ('1', 'true', 'yes')
                domain.append(('active', '=', val))

            if 'type' in kwargs:
                domain.append(('type', '=', str(kwargs['type']).strip()))

            if 'category' in kwargs:
                domain.append(('category', '=', str(kwargs['category']).strip()))

            if 'requires_labor' in kwargs:
                val = str(kwargs['requires_labor']).lower() in ('1', 'true', 'yes')
                domain.append(('requires_labor', '=', val))

            if 'requires_machine' in kwargs:
                val = str(kwargs['requires_machine']).lower() in ('1', 'true', 'yes')
                domain.append(('requires_machine', '=', val))

            search_query = kwargs.get('search') or kwargs.get('q')
            if search_query:
                term = f"%{search_query.strip()}%"
                domain.append('|')
                domain.append(('name', 'ilike', term))
                domain.append('|')
                domain.append(('code', 'ilike', term))
                domain.append(('main_activity', 'ilike', term))

            activities = env['farm.activity'].search(domain, order='code asc, id asc')
            data = [self._format_activity(act, farm_code=farm_code) for act in activities]

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
    # CREATE: POST /api/activities
    # -------------------------------------------------------------------------
    @http.route([
        '/api/activities',
        '/odoo/api/activities',
        '/api/fms/activities',
        '/odoo/api/fms/activities'
    ], type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def create_activity(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found."}, status=500)

        payload = self._parse_payload(kwargs)

        name = payload.get('name')
        if not name or not str(name).strip():
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'name'."
            }, status=400)

        try:
            vals = {'name': str(name).strip()}

            # Activity Code
            code = payload.get('code')
            if code and str(code).strip():
                code_str = str(code).strip()
                existing = env['farm.activity'].search([('code', '=ilike', code_str)], limit=1)
                if existing:
                    if cr: cr.close()
                    return self._json_response({
                        "status": "error",
                        "message": f"Activity with code '{code_str}' already exists (ID: {existing.id}, Name: {existing.name})."
                    }, status=409)
                vals['code'] = code_str

            # Activity Type
            act_type = payload.get('type')
            if act_type:
                if act_type not in ('piece_rate', 'fixed'):
                    if cr: cr.close()
                    return self._json_response({
                        "status": "error",
                        "message": f"Invalid type '{act_type}'. Allowed values: 'piece_rate', 'fixed'."
                    }, status=400)
                vals['type'] = act_type

            # Category
            category = payload.get('category')
            valid_categories = ('land_prep', 'planting', 'crop_care', 'irrigation', 'harvest', 'maintenance')
            if category and category in valid_categories:
                vals['category'] = category

            # Booleans
            if 'requires_labor' in payload:
                rl = payload['requires_labor']
                vals['requires_labor'] = (rl is True or str(rl).lower() in ('1', 'true', 'yes'))
            if 'requires_machine' in payload:
                rm = payload['requires_machine']
                vals['requires_machine'] = (rm is True or str(rm).lower() in ('1', 'true', 'yes'))

            # String fields
            for char_f in ('crop_name', 'cost_category', 'main_activity', 'sub_activity', 'activity_type', 'uom_name', 'description'):
                if char_f in payload and payload[char_f] is not None:
                    vals[char_f] = str(payload[char_f]).strip()

            # Numeric fields
            for float_f in ('standard_hours', 'required_cost'):
                if float_f in payload and payload[float_f] is not None:
                    try:
                        vals[float_f] = float(payload[float_f])
                    except (ValueError, TypeError):
                        pass

            if 'company_id' in payload and payload['company_id']:
                try:
                    vals['company_id'] = int(payload['company_id'])
                except (ValueError, TypeError):
                    pass

            activity = env['farm.activity'].create(vals)

            # Process nested norms if provided
            norms_payload = payload.get('norms')
            if norms_payload and isinstance(norms_payload, list):
                for norm_item in norms_payload:
                    if not isinstance(norm_item, dict):
                        continue
                    farm = self._resolve_farm(env, norm_item)
                    if farm:
                        norm_val = norm_item.get('norm_value', norm_item.get('value', 0.0))
                        try:
                            norm_val_flt = float(norm_val)
                        except (ValueError, TypeError):
                            norm_val_flt = 0.0

                        existing_norm = env['farm.activity.norm'].search([
                            ('activity_id', '=', activity.id),
                            ('farm_id', '=', farm.id)
                        ], limit=1)
                        if existing_norm:
                            existing_norm.write({'norm_value': norm_val_flt})
                        else:
                            env['farm.activity.norm'].create({
                                'activity_id': activity.id,
                                'farm_id': farm.id,
                                'norm_value': norm_val_flt,
                            })

            cr.commit()

            return self._json_response({
                "status": "success",
                "message": f"Activity '{activity.name}' ({activity.code}) created successfully.",
                "data": self._format_activity(activity)
            }, status=201)

        except Exception as e:
            if cr: cr.rollback()
            _logger.error("Error creating activity in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to create activity: {str(e)}"}, status=500)
        finally:
            if cr:
                cr.close()

    # -------------------------------------------------------------------------
    # UPDATE: PUT & PATCH /api/activities/<code_or_id> or /api/activities
    # -------------------------------------------------------------------------
    @http.route([
        '/api/activities/<activity_identifier>',
        '/odoo/api/activities/<activity_identifier>',
        '/api/fms/activities/<activity_identifier>',
        '/odoo/api/fms/activities/<activity_identifier>',
        '/api/activities',
        '/odoo/api/activities',
        '/api/fms/activities',
        '/odoo/api/fms/activities',
    ], type='http', auth='none', methods=['PUT', 'PATCH', 'POST', 'OPTIONS'], csrf=False, cors='*')
    def update_activity(self, activity_identifier=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found."}, status=500)

        payload = self._parse_payload(kwargs)

        activity = self._find_activity(env, identifier=activity_identifier, payload=payload, kwargs=kwargs)
        if not activity:
            target = activity_identifier or payload.get('code') or payload.get('id') or kwargs.get('code') or kwargs.get('id')
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": f"Activity not found with code or ID '{target}'."
            }, status=404)

        try:
            vals = {}
            if 'name' in payload and payload['name']:
                vals['name'] = str(payload['name']).strip()

            new_code = payload.get('new_code') or (payload.get('code') if payload.get('code') and payload.get('code') != activity.code else None)
            if new_code and new_code != activity.code:
                existing = env['farm.activity'].search([('code', '=ilike', str(new_code).strip()), ('id', '!=', activity.id)], limit=1)
                if existing:
                    if cr: cr.close()
                    return self._json_response({
                        "status": "error",
                        "message": f"Another activity already has code '{new_code}'."
                    }, status=409)
                vals['code'] = str(new_code).strip()

            if 'type' in payload:
                act_type = payload['type']
                if act_type in ('piece_rate', 'fixed'):
                    vals['type'] = act_type

            valid_categories = ('land_prep', 'planting', 'crop_care', 'irrigation', 'harvest', 'maintenance')
            if 'category' in payload and payload['category'] in valid_categories:
                vals['category'] = payload['category']

            if 'requires_labor' in payload:
                rl = payload['requires_labor']
                vals['requires_labor'] = (rl is True or str(rl).lower() in ('1', 'true', 'yes'))

            if 'requires_machine' in payload:
                rm = payload['requires_machine']
                vals['requires_machine'] = (rm is True or str(rm).lower() in ('1', 'true', 'yes'))

            if 'active' in payload:
                act_val = payload['active']
                vals['active'] = (act_val is True or str(act_val).lower() in ('1', 'true', 'yes'))

            for char_f in ('crop_name', 'cost_category', 'main_activity', 'sub_activity', 'activity_type', 'uom_name', 'description'):
                if char_f in payload and payload[char_f] is not None:
                    vals[char_f] = str(payload[char_f]).strip()

            for float_f in ('standard_hours', 'required_cost'):
                if float_f in payload and payload[float_f] is not None:
                    try:
                        vals[float_f] = float(payload[float_f])
                    except (ValueError, TypeError):
                        pass

            if vals:
                activity.write(vals)

            # Update norms if provided
            norms_payload = payload.get('norms')
            if norms_payload and isinstance(norms_payload, list):
                replace_norms = payload.get('replace_norms', False)
                if replace_norms:
                    activity.farm_norm_ids.unlink()

                for norm_item in norms_payload:
                    if not isinstance(norm_item, dict):
                        continue
                    farm = self._resolve_farm(env, norm_item)
                    if farm:
                        norm_val = norm_item.get('norm_value', norm_item.get('value', 0.0))
                        try:
                            norm_val_flt = float(norm_val)
                        except (ValueError, TypeError):
                            norm_val_flt = 0.0

                        existing_norm = env['farm.activity.norm'].search([
                            ('activity_id', '=', activity.id),
                            ('farm_id', '=', farm.id)
                        ], limit=1)

                        if existing_norm:
                            existing_norm.write({'norm_value': norm_val_flt})
                        else:
                            env['farm.activity.norm'].create({
                                'activity_id': activity.id,
                                'farm_id': farm.id,
                                'norm_value': norm_val_flt,
                            })

            cr.commit()

            return self._json_response({
                "status": "success",
                "message": f"Activity '{activity.name}' ({activity.code}) updated successfully.",
                "data": self._format_activity(activity)
            }, status=200)

        except Exception as e:
            if cr: cr.rollback()
            _logger.error("Error updating activity in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to update activity: {str(e)}"}, status=500)
        finally:
            if cr:
                cr.close()

    # -------------------------------------------------------------------------
    # DELETE: DELETE /api/activities/<code_or_id> or /api/activities
    # -------------------------------------------------------------------------
    @http.route([
        '/api/activities/<activity_identifier>',
        '/odoo/api/activities/<activity_identifier>',
        '/api/fms/activities/<activity_identifier>',
        '/odoo/api/fms/activities/<activity_identifier>',
        '/api/activities',
        '/odoo/api/activities',
        '/api/fms/activities',
        '/odoo/api/fms/activities',
    ], type='http', auth='none', methods=['DELETE', 'OPTIONS'], csrf=False, cors='*')
    def delete_activity(self, activity_identifier=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found."}, status=500)

        payload = self._parse_payload(kwargs)

        activity = self._find_activity(env, identifier=activity_identifier, payload=payload, kwargs=kwargs)
        if not activity:
            target = activity_identifier or payload.get('code') or payload.get('id') or kwargs.get('code') or kwargs.get('id')
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": f"Activity not found with code or ID '{target}'."
            }, status=404)

        try:
            act_id = activity.id
            act_name = activity.name
            act_code = activity.code

            # Safeguard: check for linked work entries
            entry_count = env['farm.work.entry'].search_count([('activity_id', '=', act_id)])
            if entry_count > 0:
                # Safe archival fallback to preserve payroll integrity
                activity.write({'active': False})
                cr.commit()
                return self._json_response({
                    "status": "success",
                    "action": "archived",
                    "message": f"Activity '{act_name}' ({act_code}) has {entry_count} linked work entries and was archived to protect payroll audit history.",
                    "id": act_id,
                    "code": act_code,
                    "active": False
                }, status=200)
            else:
                activity.unlink()
                cr.commit()
                return self._json_response({
                    "status": "success",
                    "action": "deleted",
                    "message": f"Activity '{act_name}' ({act_code}) was successfully deleted.",
                    "id": act_id,
                    "code": act_code
                }, status=200)

        except Exception as e:
            if cr: cr.rollback()
            _logger.error("Error deleting activity in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to delete activity: {str(e)}"}, status=500)
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

    # -------------------------------------------------------------------------
    # Helper: Single Farm Formatter
    # -------------------------------------------------------------------------
    def _format_single_farm_dict(self, farm):
        return {
            "id": farm.id,
            "name": farm.name,
            "code": farm.code or "",
            "active": farm.active,
            "company_id": farm.company_id.id if farm.company_id else None,
            "company_name": farm.company_id.name if farm.company_id else "",
            "manager": {
                "id": farm.manager_id.id,
                "name": farm.manager_id.name,
                "employee_id": farm.manager_id.fms_employee_id or ""
            } if farm.manager_id else None,
            "location": farm.location or "",
            "address": farm.address or "",
            "description": farm.description or "",
            "total_area": farm.total_area,
            "sub_farm_count": farm.sub_farm_count,
            "sub_unit_count": farm.sub_unit_count,
            "block_count": farm.block_count,
        }

    # -------------------------------------------------------------------------
    # CREATE: POST /api/farms & /odoo/api/farms & /api/fms/farms
    # -------------------------------------------------------------------------
    @http.route([
        '/api/farms',
        '/odoo/api/farms',
        '/api/fms/farms',
        '/odoo/api/fms/farms'
    ], type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def create_farm(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found or could not connect."}, status=500)

        payload = self._parse_payload(kwargs)
        name = payload.get('name')
        if not name or not str(name).strip():
            if cr: cr.close()
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'name'."
            }, status=400)

        try:
            vals = {'name': str(name).strip()}

            code = payload.get('code') or payload.get('farm_code')
            if code and str(code).strip():
                code_str = str(code).strip()
                existing = env['farm.farm'].search([('code', '=ilike', code_str)], limit=1)
                if existing:
                    if cr: cr.close()
                    return self._json_response({
                        "status": "error",
                        "message": f"Farm with code '{code_str}' already exists (ID: {existing.id}, Name: {existing.name})."
                    }, status=409)
                vals['code'] = code_str

            for char_f in ('location', 'address', 'description'):
                if char_f in payload and payload[char_f] is not None:
                    vals[char_f] = str(payload[char_f]).strip()

            if 'active' in payload:
                vals['active'] = (payload['active'] is True or str(payload['active']).lower() in ('1', 'true', 'yes'))

            if 'company_id' in payload and payload['company_id']:
                try:
                    vals['company_id'] = int(payload['company_id'])
                except (ValueError, TypeError):
                    pass

            manager_id = payload.get('manager_id') or payload.get('manager')
            if manager_id:
                emp = self._find_employee(env, identifier=manager_id, kwargs=payload)
                if emp:
                    vals['manager_id'] = emp.id

            farm = env['farm.farm'].create(vals)
            cr.commit()

            return self._json_response({
                "status": "success",
                "database": db_name,
                "message": f"Farm '{farm.name}' ({farm.code}) created successfully.",
                "data": self._format_single_farm_dict(farm)
            }, status=201)

        except Exception as e:
            if cr: cr.rollback()
            _logger.error("Error creating farm in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to create farm: {str(e)}"}, status=500)
        finally:
            if cr:
                cr.close()

    # -------------------------------------------------------------------------
    # UPDATE: PUT/PATCH /api/farms/<farm_identifier> & /api/farms
    # -------------------------------------------------------------------------
    @http.route([
        '/api/farms/<farm_identifier>',
        '/odoo/api/farms/<farm_identifier>',
        '/api/fms/farms/<farm_identifier>',
        '/odoo/api/fms/farms/<farm_identifier>',
        '/api/farms',
        '/odoo/api/farms',
        '/api/fms/farms',
        '/odoo/api/fms/farms'
    ], type='http', auth='none', methods=['PUT', 'PATCH', 'OPTIONS'], csrf=False, cors='*')
    def update_farm(self, farm_identifier=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found or could not connect."}, status=500)

        payload = self._parse_payload(kwargs)
        target = farm_identifier or payload.get('id') or payload.get('farm_id') or payload.get('code') or payload.get('farm_code')

        if not target:
            if cr: cr.close()
            return self._json_response({"status": "error", "message": "Missing farm identifier (id or code)."}, status=400)

        try:
            target_str = str(target).strip()
            farm = None
            if target_str.isdigit():
                farm = env['farm.farm'].browse(int(target_str)).exists()
            if not farm:
                farm = env['farm.farm'].search(['|', ('code', '=ilike', target_str), ('name', '=ilike', target_str)], limit=1)

            if not farm:
                if cr: cr.close()
                return self._json_response({"status": "error", "message": f"Farm '{target_str}' not found."}, status=404)

            vals = {}
            if 'name' in payload and str(payload['name']).strip():
                vals['name'] = str(payload['name']).strip()

            if 'code' in payload and str(payload['code']).strip():
                new_code = str(payload['code']).strip()
                if new_code.lower() != (farm.code or '').lower():
                    dup = env['farm.farm'].search([('code', '=ilike', new_code), ('id', '!=', farm.id)], limit=1)
                    if dup:
                        if cr: cr.close()
                        return self._json_response({"status": "error", "message": f"Farm code '{new_code}' is already in use by ID {dup.id}."}, status=409)
                    vals['code'] = new_code

            for char_f in ('location', 'address', 'description'):
                if char_f in payload:
                    vals[char_f] = str(payload[char_f]).strip() if payload[char_f] is not None else ''

            if 'active' in payload:
                vals['active'] = (payload['active'] is True or str(payload['active']).lower() in ('1', 'true', 'yes'))

            if 'company_id' in payload and payload['company_id']:
                try:
                    vals['company_id'] = int(payload['company_id'])
                except (ValueError, TypeError):
                    pass

            if 'manager_id' in payload or 'manager' in payload:
                manager_val = payload.get('manager_id') or payload.get('manager')
                if manager_val:
                    emp = self._find_employee(env, identifier=manager_val, kwargs=payload)
                    vals['manager_id'] = emp.id if emp else False
                else:
                    vals['manager_id'] = False

            if vals:
                farm.write(vals)
                cr.commit()

            return self._json_response({
                "status": "success",
                "database": db_name,
                "message": f"Farm '{farm.name}' ({farm.code}) updated successfully.",
                "data": self._format_single_farm_dict(farm)
            }, status=200)

        except Exception as e:
            if cr: cr.rollback()
            _logger.error("Error updating farm in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to update farm: {str(e)}"}, status=500)
        finally:
            if cr:
                cr.close()

    # -------------------------------------------------------------------------
    # DELETE: DELETE /api/farms/<farm_identifier> & /api/farms
    # -------------------------------------------------------------------------
    @http.route([
        '/api/farms/<farm_identifier>',
        '/odoo/api/farms/<farm_identifier>',
        '/api/fms/farms/<farm_identifier>',
        '/odoo/api/fms/farms/<farm_identifier>',
        '/api/farms',
        '/odoo/api/farms',
        '/api/fms/farms',
        '/odoo/api/fms/farms'
    ], type='http', auth='none', methods=['DELETE', 'OPTIONS'], csrf=False, cors='*')
    def delete_farm(self, farm_identifier=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found or could not connect."}, status=500)

        payload = self._parse_payload(kwargs)
        target = farm_identifier or payload.get('id') or payload.get('farm_id') or payload.get('code') or payload.get('farm_code')

        if not target:
            if cr: cr.close()
            return self._json_response({"status": "error", "message": "Missing farm identifier (id or code)."}, status=400)

        try:
            target_str = str(target).strip()
            farm = None
            if target_str.isdigit():
                farm = env['farm.farm'].browse(int(target_str)).exists()
            if not farm:
                farm = env['farm.farm'].search(['|', ('code', '=ilike', target_str), ('name', '=ilike', target_str)], limit=1)

            if not farm:
                if cr: cr.close()
                return self._json_response({"status": "error", "message": f"Farm '{target_str}' not found."}, status=404)

            f_id = farm.id
            f_name = farm.name
            f_code = farm.code or ""

            # Check if farm has linked sub farms
            if farm.sub_farm_ids:
                # Soft delete / archive to protect spatial hierarchy
                farm.write({'active': False})
                cr.commit()
                return self._json_response({
                    "status": "success",
                    "action": "archived",
                    "database": db_name,
                    "message": f"Farm '{f_name}' ({f_code}) has {len(farm.sub_farm_ids)} sub farms and was archived to protect spatial integrity.",
                    "id": f_id,
                    "code": f_code,
                    "active": False
                }, status=200)
            else:
                farm.unlink()
                cr.commit()
                return self._json_response({
                    "status": "success",
                    "action": "deleted",
                    "database": db_name,
                    "message": f"Farm '{f_name}' ({f_code}) was successfully deleted.",
                    "id": f_id,
                    "code": f_code
                }, status=200)

        except Exception as e:
            if cr: cr.rollback()
            _logger.error("Error deleting farm in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to delete farm: {str(e)}"}, status=500)
        finally:
            if cr:
                cr.close()

    # -------------------------------------------------------------------------
    # SUB FARMS: POST, PUT, DELETE /api/sub_farms
    # -------------------------------------------------------------------------
    @http.route([
        '/api/sub_farms',
        '/odoo/api/sub_farms',
        '/api/fms/sub_farms',
        '/odoo/api/fms/sub_farms'
    ], type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def create_sub_farm(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found."}, status=500)

        payload = self._parse_payload(kwargs)
        name = payload.get('name')
        if not name or not str(name).strip():
            if cr: cr.close()
            return self._json_response({"status": "error", "message": "Missing required field: 'name'."}, status=400)

        farm = self._resolve_farm(env, payload)
        if not farm:
            if cr: cr.close()
            return self._json_response({"status": "error", "message": "Parent farm not found. Specify 'farm_id' or 'farm_code'."}, status=400)

        try:
            vals = {
                'name': str(name).strip(),
                'farm_id': farm.id,
            }
            if 'area' in payload and payload['area'] is not None:
                try: vals['area'] = float(payload['area'])
                except (ValueError, TypeError): pass

            if 'description' in payload and payload['description']:
                vals['description'] = str(payload['description']).strip()

            manager_id = payload.get('manager_id') or payload.get('manager')
            if manager_id:
                emp = self._find_employee(env, identifier=manager_id, kwargs=payload)
                if emp: vals['manager_id'] = emp.id

            sub_farm = env['farm.sub.farm'].create(vals)
            cr.commit()

            return self._json_response({
                "status": "success",
                "database": db_name,
                "message": f"Sub Farm '{sub_farm.name}' ({sub_farm.code}) created successfully.",
                "data": {
                    "id": sub_farm.id,
                    "name": sub_farm.name,
                    "code": sub_farm.code or "",
                    "farm_id": farm.id,
                    "farm_code": farm.code or "",
                    "area": sub_farm.area
                }
            }, status=201)

        except Exception as e:
            if cr: cr.rollback()
            _logger.error("Error creating sub farm in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to create sub farm: {str(e)}"}, status=500)
        finally:
            if cr:
                cr.close()

    # -------------------------------------------------------------------------
    # SUB UNITS: POST /api/sub_units
    # -------------------------------------------------------------------------
    @http.route([
        '/api/sub_units',
        '/odoo/api/sub_units',
        '/api/fms/sub_units',
        '/odoo/api/fms/sub_units'
    ], type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def create_sub_unit(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found."}, status=500)

        payload = self._parse_payload(kwargs)
        name = payload.get('name')
        if not name or not str(name).strip():
            if cr: cr.close()
            return self._json_response({"status": "error", "message": "Missing required field: 'name'."}, status=400)

        # Resolve parent sub farm
        sub_farm = None
        sf_id = payload.get('sub_farm_id') or payload.get('sub_farm')
        sf_code = payload.get('sub_farm_code')
        if sf_id and str(sf_id).isdigit():
            sub_farm = env['farm.sub.farm'].browse(int(sf_id)).exists()
        if not sub_farm and sf_code:
            sub_farm = env['farm.sub.farm'].search([('code', '=ilike', str(sf_code).strip())], limit=1)

        if not sub_farm:
            if cr: cr.close()
            return self._json_response({"status": "error", "message": "Parent sub farm not found. Specify 'sub_farm_id' or 'sub_farm_code'."}, status=400)

        try:
            vals = {
                'name': str(name).strip(),
                'sub_farm_id': sub_farm.id,
            }
            if 'hudad_number' in payload and payload['hudad_number']:
                vals['hudad_number'] = str(payload['hudad_number']).strip()

            if 'area' in payload and payload['area'] is not None:
                try: vals['area'] = float(payload['area'])
                except (ValueError, TypeError): pass

            manager_id = payload.get('manager_id') or payload.get('manager')
            if manager_id:
                emp = self._find_employee(env, identifier=manager_id, kwargs=payload)
                if emp: vals['manager_id'] = emp.id

            sub_unit = env['farm.sub.unit'].create(vals)
            cr.commit()

            return self._json_response({
                "status": "success",
                "database": db_name,
                "message": f"Sub Unit '{sub_unit.name}' ({sub_unit.code}) created successfully.",
                "data": {
                    "id": sub_unit.id,
                    "name": sub_unit.name,
                    "code": sub_unit.code or "",
                    "sub_farm_id": sub_farm.id,
                    "sub_farm_code": sub_farm.code or "",
                    "hudad_number": sub_unit.hudad_number or "",
                    "area": sub_unit.area
                }
            }, status=201)

        except Exception as e:
            if cr: cr.rollback()
            _logger.error("Error creating sub unit in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to create sub unit: {str(e)}"}, status=500)
        finally:
            if cr:
                cr.close()

    # -------------------------------------------------------------------------
    # BLOCKS: POST /api/blocks
    # -------------------------------------------------------------------------
    @http.route([
        '/api/blocks',
        '/odoo/api/blocks',
        '/api/fms/blocks',
        '/odoo/api/fms/blocks'
    ], type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def create_block(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        env, cr, db_name = self._get_env_and_user()
        if not env:
            return self._json_response({"status": "error", "message": "Database not found."}, status=500)

        payload = self._parse_payload(kwargs)
        name = payload.get('name')
        if not name or not str(name).strip():
            if cr: cr.close()
            return self._json_response({"status": "error", "message": "Missing required field: 'name'."}, status=400)

        # Resolve parent sub unit
        sub_unit = None
        su_id = payload.get('sub_unit_id') or payload.get('sub_unit')
        su_code = payload.get('sub_unit_code')
        if su_id and str(su_id).isdigit():
            sub_unit = env['farm.sub.unit'].browse(int(su_id)).exists()
        if not sub_unit and su_code:
            sub_unit = env['farm.sub.unit'].search([('code', '=ilike', str(su_code).strip())], limit=1)

        if not sub_unit:
            if cr: cr.close()
            return self._json_response({"status": "error", "message": "Parent sub unit not found. Specify 'sub_unit_id' or 'sub_unit_code'."}, status=400)

        try:
            vals = {
                'name': str(name).strip(),
                'sub_unit_id': sub_unit.id,
            }
            if 'area' in payload and payload['area'] is not None:
                try: vals['area'] = float(payload['area'])
                except (ValueError, TypeError): pass

            for char_f in ('crop_name', 'crop_type', 'variety', 'productivity_quarter', 'soil_type'):
                if char_f in payload and payload[char_f]:
                    vals[char_f] = str(payload[char_f]).strip()

            if 'population' in payload and payload['population'] is not None:
                try: vals['population'] = float(payload['population'])
                except (ValueError, TypeError): pass

            supervisor_id = payload.get('supervisor_id') or payload.get('supervisor')
            if supervisor_id:
                emp = self._find_employee(env, identifier=supervisor_id, kwargs=payload)
                if emp: vals['supervisor_id'] = emp.id

            block = env['farm.block'].create(vals)
            cr.commit()

            return self._json_response({
                "status": "success",
                "database": db_name,
                "message": f"Block '{block.name}' ({block.code}) created successfully.",
                "data": {
                    "id": block.id,
                    "name": block.name,
                    "code": block.code or "",
                    "sub_unit_id": sub_unit.id,
                    "sub_unit_code": sub_unit.code or "",
                    "area": block.area,
                    "crop_name": block.crop_name or ""
                }
            }, status=201)

        except Exception as e:
            if cr: cr.rollback()
            _logger.error("Error creating block in REST API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to create block: {str(e)}"}, status=500)
        finally:
            if cr:
                cr.close()


