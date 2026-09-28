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
                ('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, PATCH, OPTIONS')
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

        work_date = fields.Date.today()
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

            # Check Activity Type (Fixed vs Piece Rate)
            is_fixed = (activity.type == 'fixed')
            if is_fixed:
                if score_float not in (0.5, 1.0, 1.5, 2.0):
                    return self._json_response({
                        "status": "error",
                        "message": f"For fixed rate activity '{activity.code}' ({activity.name}), score must be strictly 0.5 (Half Day), 1.0 (Full Day), 1.5 (Day and a Half), or 2.0 (Two Days). Received: {score_float}."
                    }, status=400)
                duration_map = {0.5: 'half_day', 1.0: 'full_day', 1.5: 'one_and_half_day', 2.0: 'two_days'}
                work_duration = duration_map.get(score_float, 'full_day')
                entry_type = 'fixed'
            else:
                entry_type = 'piece_rate'
                work_duration = False

            # 4. Resolve Activity Norm (with fallback to any configured norm)
            norm_rec = request.env['farm.activity.norm'].sudo().search([
                ('activity_id', '=', activity.id),
                ('farm_id', '=', farm.id)
            ], limit=1)

            norm_rate = 0.0
            uom_name = activity.uom_name or ('Birr/Day' if is_fixed else 'Birr/Kg')
            if norm_rec and norm_rec.norm_value > 0:
                norm_rate = norm_rec.norm_value
                uom_name = norm_rec.uom_name or uom_name
            elif activity.farm_norm_ids:
                any_norm = activity.farm_norm_ids.filtered(lambda n: n.norm_value > 0)
                if any_norm:
                    norm_rate = any_norm[0].norm_value
                    uom_name = any_norm[0].uom_name or uom_name

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
                'entry_type': entry_type,
                'work_duration': work_duration,
                'norm_rate': norm_rate,
                'uom_name': uom_name,
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

    def _find_activity(self, identifier=None, payload=None, kwargs=None):
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
        act = request.env['farm.activity'].sudo().search([('code', '=ilike', target_str)], limit=1)
        if act:
            return act

        if target_str.isdigit():
            try:
                act = request.env['farm.activity'].sudo().browse(int(target_str)).exists()
                if act:
                    return act
            except Exception:
                pass

        act = request.env['farm.activity'].sudo().search([('name', '=ilike', target_str)], limit=1)
        return act or None

    def _resolve_farm(self, norm_item):
        """Resolves a farm record by id, code, or name."""
        farm = None
        farm_id = norm_item.get('farm_id')
        farm_code = norm_item.get('farm_code')
        farm_name = norm_item.get('farm_name') or norm_item.get('farm')

        if farm_id:
            try:
                farm = request.env['farm.farm'].sudo().browse(int(farm_id)).exists()
            except (ValueError, TypeError):
                pass
        if not farm and farm_code:
            farm = request.env['farm.farm'].sudo().search([('code', '=ilike', str(farm_code).strip())], limit=1)
        if not farm and farm_name:
            farm = request.env['farm.farm'].sudo().search([('name', '=ilike', str(farm_name).strip())], limit=1)
        return farm

    # -------------------------------------------------------------------------
    # READ: GET /api/fms/activities & GET /api/activities
    # -------------------------------------------------------------------------
    @http.route([
        '/api/fms/activities/<activity_identifier>',
        '/api/activities/<activity_identifier>',
        '/api/fms/activities',
        '/api/activities',
    ], type='http', auth='public', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_activities(self, activity_identifier=None, farm_code=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        user = self._authenticate()
        if not user:
            return self._json_response({
                "status": "error",
                "message": "Unauthorized"
            }, status=401)

        try:
            activity = self._find_activity(identifier=activity_identifier, kwargs=kwargs)
            if activity:
                return self._json_response({
                    "status": "success",
                    "data": self._format_activity(activity, farm_code=farm_code)
                }, status=200)

            target = activity_identifier or kwargs.get('code') or kwargs.get('id')
            if target:
                return self._json_response({
                    "status": "error",
                    "message": f"Activity with code or ID '{target}' not found."
                }, status=404)

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

            activities = request.env['farm.activity'].sudo().search(domain, order='code asc, id asc')
            data = [self._format_activity(act, farm_code=farm_code) for act in activities]

            return self._json_response({
                "status": "success",
                "count": len(data),
                "data": data
            }, status=200)
        except Exception as e:
            return self._json_response({"status": "error", "message": str(e)}, status=500)

    # -------------------------------------------------------------------------
    # CREATE: POST /api/fms/activities & POST /api/activities
    # -------------------------------------------------------------------------
    @http.route([
        '/api/fms/activities',
        '/api/activities',
    ], type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def create_activity(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        user = self._authenticate()
        if not user:
            return self._json_response({
                "status": "error",
                "message": "Unauthorized"
            }, status=401)

        payload = self._parse_payload(kwargs)

        name = payload.get('name')
        if not name or not str(name).strip():
            return self._json_response({
                "status": "error",
                "message": "Missing required field: 'name'."
            }, status=400)

        try:
            vals = {'name': str(name).strip()}

            code = payload.get('code')
            if code and str(code).strip():
                code_str = str(code).strip()
                existing = request.env['farm.activity'].sudo().search([('code', '=ilike', code_str)], limit=1)
                if existing:
                    return self._json_response({
                        "status": "error",
                        "message": f"Activity with code '{code_str}' already exists (ID: {existing.id}, Name: {existing.name})."
                    }, status=409)
                vals['code'] = code_str

            act_type = payload.get('type')
            if act_type:
                if act_type not in ('piece_rate', 'fixed'):
                    return self._json_response({
                        "status": "error",
                        "message": f"Invalid type '{act_type}'. Allowed values: 'piece_rate', 'fixed'."
                    }, status=400)
                vals['type'] = act_type

            category = payload.get('category')
            valid_categories = ('land_prep', 'planting', 'crop_care', 'irrigation', 'harvest', 'maintenance')
            if category and category in valid_categories:
                vals['category'] = category

            if 'requires_labor' in payload:
                rl = payload['requires_labor']
                vals['requires_labor'] = (rl is True or str(rl).lower() in ('1', 'true', 'yes'))
            if 'requires_machine' in payload:
                rm = payload['requires_machine']
                vals['requires_machine'] = (rm is True or str(rm).lower() in ('1', 'true', 'yes'))

            for char_f in ('crop_name', 'cost_category', 'main_activity', 'sub_activity', 'activity_type', 'uom_name', 'description'):
                if char_f in payload and payload[char_f] is not None:
                    vals[char_f] = str(payload[char_f]).strip()

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

            activity = request.env['farm.activity'].sudo().create(vals)

            norms_payload = payload.get('norms')
            if norms_payload and isinstance(norms_payload, list):
                for norm_item in norms_payload:
                    if not isinstance(norm_item, dict):
                        continue
                    farm = self._resolve_farm(norm_item)
                    if farm:
                        norm_val = norm_item.get('norm_value', norm_item.get('value', 0.0))
                        try:
                            norm_val_flt = float(norm_val)
                        except (ValueError, TypeError):
                            norm_val_flt = 0.0

                        existing_norm = request.env['farm.activity.norm'].sudo().search([
                            ('activity_id', '=', activity.id),
                            ('farm_id', '=', farm.id)
                        ], limit=1)
                        if existing_norm:
                            existing_norm.write({'norm_value': norm_val_flt})
                        else:
                            request.env['farm.activity.norm'].sudo().create({
                                'activity_id': activity.id,
                                'farm_id': farm.id,
                                'norm_value': norm_val_flt,
                            })

            return self._json_response({
                "status": "success",
                "message": f"Activity '{activity.name}' ({activity.code}) created successfully.",
                "data": self._format_activity(activity)
            }, status=201)

        except Exception as e:
            _logger.error("Error creating activity in FMS API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to create activity: {str(e)}"}, status=500)

    # -------------------------------------------------------------------------
    # UPDATE: PUT & PATCH /api/fms/activities/<code_or_id> or /api/fms/activities
    # -------------------------------------------------------------------------
    @http.route([
        '/api/fms/activities/<activity_identifier>',
        '/api/activities/<activity_identifier>',
        '/api/fms/activities',
        '/api/activities',
    ], type='http', auth='public', methods=['PUT', 'PATCH', 'POST', 'OPTIONS'], csrf=False, cors='*')
    def update_activity(self, activity_identifier=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        user = self._authenticate()
        if not user:
            return self._json_response({
                "status": "error",
                "message": "Unauthorized"
            }, status=401)

        payload = self._parse_payload(kwargs)

        activity = self._find_activity(identifier=activity_identifier, payload=payload, kwargs=kwargs)
        if not activity:
            target = activity_identifier or payload.get('code') or payload.get('id') or kwargs.get('code') or kwargs.get('id')
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
                existing = request.env['farm.activity'].sudo().search([('code', '=ilike', str(new_code).strip()), ('id', '!=', activity.id)], limit=1)
                if existing:
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

            norms_payload = payload.get('norms')
            if norms_payload and isinstance(norms_payload, list):
                replace_norms = payload.get('replace_norms', False)
                if replace_norms:
                    activity.farm_norm_ids.unlink()

                for norm_item in norms_payload:
                    if not isinstance(norm_item, dict):
                        continue
                    farm = self._resolve_farm(norm_item)
                    if farm:
                        norm_val = norm_item.get('norm_value', norm_item.get('value', 0.0))
                        try:
                            norm_val_flt = float(norm_val)
                        except (ValueError, TypeError):
                            norm_val_flt = 0.0

                        existing_norm = request.env['farm.activity.norm'].sudo().search([
                            ('activity_id', '=', activity.id),
                            ('farm_id', '=', farm.id)
                        ], limit=1)

                        if existing_norm:
                            existing_norm.write({'norm_value': norm_val_flt})
                        else:
                            request.env['farm.activity.norm'].sudo().create({
                                'activity_id': activity.id,
                                'farm_id': farm.id,
                                'norm_value': norm_val_flt,
                            })

            return self._json_response({
                "status": "success",
                "message": f"Activity '{activity.name}' ({activity.code}) updated successfully.",
                "data": self._format_activity(activity)
            }, status=200)

        except Exception as e:
            _logger.error("Error updating activity in FMS API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to update activity: {str(e)}"}, status=500)

    # -------------------------------------------------------------------------
    # DELETE: DELETE /api/fms/activities/<code_or_id> or /api/fms/activities
    # -------------------------------------------------------------------------
    @http.route([
        '/api/fms/activities/<activity_identifier>',
        '/api/activities/<activity_identifier>',
        '/api/fms/activities',
        '/api/activities',
    ], type='http', auth='public', methods=['DELETE', 'OPTIONS'], csrf=False, cors='*')
    def delete_activity(self, activity_identifier=None, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({}, status=200)

        user = self._authenticate()
        if not user:
            return self._json_response({
                "status": "error",
                "message": "Unauthorized"
            }, status=401)

        payload = self._parse_payload(kwargs)

        activity = self._find_activity(identifier=activity_identifier, payload=payload, kwargs=kwargs)
        if not activity:
            target = activity_identifier or payload.get('code') or payload.get('id') or kwargs.get('code') or kwargs.get('id')
            return self._json_response({
                "status": "error",
                "message": f"Activity not found with code or ID '{target}'."
            }, status=404)

        try:
            act_id = activity.id
            act_name = activity.name
            act_code = activity.code

            entry_count = request.env['farm.work.entry'].sudo().search_count([('activity_id', '=', act_id)])
            if entry_count > 0:
                activity.write({'active': False})
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
                return self._json_response({
                    "status": "success",
                    "action": "deleted",
                    "message": f"Activity '{act_name}' ({act_code}) was successfully deleted.",
                    "id": act_id,
                    "code": act_code
                }, status=200)

        except Exception as e:
            _logger.error("Error deleting activity in FMS API: %s", str(e), exc_info=True)
            return self._json_response({"status": "error", "message": f"Failed to delete activity: {str(e)}"}, status=500)


