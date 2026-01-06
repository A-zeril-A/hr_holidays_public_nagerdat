# Copyright 2024-2025 Isalab Team
# Author: AI Assistant <ai@isalab.com>
# Date: 2025-12-27
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from datetime import date, datetime, timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Nager.Date API base URL template
NAGERDATE_API_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/{country_code}"


class NagerDateSettings(models.Model):
    """
    Configuration model for Nager.Date public holidays sync.
    Allows configuring country, year range, and sync behavior.
    """
    _name = "nagerdate.settings"
    _description = "Nager.Date Sync Settings"
    _rec_name = "country_id"

    country_id = fields.Many2one(
        comodel_name="res.country",
        string="Country",
        required=True,
        help="Country for which to sync public holidays",
    )
    country_code = fields.Char(
        string="Country Code",
        size=2,
        required=True,
        default="IT",
        help="ISO 3166-1 alpha-2 country code (e.g., IT, DE, FR, US)",
    )
    years_ahead = fields.Integer(
        string="Years Ahead",
        default=2,
        help="Number of years ahead to sync (from current year)",
    )
    years_back = fields.Integer(
        string="Years Back",
        default=1,
        help="Number of years back to sync (from current year)",
    )
    auto_sync_enabled = fields.Boolean(
        string="Auto Sync Enabled",
        default=True,
        help="Enable automatic synchronization via scheduled action",
    )
    last_sync_date = fields.Datetime(
        string="Last Sync Date",
        readonly=True,
        help="Date and time of the last successful sync",
    )
    api_base_url = fields.Char(
        string="API Base URL",
        default="https://date.nager.at/api/v3/PublicHolidays",
        help="Base URL for the Nager.Date API",
    )
    sync_to_resource_calendar = fields.Boolean(
        string="Sync to Resource Calendar Leaves",
        default=False,
        help="WARNING: May cause duplicates! Only enable if NOT using OCA modules.\n"
             "When enabled, syncs to resource.calendar.leaves (standard Odoo model).\n"
             "If using calendar_public_holiday (OCA), leave this DISABLED.",
    )
    resource_calendar_ids = fields.Many2many(
        comodel_name="resource.calendar",
        string="Resource Calendars",
        help="Specific resource calendars to add holidays to. "
             "Leave empty to add as global holidays (all calendars)",
    )

    _sql_constraints = [
        (
            "country_unique",
            "UNIQUE(country_id)",
            "A settings record for this country already exists!",
        ),
    ]

    @api.model
    def _get_api_url(self, year, country_code):
        """
        Build the API URL for fetching holidays.

        Args:
            year: The year to fetch holidays for
            country_code: ISO country code

        Returns:
            str: Full API URL
        """
        return NAGERDATE_API_URL.format(year=year, country_code=country_code)

    def _fetch_holidays_from_api(self, year):
        """
        Fetch holidays from Nager.Date API for a specific year.

        Args:
            year: The year to fetch holidays for

        Returns:
            list: List of holiday dictionaries or empty list on error
        """
        self.ensure_one()
        url = self._get_api_url(year, self.country_code)
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            _logger.warning(
                "Nager.Date API timeout for year %s, country %s",
                year, self.country_code
            )
            return []
        except requests.exceptions.RequestException as e:
            _logger.warning(
                "Nager.Date API error for year %s, country %s: %s",
                year, self.country_code, str(e)
            )
            return []
        except ValueError as e:
            _logger.warning(
                "Nager.Date API JSON parse error for year %s, country %s: %s",
                year, self.country_code, str(e)
            )
            return []

    def _get_or_create_public_holiday_year(self, year):
        """
        Get or create the calendar.public.holiday record for a year/country.
        Uses sudo() to bypass access rules for system operations.

        Args:
            year: The year

        Returns:
            recordset: calendar.public.holiday record
        """
        self.ensure_one()
        # Use sudo() to bypass ir.rules for calendar.event creation
        PublicHoliday = self.env["calendar.public.holiday"].sudo()

        # Search for existing year/country combination
        holiday_year = PublicHoliday.search([
            ("year", "=", year),
            ("country_id", "=", self.country_id.id),
        ], limit=1)

        if not holiday_year:
            # Create new year record
            holiday_year = PublicHoliday.create({
                "year": year,
                "country_id": self.country_id.id,
            })
            _logger.info(
                "Created public holiday year record: %s for country %s",
                year, self.country_id.name
            )

        return holiday_year

    def _upsert_holiday_line(self, holiday_year, holiday_data):
        """
        Create or update a single holiday line record.
        Uses sudo() to bypass access rules for calendar.event operations.

        Args:
            holiday_year: calendar.public.holiday record
            holiday_data: dict from Nager.Date API with keys:
                - date: "YYYY-MM-DD"
                - localName: local language name
                - name: English name
                - global: bool
                - types: list of type strings

        Returns:
            recordset: created or updated calendar.public.holiday.line
        """
        self.ensure_one()
        # Use sudo() to bypass ir.rules (e.g., "Edit Own Calendar Events Only")
        # since holiday sync is a system operation, not user-specific
        HolidayLine = self.env["calendar.public.holiday.line"].sudo()

        holiday_date = fields.Date.from_string(holiday_data.get("date"))
        local_name = holiday_data.get("localName", "")
        english_name = holiday_data.get("name", "")
        types = holiday_data.get("types", [])

        # Use localName if available, fallback to english name
        name = local_name or english_name

        # Search for existing line with same date in this year
        existing_line = HolidayLine.search([
            ("public_holiday_id", "=", holiday_year.id),
            ("date", "=", holiday_date),
            ("source", "=", "nagerdate"),
        ], limit=1)

        vals = {
            "name": name,
            "date": holiday_date,
            "public_holiday_id": holiday_year.id,
            "source": "nagerdate",
            "nagerdate_types": ", ".join(types) if types else False,
            "variable_date": True,
        }

        if existing_line:
            # Update existing record
            existing_line.write(vals)
            _logger.debug(
                "Updated holiday: %s on %s",
                name, holiday_date
            )
            result_line = existing_line
        else:
            # Create new record
            new_line = HolidayLine.create(vals)
            _logger.debug(
                "Created holiday: %s on %s",
                name, holiday_date
            )
            result_line = new_line

        # Ensure the linked calendar.event is public so all users can see it
        # The calendar_public_holiday module creates events with privacy='confidential'
        if result_line.meeting_id:
            result_line.meeting_id.sudo().write({"privacy": "public"})

        # Also sync to resource.calendar.leaves if enabled
        if self.sync_to_resource_calendar:
            self._sync_to_resource_calendar_leaves(holiday_data)

        return result_line

    def _sync_to_resource_calendar_leaves(self, holiday_data):
        """
        Sync a holiday to resource.calendar.leaves (standard Odoo model).
        This makes holidays visible in the standard Odoo Public Holidays menu.

        Args:
            holiday_data: dict from Nager.Date API
        """
        self.ensure_one()
        ResourceLeave = self.env["resource.calendar.leaves"].sudo()

        holiday_date = fields.Date.from_string(holiday_data.get("date"))
        local_name = holiday_data.get("localName", "")
        english_name = holiday_data.get("name", "")
        name = local_name or english_name

        # Add prefix to identify Nager.Date synced records
        full_name = f"[Nager.Date] {name}"

        # Convert date to datetime (full day)
        date_from = datetime.combine(holiday_date, datetime.min.time())
        date_to = datetime.combine(holiday_date, datetime.max.time().replace(microsecond=0))

        # Get company (use first company or current company)
        company = self.env.company

        # Determine which calendars to sync to
        if self.resource_calendar_ids:
            calendars = self.resource_calendar_ids
        else:
            # Global holiday - no specific calendar (applies to all)
            calendars = self.env["resource.calendar"].browse()

        if calendars:
            # Sync to specific calendars
            for calendar in calendars:
                self._upsert_resource_leave(
                    ResourceLeave, full_name, date_from, date_to,
                    company, calendar
                )
        else:
            # Global holiday (calendar_id = False)
            self._upsert_resource_leave(
                ResourceLeave, full_name, date_from, date_to,
                company, None
            )

    def _upsert_resource_leave(self, ResourceLeave, name, date_from, date_to,
                                company, calendar):
        """
        Create or update a resource.calendar.leaves record.

        Args:
            ResourceLeave: resource.calendar.leaves model (with sudo)
            name: Holiday name with prefix
            date_from: Start datetime
            date_to: End datetime
            company: res.company record
            calendar: resource.calendar record or None for global
        """
        # Search for existing record with same name and date
        domain = [
            ("name", "=", name),
            ("date_from", ">=", date_from.replace(hour=0, minute=0, second=0)),
            ("date_from", "<", date_from.replace(hour=0, minute=0, second=0) + 
             timedelta(days=1)),
            ("resource_id", "=", False),  # Global (not employee-specific)
        ]
        if calendar:
            domain.append(("calendar_id", "=", calendar.id))
        else:
            domain.append(("calendar_id", "=", False))

        existing = ResourceLeave.search(domain, limit=1)

        vals = {
            "name": name,
            "date_from": date_from,
            "date_to": date_to,
            "resource_id": False,  # Global holiday
            "calendar_id": calendar.id if calendar else False,
            "company_id": company.id,
            "time_type": "leave",
        }

        if existing:
            existing.write(vals)
            _logger.debug(
                "Updated resource.calendar.leaves: %s on %s",
                name, date_from.date()
            )
        else:
            ResourceLeave.create(vals)
            _logger.debug(
                "Created resource.calendar.leaves: %s on %s",
                name, date_from.date()
            )

    def sync_year(self, year):
        """
        Sync public holidays for a specific year from Nager.Date API.

        Args:
            year: The year to sync

        Returns:
            int: Number of holidays synced
        """
        self.ensure_one()
        _logger.info(
            "Starting sync for year %s, country %s",
            year, self.country_code
        )

        holidays_data = self._fetch_holidays_from_api(year)
        if not holidays_data:
            _logger.warning(
                "No holidays data received for year %s, country %s",
                year, self.country_code
            )
            return 0

        # Get or create the year record
        holiday_year = self._get_or_create_public_holiday_year(year)

        # Upsert each holiday
        count = 0
        for holiday_data in holidays_data:
            try:
                self._upsert_holiday_line(holiday_year, holiday_data)
                count += 1
            except Exception as e:
                _logger.error(
                    "Error syncing holiday %s: %s",
                    holiday_data.get("name", "Unknown"), str(e)
                )

        _logger.info(
            "Synced %d holidays for year %s, country %s",
            count, year, self.country_code
        )
        return count

    def sync_all_years(self):
        """
        Sync holidays for all configured years (years_back to years_ahead).

        Returns:
            int: Total number of holidays synced
        """
        self.ensure_one()
        current_year = date.today().year
        start_year = current_year - self.years_back
        end_year = current_year + self.years_ahead

        total_count = 0
        for year in range(start_year, end_year + 1):
            count = self.sync_year(year)
            total_count += count

        # Update last sync date
        self.write({"last_sync_date": fields.Datetime.now()})

        return total_count

    def action_sync_now(self):
        """
        Manual sync action triggered from UI button.
        """
        self.ensure_one()
        count = self.sync_all_years()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Sync Completed"),
                "message": _("Successfully synced %d holidays for %s") % (
                    count, self.country_id.name
                ),
                "type": "success",
                "sticky": False,
            },
        }

    @api.model
    def cron_sync_all_settings(self):
        """
        Cron job method to sync holidays for all enabled settings.
        Called by scheduled action.
        """
        settings = self.search([("auto_sync_enabled", "=", True)])
        total_count = 0

        for setting in settings:
            try:
                count = setting.sync_all_years()
                total_count += count
                _logger.info(
                    "Cron sync completed for %s: %d holidays",
                    setting.country_id.name, count
                )
            except Exception as e:
                _logger.error(
                    "Cron sync failed for %s: %s",
                    setting.country_id.name, str(e)
                )

        _logger.info("Total holidays synced in cron job: %d", total_count)
        return True

    def action_test_api(self):
        """
        Test API connection by fetching current year holidays.
        """
        self.ensure_one()
        current_year = date.today().year
        holidays = self._fetch_holidays_from_api(current_year)

        if holidays:
            message = _("API connection successful! Found %d holidays for %s") % (
                len(holidays), current_year
            )
            msg_type = "success"
        else:
            message = _("API returned no data. Please check the country code.")
            msg_type = "warning"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("API Test"),
                "message": message,
                "type": msg_type,
                "sticky": False,
            },
        }

