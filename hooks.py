# Copyright 2024-2025 Isalab Team
# Author: Javad Joudi
# Date: 2025-12-28
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

_logger = logging.getLogger(__name__)

# Partner ID used for public holiday events (Administrator)
# This is the partner that OCA uses as the default event owner
HOLIDAY_PARTNER_ID = 3


def post_init_hook(env):
    """
    Post-installation hook to:
    1. Update existing public holiday calendar events to be public/free
    2. Add Administrator partner to all internal users' calendar filters
       so they can see public holidays in their calendar
    
    Author: Javad Joudi
    Date: 2025-12-28
    """
    _logger.info("Running post_init_hook for hr_holidays_public_nagerdate...")
    
    _update_existing_holiday_events(env)
    _add_holiday_filter_to_users(env)
    
    _logger.info("post_init_hook completed successfully.")


def _update_existing_holiday_events(env):
    """
    Update existing public holiday calendar events to:
    - privacy = 'public' (allows record rule access)
    - show_as = 'free' (doesn't block calendar time)
    """
    HolidayLine = env['calendar.public.holiday.line']
    holiday_lines = HolidayLine.sudo().search([('meeting_id', '!=', False)])
    
    if not holiday_lines:
        _logger.info("No public holiday events found to update.")
        return
    
    meetings = holiday_lines.mapped('meeting_id')
    _logger.info(f"Updating {len(meetings)} public holiday calendar events...")
    
    # Update to public/free but keep existing attendees
    meetings.sudo().write({
        'privacy': 'public',
        'show_as': 'free',
    })
    
    _logger.info(f"Updated {len(meetings)} holiday events to public visibility.")


def _add_holiday_filter_to_users(env):
    """
    Add the holiday partner (Administrator) to all internal users' calendar filters.
    This ensures all users can see public holidays in their Calendar view.
    
    Odoo's calendar filters events based on attendees. By adding the holiday
    partner to each user's filters (with partner_checked=True), holidays become
    visible to everyone.
    """
    CalendarFilters = env['calendar.filters']
    ResUsers = env['res.users']
    
    # Get holiday partner
    holiday_partner = env['res.partner'].sudo().browse(HOLIDAY_PARTNER_ID)
    if not holiday_partner.exists():
        _logger.warning(f"Holiday partner (id={HOLIDAY_PARTNER_ID}) not found!")
        return
    
    # Get all internal users (not portal/public)
    internal_users = ResUsers.sudo().search([
        ('share', '=', False),  # Internal users only
        ('active', '=', True),
    ])
    
    added_count = 0
    for user in internal_users:
        # Check if filter already exists for this user
        existing_filter = CalendarFilters.sudo().search([
            ('user_id', '=', user.id),
            ('partner_id', '=', HOLIDAY_PARTNER_ID),
        ], limit=1)
        
        if not existing_filter:
            # Create new filter with holidays visible (checked)
            CalendarFilters.sudo().create({
                'user_id': user.id,
                'partner_id': HOLIDAY_PARTNER_ID,
                'partner_checked': True,
                'active': True,
            })
            added_count += 1
        elif not existing_filter.partner_checked:
            # Enable the filter if it exists but is unchecked
            existing_filter.sudo().write({'partner_checked': True})
            added_count += 1
    
    _logger.info(
        f"Added/enabled holiday calendar filter for {added_count} users "
        f"(total internal users: {len(internal_users)})"
    )

