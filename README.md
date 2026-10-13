# Farm Management Module (Odoo 18 Enterprise)

A complete agricultural asset management module integrated into the **HR / Employees** application.

## Hierarchy Architecture
1:Many cascading structure:
```
Farm (farm.farm)
 └── Sub Farm (farm.sub.farm)
      └── Sub Unit (farm.sub.unit)
           └── Block (farm.block)
```

## Features
- **4-Tier Structural Modeling**: Complete tracking of Farms, Sub Farms, Sub Units, and Blocks.
- **HR Employee Assignments**:
  - Assign Farm Managers, Sub Farm Managers, and Sub Unit Supervisors.
  - Assign Field Workers to specific Blocks with dedicated stat counters on the Employee form.
- **Smart Navigation**:
  - Direct stat buttons to jump from Farm $\rightarrow$ Sub Farms $\rightarrow$ Sub Units $\rightarrow$ Blocks.
  - Cascading default contexts when creating sub-units and blocks inside parent forms.
- **Top Bar Integration**:
  - Located directly inside the **Employees** (`hr.menu_hr_root`) top menu navigation.
- **Analytics & Tracking**:
  - Real-time rollup total area calculations and child count statistics.
  - Odoo Chatter integration with activity planning and message logs.
- **Multi-Company & Security**:
  - Record rules for multi-company isolation.
  - Granular access groups: `Farm Management / User` and `Farm Management / Administrator`.
  - Employee Classification Segregation (`CPW`, `Permanent / Farm`, `Temporary`, `Zemach`, `Head Office`).
  - See [SECURITY.md](file:///home/toptech/Downloads/odoo18ent/server/custom_addons/farm_management/SECURITY.md) for complete details.

## Installation & Deployment
1. Add `farm_management` to your Odoo custom addons directory.
2. In Odoo Developer mode, click **Update Apps List**.
3. Search for `Farm Management` and click **Activate / Install**.

---

## 🌐 REST API Endpoints

### 1. Employee Contract Basic Monthly Wage
Retrieve the contract basic monthly wage, salary scale matrix details, grade, step/level, and gross/net wage breakdown.

- **Single Employee**:
  - `GET /api/employees/<employee_code_or_id>/contract_wage`
  - *Example*: `GET /api/employees/CPW001/contract_wage` or `GET /api/employees/6/contract_wage`
  - *Aliases*: `/api/employees/<id>/wage`, `/api/employees/<id>/contract`, `/odoo/api/employees/<id>/contract_wage`

- **All Employees (with filters)**:
  - `GET /api/employees/contract_wage`
  - *Query Parameters*:
    - `employee_id`: filter by employee code or ID (e.g. `?employee_id=CPW001`)
    - `farm`: filter by farm code (e.g. `?farm=FM01`)
    - `type` / `classification`: filter by classification (`cpw`, `head_office`, `permanent`, `temporary`, `zemach`)
    - `has_contract`: `true` or `false`
    - `db`: database name (optional if dynamic discovery or session DB is used)
  - *Aliases*: `/api/contracts/basic_wage`, `/odoo/api/employees/contract_wage`

**Sample Response**:
```json
{
  "status": "success",
  "database": "hpdb18",
  "data": {
    "id": 6,
    "employee_id": "CPW001",
    "name": "Abigail Peterson",
    "classification": "CPW",
    "classification_code": "cpw",
    "job_title": "Senior Auditor",
    "department": "Finance",
    "farm": {
      "id": 1,
      "code": "CPW",
      "name": "Central Processing Workshop"
    },
    "has_active_contract": true,
    "basic_monthly_wage": 7769.0,
    "currency": "ETB",
    "contract": {
      "id": 16,
      "name": "Abigail Peterson Contract",
      "state": "open",
      "is_running": true,
      "date_start": "2024-01-01",
      "date_end": null,
      "basic_monthly_wage": 7769.0,
      "matrix_basic_wage": 7769.0,
      "gross_monthly_wage": 19519.0,
      "estimated_net_wage": 15400.0,
      "currency": "ETB",
      "salary_scale": "CPW Salary Scale - 2018 E.C.",
      "salary_grade": "Grade 14 (ደረጃ 14)",
      "salary_level": "Base (መነሻ)",
      "structure_type": "Farm Worker"
    }
  }
}
```

### 2. Employees Directory
- `GET /api/employees` and `GET /api/employees/<employee_code_or_id>`
  - Now includes `contract_basic_wage` and `has_active_contract` directly on each employee record.

