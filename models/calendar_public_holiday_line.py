# Copyright 2024-2025 Isalab Team
# Author: Javad Joudi
# Date: 2025-12-27
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class CalendarPublicHolidayLine(models.Model):
    """
    Extends calendar.public.holiday.line to:
    1. Add source tracking field for Nager.Date synced holidays
    2. Override calendar event creation to make holidays visible to all users
    """
    _inherit = "calendar.public.holiday.line"

    source = fields.Selection(
        selection=[
            ("manual", "Manual"),
            ("nagerdate", "Nager.Date API"),
        ],
        string="Source",
        default="manual",
        help="Indicates the origin of this holiday record. "
             "'Manual' for user-created records, "
             "'Nager.Date API' for auto-synced records.",
        index=True,
    )
    nagerdate_types = fields.Char(
        string="Holiday Types",
        help="Holiday type categories from Nager.Date API "
             "(e.g., Public, Bank, School, etc.)",
    )

    def _prepare_holidays_meeting_values(self):
        """
        Override to set public visibility for calendar events.
        
        Changes from original OCA implementation:
        - privacy: 'public' instead of 'confidential' (allows record rule access)
        - show_as: 'free' instead of 'busy' (holidays don't block calendar time)
        
        We keep the original user_id and partner_ids (attendees) so that:
        1. Events appear in Admin's calendar (who is the default attendee)
        2. Other users can add Admin to their calendar filters to see holidays
        
        Author: Javad Joudi
        Date: 2025-12-28
        """
        # Call parent to get base values
        vals = super()._prepare_holidays_meeting_values()
        
        # Only override privacy and show_as, keep attendees intact
        vals.update({
            "privacy": "public",      # Everyone can READ (via record rule)
            "show_as": "free",        # Don't block calendar time slots
        })
        
        return vals

