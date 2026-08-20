# -*- coding: utf-8 -*-
{
    'name': 'Farm Management',
    'version': '18.0.1.0.0',
    'category': 'Human Resources/Farm Management',
    'summary': 'Manage Agricultural Farms, Sub Farms, Sub Units, Blocks, Activities, Transfers, and Work Entries within HR Employees',
    'description': """
Farm Management for Odoo 18 Enterprise
======================================
This module structures agricultural operations directly integrated into the HR Employees ecosystem:
- 4-Tier Hierarchy: Farm -> Sub Farm -> Sub Unit -> Block (1:Many relationships)
- Employee and Supervisor assignments per farm tier
- Sub Unit level field workforce assignment
- Employee Transfer & Movement History with Transfer Date & Moving Date tracking
- Farm Activities management with unique IDs and per-farm target productivity norms
- Farm Work Entries with FMS Employee ID integration and dynamic payment calculation (Score × Norm Rate)
- Smart navigation and integrated chatter/activity tracking
    """,
    'author': 'Custom Development',
    'website': 'https://www.odoo.com',
    'depends': ['base', 'hr', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/farm_views.xml',
        'views/sub_farm_views.xml',
        'views/sub_unit_views.xml',
        'views/block_views.xml',
        'views/activity_views.xml',
        'views/transfer_views.xml',
        'views/work_entry_views.xml',
        'views/hr_employee_views.xml',
        'views/menu_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
