# Security & Access Rights Documentation — Farm Management

## 1. Overview
The **Farm Management** (`farm_management`) module implements a granular security and access control architecture for agricultural operations, workforce classification segregation, multi-company isolation, and payroll integration in Odoo 18 Enterprise.

---

## 2. Security Roles & Categories

### A. Module Roles (Category: `Farm Management`)
Defined in [`security/security.xml`](file:///home/toptech/Downloads/odoo18ent/server/custom_addons/farm_management/security/security.xml).

| Group XML ID | Group Name | Description |
| :--- | :--- | :--- |
| `group_farm_user` | **User** | Field supervisors and operational staff who record farm work entries, transfers, and view agricultural structures. |
| `group_farm_manager` | **Administrator** | Full configuration and administrative rights across farm structures, norms, matrix scales, and payroll imports. Automatically inherits `group_farm_user` and `hr.group_hr_user`. Assigned by default to `base.user_root` and `base.user_admin`. |

### B. Employee Classification Segregation (Category: `Employee Classification Access`)
Enables strict separation so that HR officers, farm managers, and CPW accountants only see the employees, contracts, and payslips matching their assigned classification.

| Group XML ID | Group Name | Accessible Employee Classification (`farm_employee_type`) |
| :--- | :--- | :--- |
| `group_employee_classification_all` | **All Classifications** | Full unrestricted visibility across all 5 classifications. Assigned to `base.user_root` and `base.user_admin`. |
| `group_employee_classification_cpw` | **CPW** | Central Processing Workshop (`cpw`) employees. |
| `group_employee_classification_farm` | **Farm (Permanent / የእርሻ)** | Permanent farm staff (`permanent`). |
| `group_employee_classification_temporary` | **Temporary (ጊዜያዊ)** | Temporary daily wage farm workers (`temporary`). |
| `group_employee_classification_zemach` | **Zemach / Seasonal (ዘመች)** | Piece-rate seasonal harvesting workers (`zemach`). |
| `group_employee_classification_head_office` | **Head Office (ዋና መ/ቤት)** | Corporate / Head Office permanent employees (`head_office`). |
| `group_employee_classification_general` | **General (Legacy)** | Backward-compatible group granting access to `head_office`, `permanent`, `temporary`, and `zemach`. |

---

## 3. Dynamic Python Security Resolvers (`models/res_users.py`)
To avoid hardcoding or brittle group lookups, [`models/res_users.py`](file:///home/toptech/Downloads/odoo18ent/server/custom_addons/farm_management/models/res_users.py) provides four central security methods:

1. **`_has_farm_group(xml_name)`**:
   - Resolves group membership reliably across different folder naming schemes on disk (`farm_management`, `Farm-Management`, or `Farm_Management`).
2. **`_get_allowed_farm_employee_types()`**:
   - Dynamically returns the list of allowed `farm_employee_type` values for the user.
   - Evaluated live in record rules for `hr.employee`, `hr.employee.public`, `hr.contract`, `hr.payslip`, and `farm.work.entry`.
3. **`_get_allowed_salary_matrix_types()`**:
   - Returns allowed salary scale types (`['head_office', 'farm', 'saudi_star', 'cpw', 'other']`).
   - Controls visibility of salary matrix sheets.
4. **`_get_allowed_payslip_run_classifications()`**:
   - Restricts which payslip batches (`hr.payslip.run`) the user can view or generate based on `worker_type`.

---

## 4. Record Rules (`security/security.xml`)

### A. Classification Segregation Rules (Global: `global=True`)
Global rules apply to all users to strictly partition workforce data:

| Rule XML ID | Target Model | Domain Expression |
| :--- | :--- | :--- |
| `hr_employee_classification_rule` | `hr.employee` | `['\|', ('user_id', '=', user.id), ('farm_employee_type', 'in', user._get_allowed_farm_employee_types())]` |
| `hr_employee_public_classification_rule` | `hr.employee.public` | `['\|', ('user_id', '=', user.id), ('farm_employee_type', 'in', user._get_allowed_farm_employee_types())]` |
| `hr_contract_classification_rule` | `hr.contract` | `['\|', ('employee_id.user_id', '=', user.id), ('farm_employee_type', 'in', user._get_allowed_farm_employee_types())]` |
| `hr_payslip_classification_rule` | `hr.payslip` | `['\|', ('employee_id.user_id', '=', user.id), ('farm_employee_type', 'in', user._get_allowed_farm_employee_types())]` |
| `hr_payslip_run_classification_rule` | `hr.payslip.run` | `[('worker_type', 'in', user._get_allowed_payslip_run_classifications())]` |
| `farm_work_entry_classification_rule` | `farm.work.entry` | `['\|', ('employee_id.user_id', '=', user.id), ('employee_type', 'in', user._get_allowed_farm_employee_types())]` |
| `hr_salary_matrix_classification_rule` | `hr.salary.matrix` | `[('matrix_type', 'in', user._get_allowed_salary_matrix_types())]` |

*Self-Service Exception*: Employees can always view their own employee record, contract, payslip, and work entries (`('user_id', '=', user.id)`).

### B. Multi-Company Isolation Rules (`noupdate="1"`)
Ensures agricultural entities are strictly partitioned across multi-company deployments:
- `farm.farm`, `farm.sub.farm`, `farm.sub.unit`, `farm.block`
- `farm.activity`, `farm.activity.norm`
- `farm.employee.transfer`, `farm.work.entry`
- `hr.salary.matrix`, `hr.employee.family.member`

Each rule enforces:
```python
[('company_id', 'in', company_ids)]
```

---

## 5. Model Access Permissions (`security/ir.model.access.csv`)
Defined in [`security/ir.model.access.csv`](file:///home/toptech/Downloads/odoo18ent/server/custom_addons/farm_management/security/ir.model.access.csv):

| Model | User Group | Read | Write | Create | Unlink |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `farm.farm` | User / Manager | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✗ / ✓ |
| `farm.sub.farm` | User / Manager | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✗ / ✓ |
| `farm.sub.unit` | User / Manager | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✗ / ✓ |
| `farm.block` | User / Manager | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✗ / ✓ |
| `farm.activity` | User / Manager | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✗ / ✓ |
| `farm.activity.norm` | User / Manager | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✗ / ✓ |
| `farm.employee.transfer` | User / Manager | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✗ / ✓ |
| `farm.work.entry` | User / Manager | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✗ / ✓ |
| `hr.salary.matrix` | User / Manager | ✓ / ✓ | ✗ / ✓ | ✗ / ✓ | ✗ / ✓ |
| `hr.salary.matrix.line` | User / Manager | ✓ / ✓ | ✗ / ✓ | ✗ / ✓ | ✗ / ✓ |
| `hr.salary.matrix` (CPW) | CPW Classification Group | ✓ | ✗ | ✗ | ✗ |
| `hr.employee.family.member` | Base User / Manager | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| `hr.salary.matrix.grade` | Base User / Manager | ✓ / ✓ | ✗ / ✓ | ✗ / ✓ | ✗ / ✓ |
| `approval.location` | Base User / Approval Mgr / Farm Mgr | ✓ / ✓ / ✓ | ✗ / ✓ / ✓ | ✗ / ✓ / ✓ | ✗ / ✓ / ✓ |
| `approval.location.approver`| Base User / Approval Mgr / Farm Mgr | ✓ / ✓ / ✓ | ✗ / ✓ / ✓ | ✗ / ✓ / ✓ | ✗ / ✓ / ✓ |
| `farm.data.import.wizard` | User / Manager | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| `hr.salary.attachment.schedule` | Base User / Farm Manager | ✓ / ✓ | ✗ / ✓ | ✗ / ✓ | ✗ / ✓ |
| `hr.salary.attachment.adjust.wizard` | Base User / Farm Manager | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| `hr.payroll.structure.copy.rules` | Base User | ✓ | ✓ | ✓ | ✓ |

---

## 6. Payroll Structure & Multi-Company Troubleshooting (`hr.payroll.structure`)

### A. Record Rule Specification
The standard Odoo Enterprise Payroll module applies a multi-company rule on salary structures:

* **Target Model**: `hr.payroll.structure` (Salary Structure)
* **Rule Name**: `HR Payroll Structure: Multi Company`
* **XML ID**: `hr_payroll.ir_rule_hr_payroll_structure_multi_company`
* **Domain Filter**:
  ```python
  ['|', ('country_id', '=', False), ('country_id', 'in', user.env.companies.mapped('country_id').ids)]
  ```

### B. "Salary Structure, False" Access Error Diagnosis
When saving or viewing an employee contract, batch payslip, or work entry, the following error may occur:
> *Access Error: Mitchell Admin doesn't have 'read' access to: Salary Structure, False (hr.payroll.structure: 5). Blame the following rules: HR Payroll Structure: Multi Company.*

This is triggered by one of the following root causes:
1. **Archived Structure Reference**: The structure (`id=5`) was archived (`active = False`), causing Odoo's name computation to evaluate to `False`. When contracts or payroll wizards reference an archived structure, relational reads violate the access rule.
2. **Missing Country on Company**: The active company (`res.company`) has no country set (`country_id = False`). As a result, any structure linked to a country fails the domain check.
3. **Multi-Company Mismatch**: The active user is currently switched into a company whose country does not match the structure's country.

### C. Resolution Steps (Odoo UI / Configuration — No Code Changes)

1. **Unarchive the Salary Structure**:
   - Navigate to: **Payroll** $\rightarrow$ **Configuration** $\rightarrow$ **Salary Structures**.
   - Clear the default **Active** search filter and select the **Archived** filter.
   - Open the affected structure (e.g. structure ID 5) and click **Action** $\rightarrow$ **Unarchive**.

2. **Verify Company Country**:
   - Navigate to: **Settings** $\rightarrow$ **Users & Companies** $\rightarrow$ **Companies**.
   - Open the active company and verify that the **Country** field is properly set (e.g., *Ethiopia*, *United States*, etc.).

3. **Re-select Active Structure on the Record**:
   - Click **Discard changes** on the error dialog.
   - On the Contract or Employee form, clear the structure field and re-select the current active structure.

4. **Adjust Record Rule (Developer Mode)**:
   - Navigate to: **Settings** $\rightarrow$ **Technical** $\rightarrow$ **Security** $\rightarrow$ **Record Rules**.
   - Filter by Model: `hr.payroll.structure`.
   - Open **HR Payroll Structure: Multi Company**.
   - If structures are shared across countries/companies, deactivate the rule or adjust the domain to `[(1, '=', 1)]`.

