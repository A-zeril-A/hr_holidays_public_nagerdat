# Copyright 2024-2025 Isalab Team
# Author: Javad Joudi
# Date: 2025-12-27
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "HR Holidays Public - Nager.Date Sync",
    "summary": """
        Automatically sync public holidays from Nager.Date API
    """,
    "description": """
        This module provides automatic synchronization of public holidays
        from the Nager.Date API (https://date.nager.at/).

        Features:
        - Configurable country code and year range
        - Automatic upsert of holidays (create/update)
        - Scheduled cron job for periodic sync
        - Source tracking field to distinguish auto-synced records
        - Public holidays visible to ALL users in Calendar (not just admin)

        The module is designed to work with calendar_public_holiday
        and hr_holidays_public modules from OCA.
    """,
    "version": "18.0.1.2.0",
    "license": "AGPL-3",
    "category": "Human Resources",
    "author": "Isalab Team",
    "website": "https://github.com/isalab",
    "depends": [
        "calendar_public_holiday",
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

