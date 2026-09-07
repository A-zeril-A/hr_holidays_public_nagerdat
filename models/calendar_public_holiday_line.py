# Copyright 2024-2025 Isalab Team
# Author: Javad Joudi
# Date: 2025-12-27
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import Command, fields, models


class CalendarPublicHolidayLine(models.Model):
    """
    Extend the OCA public holiday line with Nager.Date metadata.

    The linked calendar.event is intentionally kept as a neutral side effect of
    calendar_public_holiday. Standard employee visibility is handled in Time Off
    through resource.calendar.leaves, not through the Calendar app.
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
        Keep generated calendar events neutral.

        The OCA stack still creates calendar.event records for public holiday
        lines. We clear the organizer/attendees so these technical events do not
        leak into personal calendars or Outlook synchronization.
        """
        vals = super()._prepare_holidays_meeting_values()
        vals.update(
            {
                "user_id": False,
                "partner_ids": [Command.set([])],
                "privacy": "confidential",
                "show_as": "free",
            }
        )
        return vals

