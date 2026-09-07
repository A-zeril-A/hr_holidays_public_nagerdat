# Copyright 2024-2025 Isalab Team
# Author: A-zeril-A
# Date: 2025-12-27
# License AGPL-3.0 or later (https://github.com/A-zeril-A/hr_holidays_public_nagerdat.git).

{
    "name": "HR Holidays Public - Nager.Date Sync",
    "summary": """
        Sync Nager.Date public holidays into Odoo HR
    """,
    "description": """
        This module synchronizes public holidays from the Nager.Date API
        (https://date.nager.at/) into Odoo.

        Features:
        - Configurable company, country, and year range
        - Automatic upsert of public holidays
        - Scheduled cron job for periodic sync
        - Standard Odoo public holidays synced to resource.calendar.leaves
        - Compatibility sync for the installed OCA public holiday stack
        - Source tracking for imported records
    """,
    "version": "18.0.2.0.2",
    "license": "AGPL-3",
    "category": "Human Resources",
    "author": "Isalab Team",
    "website": "https://github.com/isalab",
    "depends": [
        "calendar_public_holiday",
        "hr_holidays",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "data/ir_cron.xml",
        "views/nagerdate_settings_view.xml",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}

