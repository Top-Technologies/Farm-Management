# -*- coding: utf-8 -*-
{
    'name': 'Farm Management',
    'version': '1.0.0',
    'category': 'Human Resources/Farm Management',
    'summary': 'Manage Agricultural Farms, Sub Farms, Sub Units, Blocks, Activities, Temporary Worker Rates, Transfers, Work Entries, and Batch Payroll within HR Employees',
    'description': """
Farm Management for Odoo 18 & 19 Enterprise
============================================
This module structures agricultural operations directly integrated into the HR Employees and Payroll ecosystem:
- 4-Tier Hierarchy: Farm -> Sub Farm -> Sub Unit -> Block (1:Many relationships)
- Employee and Supervisor assignments per farm tier
- Sub Unit level field workforce assignment
- Employee Classification (Permanent, Temporary, Zemach) & Auto-generated 3-part ID (e.g. FM01T0001)
- Employee Transfer & Movement History with Transfer Date & Moving Date tracking
- Farm Activities management with unique IDs and per-farm target productivity norms (Piece-Rate)
- Temporary Worker Wage Rates with Full Day (1.0) and Half Day (0.5) daily fixed rates per farm
- Farm Work Entries with FMS Employee ID integration and dynamic payment calculation
- Direct Payroll Integration (hr_payroll):
  * Automatic aggregation of unpaid work entries for Temporary and Seasonal (Zemach) workers in Payslip Batches
  * Worker classification filtering on batch generation (Temporary, Seasonal/Zemach, Permanent, All)
  * Dedicated agricultural salary structures & rules (TEMP_WAGE, PIECE_RATE)
  * Automatic payment status transitions (Unpaid -> In Payroll -> Paid) upon payslip validation
- RESTful JSON API endpoints for external FMS system synchronization
- Smart navigation and integrated chatter/activity tracking
    """,
    'author': 'Custom Development',
    'website': 'https://www.odoo.com',
    'depends': ['base', 'hr', 'mail', 'hr_payroll', 'hr_work_entry_contract_enterprise'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/hr_payroll_data.xml',
        'views/farm_views.xml',
        'views/sub_farm_views.xml',
        'views/sub_unit_views.xml',
        'views/block_views.xml',
        'views/activity_views.xml',
        'views/temporary_rate_views.xml',
        'views/transfer_views.xml',
        'views/work_entry_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_contract_views.xml',
        'views/hr_payslip_views.xml',
        'views/salary_matrix_views.xml',
        'views/menu_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
}
