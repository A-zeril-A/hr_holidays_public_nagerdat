from datetime import datetime

import pytz

from odoo import api, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    @api.model
    def get_public_holidays_data(self, date_start, date_end):
        """
        Use the standard Odoo public holiday source in Time Off.

        The OCA public holiday stack also injects `calendar.public.holiday.line`
        records into the same sidebar payload. That is useful for compatibility,
        but in this project `resource.calendar.leaves` is the source of truth for
        HR and Time Off. We therefore build the sidebar from the standard model
        only, and normalize imported Nager.Date holidays to a single-day display
        using their original calendar date.
        """
        employee = self._get_contextual_employee()
        employee_tz = pytz.timezone(
            employee._get_tz() if employee else self.env.user.tz or "utc"
        )
        public_holidays = employee._get_public_holidays(date_start, date_end).sorted(
            "date_from"
        )
        deduplicated = []
        seen_intervals = set()
        for public_holiday in public_holidays:
            if (
                public_holiday.source == "nagerdate"
                and public_holiday.nagerdate_holiday_date
            ):
                start_date = public_holiday.nagerdate_holiday_date
                end_date = public_holiday.nagerdate_holiday_date
            else:
                start_date = public_holiday.date_from.astimezone(employee_tz).date()
                end_date = public_holiday.date_to.astimezone(employee_tz).date()

            holiday = {
                "id": -public_holiday.id,
                "colorIndex": 0,
                "end": datetime.combine(end_date, datetime.max.time()).isoformat(),
                "endType": "datetime",
                "isAllDay": True,
                "start": datetime.combine(
                    start_date, datetime.min.time()
                ).isoformat(),
                "startType": "datetime",
                "title": public_holiday.name,
            }
            interval_key = (
                holiday["title"],
                holiday["start"],
                holiday["end"],
            )
            if interval_key in seen_intervals:
                continue
            seen_intervals.add(interval_key)
            deduplicated.append(holiday)
        return deduplicated
