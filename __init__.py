# -*- coding: utf-8 -*-
from . import controllers
from . import models


def post_init_hook(env):
    """
    After install: ensure all Odoo system administrators are assigned to the
    Farm Management / Administrator group so they have immediate access.
    Also reset noupdate flags so future upgrades can re-apply group data.
    """
    farm_manager_group = env.ref('Farm_Management.group_farm_manager', raise_if_not_found=False)
    if not farm_manager_group:
        return

    # Add all internal admin users (group_system = Settings / Technical Features)
    system_group = env.ref('base.group_system', raise_if_not_found=False)
    if system_group:
        for user in system_group.users:
            if user.active and user not in farm_manager_group.users:
                farm_manager_group.users = [(4, user.id)]

    # Explicitly ensure base admin users are included
    for xml_id in ('base.user_admin', 'base.user_root'):
        user = env.ref(xml_id, raise_if_not_found=False)
        if user and user not in farm_manager_group.users:
            farm_manager_group.users = [(4, user.id)]

    # Reset noupdate so future -u upgrades can re-apply group records
    env.cr.execute("""
        UPDATE ir_model_data
        SET noupdate = false
        WHERE module = 'Farm_Management'
        AND name IN ('group_farm_user', 'group_farm_manager', 'module_category_farm')
    """)

    # Initialize all 3 standard salary scales (Head Office, CPW, Farm Permanent)
    try:
        env['hr.salary.matrix'].load_default_matrices()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to initialize default salary matrices: %s", str(e))
