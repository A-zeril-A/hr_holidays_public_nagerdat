# Copyright 2024-2025 Isalab Team
# Author: Javad Joudi
# Date: 2025-12-28
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import Command

_logger = logging.getLogger(__name__)


def normalize_nagerdate_holiday_events(env):
    """Keep legacy calendar.event records neutral and non-personal."""
    if "calendar.public.holiday.line" not in env:
        return

    holiday_lines = env["calendar.public.holiday.line"].sudo().search(
        [("source", "=", "nagerdate"), ("meeting_id", "!=", False)]
    )
    if not holiday_lines:
        return

    meetings = holiday_lines.mapped("meeting_id").sudo()
    meetings_to_normalize = meetings.filtered(
        lambda meeting: meeting.user_id
        or meeting.partner_ids
        or meeting.privacy != "confidential"
        or meeting.show_as != "free"
    )
    if not meetings_to_normalize:
        return

    meetings_to_normalize.write(
        {
            "user_id": False,
            "partner_ids": [Command.set([])],
            "privacy": "confidential",
            "show_as": "free",
        }
    )
    _logger.info(
        "Normalized %s Nager.Date holiday meetings.",
        len(meetings_to_normalize),
    )


def normalize_nagerdate_resource_leave_bounds(env):
    """Recompute imported resource leaves with the current timezone policy."""
    if "nagerdate.settings" not in env:
        return

    settings = env["nagerdate.settings"].sudo().with_context(active_test=False).search([])
    if not settings:
        return

    updated = settings.normalize_imported_resource_leave_bounds()
    if updated:
        _logger.info(
            "Normalized %s Nager.Date resource calendar leaves.",
            len(updated),
        )


def normalize_hr_holidays_public_menu(env):
    """
    Hide the OCA public holiday menu from the Time Off configuration menu.

    Once standard Odoo public holidays are used as the HR source of truth, the
    OCA catalog is kept only as a compatibility layer for installed consumers.
    Leaving both menus visible in Time Off is confusing because users see two
    different "Public Holidays" entries backed by different models.
    """
    menu_xmlids = [
        "hr_holidays_public.menu_hr_public_holidays",
        "hr_holidays_public.menu_holidays_public_view",
        "hr_holidays_public.menu_create_next_year_public_holidays",
    ]
    menus = env["ir.ui.menu"].browse()
    for xmlid in menu_xmlids:
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menus |= menu
    active_menus = menus.filtered("active")
    if active_menus:
        active_menus.sudo().write({"active": False})
        _logger.info(
            "Disabled %s OCA Public Holidays menu entries in Time Off.",
            len(active_menus),
        )


def post_init_hook(env):
    _logger.info("Running post_init_hook for hr_holidays_public_nagerdate...")
    normalize_nagerdate_holiday_events(env)
    normalize_nagerdate_resource_leave_bounds(env)
    normalize_hr_holidays_public_menu(env)
    _logger.info("post_init_hook completed successfully.")

