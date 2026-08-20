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

## Installation & Deployment
1. Add `farm_management` to your Odoo custom addons directory.
2. In Odoo Developer mode, click **Update Apps List**.
3. Search for `Farm Management` and click **Activate / Install**.
