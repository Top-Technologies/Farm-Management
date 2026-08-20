# -*- coding: utf-8 -*-
import json
import base64
import logging
import datetime
from odoo import http, fields, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class FmsRestController(http.Controller):

    def _authenticate(self):
        """Helper to authenticate requests using Bearer token, Basic Auth, or Session."""
        auth_header = request.httprequest.headers.get('Authorization')
        user = None

        if auth_header:
            try:
                auth_parts = auth_header.split(' ', 1)
                if len(auth_parts) == 2:
                    auth_type, auth_val = auth_parts
                    auth_type = auth_type.lower()

                    if auth_type == 'bearer':
                        token = auth_val.strip()
                        uid = request.env['res.users.apikeys'].sudo()._check_credentials(scope='rpc', key=token)
                        if uid:
                            user = request.env['res.users'].sudo().browse(uid)

                    elif auth_type == 'basic':
                        decoded = base64.b64decode(auth_val).decode('utf-8')
                        username, password = decoded.split(':', 1) if ':' in decoded else (decoded, '')

                        # Check password as API Key
                        uid = request.env['res.users.apikeys'].sudo()._check_credentials(scope='rpc', key=password)
                        if not uid:
                            uid = request.env['res.users.apikeys'].sudo()._check_credentials(scope='rpc', key=username)

                        if uid:
                            user = request.env['res.users'].sudo().browse(uid)
                        else:
                            # Fallback to password authentication
                            db_name = request.db or request.env.cr.dbname
                            if db_name:
                                uid = request.env['res.users'].sudo().authenticate(
                                    db_name, username, password, {'interactive': False}
                                )
                                if uid:
                                    user = request.env['res.users'].sudo().browse(uid)
            except Exception as e:
                _logger.error("Authentication error in REST API: %s", str(e))

        # Fallback to session uid if available
        if not user and getattr(request, 'session', None) and request.session.uid:
            user = request.env['res.users'].sudo().browse(request.session.uid)

        # Fallback to admin user for development / testing
        if not user:
            admin_user = request.env.ref('base.user_admin', raise_if_not_found=False)
            if admin_user:
                user = admin_user.sudo()

        return user

    def _json_response(self, data, status=200):
        """Helper to return formatted JSON responses with CORS headers."""
        return request.make_response(
            json.dumps(data, default=str),
            headers=[
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Headers', 'Authorization, Content-Type, Origin, Accept, X-Odoo-Db, X-Database'),
                ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            ],
            status=status
        )

    # -------------------------------------------------------------------------
    # GET /api/fms/employees and GET /api/employees
    # -------------------------------------------------------------------------
    @http.route(['/api/fms/employees', '/api/employees'], type='http', auth='public', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_employees(self, farm_code=None, employee_type=None, search=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        user = self._authenticate()
        if not user:
            return self._json_response({
                "status": "error",
                "message": "Unauthorized: Missing or invalid API key / token."
            }, status=401)

        try:
            domain = []
            if farm_code:
                domain.append('|')
                domain.append(('current_farm_id.code', '=ilike', farm_code.strip()))
                domain.append(('initial_farm_id.code', '=ilike', farm_code.strip()))

            if employee_type:
                domain.append(('farm_employee_type', '=', employee_type.strip().lower()))

            if search:
                domain.append('|')
                domain.append(('name', 'ilike', search.strip()))
                domain.append(('fms_employee_id', 'ilike', search.strip()))

            employees = request.env['hr.employee'].sudo().search(domain, order='id asc')

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
                "count": len(data),
                "data": data
            }, status=200)

        except Exception as e:
            _logger.error("Error retrieving employees in FMS API: %s", str(e), exc_info=True)
            return self._json_response({
                "status": "error",
                "message": f"Server error: {str(e)}"
            }, status=500)

    # -------------------------------------------------------------------------
    # POST /api/fms/work_entries and POST /api/work_entries
    # -------------------------------------------------------------------------
    @http.route(['/api/fms/work_entries', '/api/work_entries'], type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def create_work_entry(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        user = self._authenticate()
        if not user:
            return self._json_response({
                "status": "error",
                "message": "Unauthorized: Missing or invalid API key / token."
            }, status=401)

        # Parse request body (JSON or form data)
        payload = {}
        if request.httprequest.content_type == 'application/json':
            try:
                payload = request.get_json_data() or {}
            except Exception as e:
                return self._json_response({
                    "status": "error",
                    "message": "Invalid JSON format."
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
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'employee_id' (e.g. 'FM01T0001')."
            }, status=400)

        if not activity_identifier:
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'activity_id' (e.g. 'SP')."
            }, status=400)

        if score_val is None:
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'score'."
            }, status=400)

        try:
            score_float = float(score_val)
            if score_float <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            return self._json_response({
                "status": "error",
                "message": "Field 'score' must be a positive number."
            }, status=400)

        work_date = fields.Date.context_today(request.env['farm.work.entry'])
        if date_str:
            try:
                work_date = datetime.datetime.strptime(str(date_str).strip(), '%Y-%m-%d').date()
            except ValueError:
                return self._json_response({
                    "status": "error",
                    "message": "Invalid date format. Expected YYYY-MM-DD."
                }, status=400)

        try:
            # 1. Resolve Employee
            emp = request.env['hr.employee'].sudo().search([
                '|', ('fms_employee_id', '=ilike', str(emp_identifier).strip()),
                     ('employee_code', '=ilike', str(emp_identifier).strip())
            ], limit=1)

            if not emp and str(emp_identifier).isdigit():
                emp = request.env['hr.employee'].sudo().browse(int(emp_identifier)).exists()

            if not emp:
                return self._json_response({
                    "status": "error",
                    "message": f"Employee with ID '{emp_identifier}' not found."
                }, status=404)

            # 2. Resolve Activity
            activity = request.env['farm.activity'].sudo().search([
                ('code', '=ilike', str(activity_identifier).strip())
            ], limit=1)

            if not activity and str(activity_identifier).isdigit():
                activity = request.env['farm.activity'].sudo().browse(int(activity_identifier)).exists()

            if not activity:
                return self._json_response({
                    "status": "error",
                    "message": f"Activity with ID/Code '{activity_identifier}' not found."
                }, status=404)

            # 3. Resolve Location
            farm = emp.current_farm_id or emp.initial_farm_id
            sub_farm = emp.current_sub_farm_id or emp.initial_sub_farm_id
            sub_unit = emp.current_sub_unit_id or emp.initial_sub_unit_id
            block = emp.current_block_id or emp.initial_block_id

            if not farm:
                farm = request.env['farm.farm'].sudo().search([], limit=1)

            if not farm:
                return self._json_response({
                    "status": "error",
                    "message": "No farm found in the system to calculate activity norm."
                }, status=400)

            # 4. Resolve Activity Norm
            norm_rec = request.env['farm.activity.norm'].sudo().search([
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

            work_entry = request.env['farm.work.entry'].sudo().create(vals)

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
            _logger.error("Error creating work entry in FMS API: %s", str(e), exc_info=True)
            return self._json_response({
                "status": "error",
                "message": f"Failed to record work entry: {str(e)}"
            }, status=500)

    # -------------------------------------------------------------------------
    # GET /api/fms/activities and GET /api/activities
    # -------------------------------------------------------------------------
    @http.route(['/api/fms/activities', '/api/activities'], type='http', auth='public', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_activities(self, farm_code=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        user = self._authenticate()
        if not user:
            return self._json_response({
                "status": "error",
                "message": "Unauthorized"
            }, status=401)

        try:
            activities = request.env['farm.activity'].sudo().search([], order='code asc')
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
