from datetime import date, datetime
from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestNagerDateSync(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "NagerDate Test Company"})
        cls.country = cls.env["res.country"].search([("code", "=", "XN")], limit=1)
        if not cls.country:
            cls.country = cls.env["res.country"].create(
                {"name": "NagerDate Test Country", "code": "XN"}
            )
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "Italy Schedule",
                "company_id": cls.company.id,
                "tz": "Europe/Rome",
                "hours_per_day": 8.0,
            }
        )
        cls.setting = cls.env["nagerdate.settings"].create(
            {
                "company_id": cls.company.id,
                "country_id": cls.country.id,
                "country_code": "XN",
                "years_back": 0,
                "years_ahead": 0,
                "resource_calendar_ids": [(6, 0, cls.calendar.ids)],
            }
        )

    def _sync(self, payload, year=2026):
        with patch.object(
            type(self.setting), "_fetch_holidays_from_api", return_value=payload
        ):
            return self.setting.sync_year(year)

    def test_sync_year_creates_standard_and_oca_records(self):
        count = self._sync(
            [
                {
                    "date": "2026-01-06",
                    "localName": "Epifania",
                    "name": "Epiphany",
                    "types": ["Public"],
                }
            ]
        )

        self.assertEqual(count, 1)

        holiday_year = self.env["calendar.public.holiday"].search(
            [("year", "=", 2026), ("country_id", "=", self.country.id)], limit=1
        )
        holiday_line = self.env["calendar.public.holiday.line"].search(
            [
                ("public_holiday_id", "=", holiday_year.id),
                ("date", "=", date(2026, 1, 6)),
                ("source", "=", "nagerdate"),
            ],
            limit=1,
        )
        self.assertTrue(holiday_line)
        self.assertEqual(holiday_line.name, "Epifania")
        self.assertFalse(holiday_line.meeting_id.user_id)
        self.assertFalse(holiday_line.meeting_id.partner_ids)

        resource_leave = self.env["resource.calendar.leaves"].search(
            [
                ("nagerdate_setting_id", "=", self.setting.id),
                ("nagerdate_holiday_date", "=", date(2026, 1, 6)),
                ("calendar_id", "=", self.calendar.id),
                ("source", "=", "nagerdate"),
            ],
            limit=1,
        )
        self.assertTrue(resource_leave)
        self.assertEqual(resource_leave.name, "Epifania")
        self.assertEqual(resource_leave.nagerdate_types, "Public")

    def test_sync_year_updates_legacy_resource_leaves_and_cleans_stale_imports(self):
        current_date = date(2026, 1, 6)
        stale_date = date(2026, 5, 1)
        current_bounds = self.setting._get_resource_leave_datetimes(
            current_date, self.calendar, self.company
        )
        stale_bounds = self.setting._get_resource_leave_datetimes(
            stale_date, self.calendar, self.company
        )

        legacy_leave = (
            self.env["resource.calendar.leaves"]
            .sudo()
            .with_company(self.company)
            .create(
                {
                    "name": "[Nager.Date] Epifania",
                    "calendar_id": self.calendar.id,
                    "date_from": current_bounds[0],
                    "date_to": current_bounds[1],
                    "resource_id": False,
                    "time_type": "leave",
                }
            )
        )
        stale_leave = (
            self.env["resource.calendar.leaves"]
            .sudo()
            .with_company(self.company)
            .create(
                {
                    "name": "Stale Holiday",
                    "calendar_id": self.calendar.id,
                    "date_from": stale_bounds[0],
                    "date_to": stale_bounds[1],
                    "resource_id": False,
                    "time_type": "leave",
                    "source": "nagerdate",
                    "nagerdate_setting_id": self.setting.id,
                    "nagerdate_holiday_date": stale_date,
                }
            )
        )

        self._sync(
            [
                {
                    "date": "2026-01-06",
                    "localName": "Epifania",
                    "name": "Epiphany",
                    "types": ["Public"],
                }
            ]
        )

        migrated_leave = self.env["resource.calendar.leaves"].browse(legacy_leave.id)
        self.assertTrue(migrated_leave.exists())
        self.assertEqual(migrated_leave.source, "nagerdate")
        self.assertEqual(migrated_leave.name, "Epifania")
        self.assertEqual(migrated_leave.nagerdate_setting_id, self.setting)
        self.assertEqual(migrated_leave.nagerdate_holiday_date, current_date)
        self.assertFalse(stale_leave.exists())

    def test_sync_year_skips_and_cleans_non_global_holidays(self):
        holiday_year = self.setting._get_or_create_public_holiday_year(2026)
        regional_date = date(2026, 5, 25)
        date_from, date_to = self.setting._get_resource_leave_datetimes(
            regional_date, self.calendar, self.company
        )

        regional_line = self.env["calendar.public.holiday.line"].create(
            {
                "name": "Lunedi di Pentecoste",
                "date": regional_date,
                "public_holiday_id": holiday_year.id,
                "source": "nagerdate",
                "nagerdate_types": "Public",
            }
        )
        regional_leave = self.env["resource.calendar.leaves"].with_company(
            self.company
        ).create(
            {
                "name": "Lunedi di Pentecoste",
                "calendar_id": self.calendar.id,
                "date_from": date_from,
                "date_to": date_to,
                "resource_id": False,
                "time_type": "leave",
                "source": "nagerdate",
                "nagerdate_setting_id": self.setting.id,
                "nagerdate_holiday_date": regional_date,
                "nagerdate_types": "Public",
            }
        )

        count = self._sync(
            [
                {
                    "date": "2026-05-25",
                    "localName": "Lunedi di Pentecoste",
                    "name": "Whit Monday",
                    "global": False,
                    "counties": ["IT-32"],
                    "types": ["Public"],
                }
            ]
        )

        self.assertEqual(count, 0)
        self.assertFalse(regional_line.exists())
        self.assertFalse(regional_leave.exists())

    def test_cleanup_unsupported_imported_holidays_removes_legacy_regional_records(self):
        holiday_year = self.setting._get_or_create_public_holiday_year(2026)
        regional_date = date(2026, 5, 25)
        date_from, date_to = self.setting._get_resource_leave_datetimes(
            regional_date, self.calendar, self.company
        )

        regional_line = self.env["calendar.public.holiday.line"].create(
            {
                "name": "Lunedi di Pentecoste",
                "date": regional_date,
                "public_holiday_id": holiday_year.id,
                "source": "nagerdate",
                "nagerdate_types": "Public",
            }
        )
        regional_leave = self.env["resource.calendar.leaves"].with_company(
            self.company
        ).create(
            {
                "name": "Lunedi di Pentecoste",
                "calendar_id": self.calendar.id,
                "date_from": date_from,
                "date_to": date_to,
                "resource_id": False,
                "time_type": "leave",
                "source": "nagerdate",
                "nagerdate_setting_id": self.setting.id,
                "nagerdate_holiday_date": regional_date,
                "nagerdate_types": "Public",
            }
        )

        result = self.setting.cleanup_unsupported_imported_holidays(
            2026,
            holidays_data=[
                {
                    "date": "2026-05-25",
                    "localName": "Lunedi di Pentecoste",
                    "name": "Whit Monday",
                    "global": False,
                    "counties": ["IT-32"],
                    "types": ["Public"],
                }
            ],
        )

        self.assertFalse(result["skipped"])
        self.assertEqual(
            result["calendar_public_holiday_lines"],
            1,
        )
        self.assertEqual(result["resource_calendar_leaves"], 1)
        self.assertEqual(result["unsupported_dates"], {regional_date})
        self.assertFalse(regional_line.exists())
        self.assertFalse(regional_leave.exists())

    def test_sync_year_skips_manual_conflicts(self):
        holiday_year = self.setting._get_or_create_public_holiday_year(2026)
        self.env["calendar.public.holiday.line"].create(
            {
                "name": "Manual Holiday",
                "date": "2026-01-06",
                "public_holiday_id": holiday_year.id,
            }
        )

        date_from, date_to = self.setting._get_resource_leave_datetimes(
            date(2026, 1, 6), self.calendar, self.company
        )
        self.env["resource.calendar.leaves"].with_company(self.company).create(
            {
                "name": "Manual Public Holiday",
                "calendar_id": self.calendar.id,
                "date_from": date_from,
                "date_to": date_to,
                "resource_id": False,
                "time_type": "leave",
            }
        )

        self._sync(
            [
                {
                    "date": "2026-01-06",
                    "localName": "Epifania",
                    "name": "Epiphany",
                    "types": ["Public"],
                }
            ]
        )

        self.assertFalse(
            self.env["calendar.public.holiday.line"].search_count(
                [
                    ("public_holiday_id", "=", holiday_year.id),
                    ("date", "=", date(2026, 1, 6)),
                    ("source", "=", "nagerdate"),
                ]
            )
        )

    def test_time_off_sidebar_uses_single_standard_entry_per_holiday(self):
        utc_calendar = self.env["resource.calendar"].create(
            {
                "name": "UTC Company Schedule",
                "company_id": self.company.id,
                "tz": "UTC",
                "hours_per_day": 8.0,
            }
        )
        self.company.resource_calendar_id = utc_calendar
        self.setting.resource_calendar_ids = [(6, 0, [])]
        employee = self.env["hr.employee"].create(
            {
                "name": "Time Off User",
                "company_id": self.company.id,
                "resource_calendar_id": self.calendar.id,
            }
        )

        self._sync(
            [
                {
                    "date": "2026-01-06",
                    "localName": "Epifania",
                    "name": "Epiphany",
                    "types": ["Public"],
                }
            ]
        )

        holidays = (
            self.env["hr.employee"]
            .with_company(self.company)
            .with_context(employee_id=employee.id, allowed_company_ids=[self.company.id])
            .get_public_holidays_data("2026-01-01", "2026-12-31")
        )

        self.assertEqual(len(holidays), 1)
        self.assertEqual(holidays[0]["title"], "Epifania")
        self.assertEqual(holidays[0]["start"], "2026-01-06T00:00:00")
        self.assertEqual(holidays[0]["end"], "2026-01-06T23:59:59.999999")
        self.assertFalse(
            self.env["resource.calendar.leaves"].search_count(
                [
                    ("nagerdate_setting_id", "=", self.setting.id),
                    ("nagerdate_holiday_date", "=", date(2026, 1, 6)),
                    ("calendar_id", "=", self.calendar.id),
                    ("source", "=", "nagerdate"),
                ]
            )
        )

    def test_company_wide_italian_holiday_uses_country_timezone(self):
        italy = self.env["res.country"].search([("code", "=", "IT")], limit=1)
        utc_calendar = self.env["resource.calendar"].create(
            {
                "name": "UTC Company Calendar",
                "company_id": self.company.id,
                "tz": "UTC",
                "hours_per_day": 8.0,
            }
        )
        self.company.resource_calendar_id = utc_calendar
        self.setting.write(
            {
                "country_id": italy.id,
                "country_code": "IT",
                "resource_calendar_ids": [(6, 0, [])],
            }
        )

        date_from, date_to = self.setting._get_resource_leave_datetimes(
            date(2026, 6, 2),
            False,
            self.company,
        )

        self.assertEqual(date_from, datetime(2026, 6, 1, 22, 0, 0))
        self.assertEqual(date_to, datetime(2026, 6, 2, 21, 59, 59))

    def test_normalize_imported_resource_leave_bounds_updates_old_utc_bounds(self):
        italy = self.env["res.country"].search([("code", "=", "IT")], limit=1)
        utc_calendar = self.env["resource.calendar"].create(
            {
                "name": "UTC Normalize Calendar",
                "company_id": self.company.id,
                "tz": "UTC",
                "hours_per_day": 8.0,
            }
        )
        self.company.resource_calendar_id = utc_calendar
        self.setting.write(
            {
                "country_id": italy.id,
                "country_code": "IT",
                "resource_calendar_ids": [(6, 0, [])],
            }
        )
        leave = self.env["resource.calendar.leaves"].with_company(self.company).create(
            {
                "name": "Festa della Repubblica",
                "date_from": datetime(2026, 6, 2, 0, 0, 0),
                "date_to": datetime(2026, 6, 2, 23, 59, 59),
                "resource_id": False,
                "calendar_id": False,
                "company_id": self.company.id,
                "time_type": "leave",
                "source": "nagerdate",
                "nagerdate_setting_id": self.setting.id,
                "nagerdate_holiday_date": date(2026, 6, 2),
            }
        )

        updated = self.setting.normalize_imported_resource_leave_bounds()

        self.assertIn(leave, updated)
        self.assertEqual(leave.date_from, datetime(2026, 6, 1, 22, 0, 0))
        self.assertEqual(leave.date_to, datetime(2026, 6, 2, 21, 59, 59))
