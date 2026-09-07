# Copyright 2024-2025 Isalab Team
# Author: AI Assistant <ai@isalab.com>
# Date: 2025-12-27
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from datetime import date, datetime, time

import pytz
import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

NAGERDATE_API_BASE_URL = "https://date.nager.at/api/v3/PublicHolidays"
LEGACY_NAGERDATE_PREFIX = "[Nager.Date] "


class NagerDateSettings(models.Model):
    _name = "nagerdate.settings"
    _description = "Nager.Date Sync Settings"
    _rec_name = "country_id"

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        help="Company whose working schedules receive the synced public holidays.",
    )
    country_id = fields.Many2one(
        comodel_name="res.country",
        string="Country",
        required=True,
        help="Country for which to sync public holidays.",
    )
    country_code = fields.Char(
        string="Country Code",
        size=2,
        required=True,
        default="IT",
        help="ISO 3166-1 alpha-2 country code used for the Nager.Date API.",
    )
    years_ahead = fields.Integer(
        string="Years Ahead",
        default=2,
        help="Number of years ahead to sync from the current year.",
    )
    years_back = fields.Integer(
        string="Years Back",
        default=1,
        help="Number of years back to sync from the current year.",
    )
    auto_sync_enabled = fields.Boolean(
        string="Auto Sync Enabled",
        default=True,
        help="Enable automatic synchronization via scheduled action.",
    )
    last_sync_date = fields.Datetime(
        string="Last Sync Date",
        readonly=True,
        help="Date and time of the last successful sync.",
    )
    api_base_url = fields.Char(
        string="API Base URL",
        default=NAGERDATE_API_BASE_URL,
        help="Base URL for the Nager.Date API.",
    )
    sync_to_resource_calendar = fields.Boolean(
        string="Legacy Resource Calendar Toggle",
        default=True,
        help="Deprecated field kept for backward compatibility. Sync now always "
        "updates standard Odoo public holidays in resource.calendar.leaves.",
    )
    resource_calendar_ids = fields.Many2many(
        comodel_name="resource.calendar",
        string="Working Schedules",
        help="Specific working schedules that should receive the imported public "
        "holidays. Leave empty to create company-wide public holidays.",
    )

    _sql_constraints = [
        (
            "company_country_unique",
            "UNIQUE(company_id, country_id)",
            "A sync settings record for this company and country already exists!",
        ),
    ]

    @api.onchange("country_id")
    def _onchange_country_id(self):
        for setting in self:
            if setting.country_id.code:
                setting.country_code = setting.country_id.code.upper()

    @api.constrains("resource_calendar_ids", "company_id")
    def _check_resource_calendar_company(self):
        for setting in self:
            invalid_calendars = setting.resource_calendar_ids.filtered(
                lambda calendar: calendar.company_id
                and calendar.company_id != setting.company_id
            )
            if invalid_calendars:
                raise ValidationError(
                    _(
                        "All selected working schedules must belong to company %s.",
                        setting.company_id.display_name,
                    )
                )

    def _get_country_code(self):
        self.ensure_one()
        country_code = (self.country_id.code or self.country_code or "").upper()
        if not country_code:
            raise UserError(
                _("Please set a valid ISO country code before syncing holidays.")
            )
        return country_code

    @api.model
    def _get_api_url(self, year, country_code, api_base_url=None):
        base_url = (api_base_url or NAGERDATE_API_BASE_URL).rstrip("/")
        return f"{base_url}/{year}/{country_code}"

    def _fetch_holidays_from_api(self, year):
        self.ensure_one()
        url = self._get_api_url(
            year,
            self._get_country_code(),
            api_base_url=self.api_base_url,
        )
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            _logger.warning(
                "Nager.Date API timeout for year %s, country %s",
                year,
                self._get_country_code(),
            )
            return []
        except requests.exceptions.RequestException as exc:
            _logger.warning(
                "Nager.Date API error for year %s, country %s: %s",
                year,
                self._get_country_code(),
                str(exc),
            )
            return []
        except ValueError as exc:
            _logger.warning(
                "Nager.Date API JSON parse error for year %s, country %s: %s",
                year,
                self._get_country_code(),
                str(exc),
            )
            return []

    def _is_supported_holiday_scope(self, holiday_data):
        """
        Return True only for country-wide holidays that can be applied globally.

        Nager.Date also returns regional holidays where `global` is false and/or
        `counties` contains province codes. This module currently syncs holidays
        only at company or full-calendar scope, so importing regional holidays as
        generic resource leaves would incorrectly mark all employees as off.
        """
        is_global = holiday_data.get("global")
        counties = holiday_data.get("counties") or []
        if isinstance(counties, str):
            counties = [counties]

        if is_global is False or counties:
            _logger.info(
                "Skipping non-global Nager.Date holiday '%s' on %s. counties=%s",
                holiday_data.get("localName")
                or holiday_data.get("name")
                or "Public Holiday",
                holiday_data.get("date"),
                counties or [],
            )
            return False
        return True

    def _get_unsupported_holiday_dates(self, holidays_data):
        """
        Extract holiday dates that should not be imported at company/calendar scope.

        This is used both during normal sync and during upgrade cleanup of legacy
        regional holidays that were previously imported as global non-working days.
        """
        unsupported_dates = set()
        for holiday_data in holidays_data or []:
            holiday_date = fields.Date.from_string(holiday_data.get("date"))
            if holiday_date and not self._is_supported_holiday_scope(holiday_data):
                unsupported_dates.add(holiday_date)
        return unsupported_dates

    def _prepare_holiday_values(self, holiday_data):
        if not self._is_supported_holiday_scope(holiday_data):
            return False
        holiday_date = fields.Date.from_string(holiday_data.get("date"))
        if not holiday_date:
            return False
        local_name = holiday_data.get("localName", "")
        english_name = holiday_data.get("name", "")
        types = holiday_data.get("types") or []
        if isinstance(types, str):
            types = [types]
        return {
            "date": holiday_date,
            "name": local_name or english_name or _("Public Holiday"),
            "nagerdate_types": ", ".join(types) if types else False,
        }

    def _get_resource_sync_targets(self):
        self.ensure_one()
        if self.resource_calendar_ids:
            return [
                {
                    "calendar": calendar,
                    "company": calendar.company_id or self.company_id,
                }
                for calendar in self.resource_calendar_ids
            ]
        return [{"calendar": False, "company": self.company_id}]

    def _get_country_timezone_name(self):
        self.ensure_one()
        country_code = self._get_country_code()
        try:
            country_timezones = pytz.country_timezones[country_code]
        except KeyError:
            country_timezones = []
        return country_timezones[0] if country_timezones else False

    def _safe_timezone(self, tz_name, fallback="UTC"):
        try:
            return pytz.timezone(tz_name or fallback)
        except pytz.UnknownTimeZoneError:
            _logger.warning(
                "Invalid timezone '%s' for Nager.Date setting %s; using %s.",
                tz_name,
                self.display_name,
                fallback,
            )
            return pytz.timezone(fallback)

    def _get_target_timezone(self, calendar, company):
        if calendar:
            return self._safe_timezone(calendar.tz)

        tz_name = (
            self._get_country_timezone_name()
            or (company.partner_id.tz if company.partner_id else None)
            or company.resource_calendar_id.tz
        )
        return self._safe_timezone(tz_name)

    def _get_resource_leave_datetimes(self, holiday_date, calendar, company):
        target_tz = self._get_target_timezone(calendar, company)
        local_start = target_tz.localize(datetime.combine(holiday_date, time.min))
        local_end = target_tz.localize(
            datetime.combine(holiday_date, time.max.replace(microsecond=0))
        )
        return (
            local_start.astimezone(pytz.utc).replace(tzinfo=None),
            local_end.astimezone(pytz.utc).replace(tzinfo=None),
        )

    def _get_or_create_public_holiday_year(self, year):
        self.ensure_one()
        public_holiday = self.env["calendar.public.holiday"].sudo()
        holiday_year = public_holiday.search(
            [
                ("year", "=", year),
                ("country_id", "=", self.country_id.id),
            ],
            limit=1,
        )
        if not holiday_year:
            holiday_year = public_holiday.create(
                {
                    "year": year,
                    "country_id": self.country_id.id,
                }
            )
            _logger.info(
                "Created public holiday year record %s for country %s",
                year,
                self.country_id.name,
            )
        return holiday_year

    def _upsert_calendar_public_holiday_line(self, holiday_year, holiday_values):
        self.ensure_one()
        holiday_line = self.env["calendar.public.holiday.line"].sudo()
        vals = {
            "name": holiday_values["name"],
            "date": holiday_values["date"],
            "public_holiday_id": holiday_year.id,
            "source": "nagerdate",
            "nagerdate_types": holiday_values["nagerdate_types"],
            "variable_date": True,
        }
        existing_line = holiday_line.search(
            [
                ("public_holiday_id", "=", holiday_year.id),
                ("date", "=", holiday_values["date"]),
                ("source", "=", "nagerdate"),
            ],
            limit=1,
        )
        if existing_line:
            existing_line.write(vals)
            return True
        try:
            holiday_line.create(vals)
            return True
        except ValidationError:
            _logger.warning(
                "Skipped imported OCA holiday on %s for %s because a manual record already exists.",
                holiday_values["date"],
                self.country_id.name,
            )
            return False

    def _cleanup_removed_calendar_public_holidays(self, holiday_year, expected_dates):
        holiday_lines = self.env["calendar.public.holiday.line"].sudo().search(
            [
                ("public_holiday_id", "=", holiday_year.id),
                ("source", "=", "nagerdate"),
            ]
        )
        stale_lines = holiday_lines.filtered(lambda line: line.date not in expected_dates)
        if stale_lines:
            stale_lines.unlink()
            _logger.info(
                "Removed %s stale imported OCA public holiday lines for %s.",
                len(stale_lines),
                holiday_year.display_name,
            )

    def _get_existing_resource_leave(self, holiday_values, calendar, company):
        resource_leave = (
            self.env["resource.calendar.leaves"].sudo().with_company(company)
        )
        domain = [
            ("resource_id", "=", False),
            ("calendar_id", "=", calendar.id if calendar else False),
            ("source", "=", "nagerdate"),
            ("nagerdate_setting_id", "=", self.id),
            ("nagerdate_holiday_date", "=", holiday_values["date"]),
        ]
        if not calendar:
            domain.append(("company_id", "=", company.id))
        existing = resource_leave.search(domain, limit=1)
        if existing:
            return existing

        date_from, date_to = self._get_resource_leave_datetimes(
            holiday_values["date"], calendar, company
        )
        legacy_domain = [
            ("resource_id", "=", False),
            ("calendar_id", "=", calendar.id if calendar else False),
            ("date_from", "<", date_to),
            ("date_to", ">", date_from),
            ("name", "=", f"{LEGACY_NAGERDATE_PREFIX}{holiday_values['name']}"),
        ]
        if not calendar:
            legacy_domain.append(("company_id", "=", company.id))
        return resource_leave.search(legacy_domain, limit=1)

    def _upsert_resource_leave(self, holiday_values, calendar, company):
        self.ensure_one()
        resource_leave = (
            self.env["resource.calendar.leaves"].sudo().with_company(company)
        )
        date_from, date_to = self._get_resource_leave_datetimes(
            holiday_values["date"], calendar, company
        )
        vals = {
            "name": holiday_values["name"],
            "date_from": date_from,
            "date_to": date_to,
            "resource_id": False,
            "calendar_id": calendar.id if calendar else False,
            "time_type": "leave",
            "source": "nagerdate",
            "nagerdate_setting_id": self.id,
            "nagerdate_holiday_date": holiday_values["date"],
            "nagerdate_types": holiday_values["nagerdate_types"],
        }
        existing_leave = self._get_existing_resource_leave(
            holiday_values, calendar, company
        )
        if existing_leave:
            existing_leave.write(vals)
            return True
        try:
            resource_leave.create(vals)
            return True
        except ValidationError:
            _logger.warning(
                "Skipped standard Odoo public holiday on %s for company %s / calendar %s because a manual public holiday already exists.",
                holiday_values["date"],
                company.display_name,
                calendar.display_name if calendar else _("Global"),
            )
            return False

    def normalize_imported_resource_leave_bounds(self):
        """Recompute imported public holiday UTC bounds with the current timezone policy."""
        updated = self.env["resource.calendar.leaves"].sudo()
        for setting in self:
            leaves = self.env["resource.calendar.leaves"].sudo().search(
                [
                    ("source", "=", "nagerdate"),
                    ("nagerdate_setting_id", "=", setting.id),
                    ("nagerdate_holiday_date", "!=", False),
                ]
            )
            for leave in leaves:
                company = (
                    leave.company_id
                    or leave.calendar_id.company_id
                    or setting.company_id
                )
                date_from, date_to = setting._get_resource_leave_datetimes(
                    leave.nagerdate_holiday_date,
                    leave.calendar_id,
                    company,
                )
                vals = {}
                if leave.date_from != date_from:
                    vals["date_from"] = date_from
                if leave.date_to != date_to:
                    vals["date_to"] = date_to
                if vals:
                    leave.with_company(company).write(vals)
                    updated |= leave
        return updated

    def _cleanup_removed_resource_leaves(self, year, expected_keys):
        imported_leaves = self.env["resource.calendar.leaves"].sudo().search(
            [
                ("source", "=", "nagerdate"),
                ("nagerdate_setting_id", "=", self.id),
                ("nagerdate_holiday_date", ">=", date(year, 1, 1)),
                ("nagerdate_holiday_date", "<=", date(year, 12, 31)),
            ]
        )
        stale_leaves = imported_leaves.filtered(
            lambda leave: (
                leave.calendar_id.id if leave.calendar_id else False,
                leave.nagerdate_holiday_date,
            )
            not in expected_keys
        )
        if stale_leaves:
            stale_leaves.unlink()
            _logger.info(
                "Removed %s stale imported standard public holidays for setting %s.",
                len(stale_leaves),
                self.display_name,
            )

    def cleanup_unsupported_imported_holidays(self, year, holidays_data=None):
        """
        Remove previously imported regional holidays that are not supported anymore.

        Safety rules:
        - Delete only records created by this module (`source='nagerdate'`)
        - Delete only exact holiday dates identified as non-global by the API
        - Fail safe when the API yields no payload: do not delete anything
        """
        self.ensure_one()
        fetched_from_api = holidays_data is None
        if holidays_data is None:
            holidays_data = self._fetch_holidays_from_api(year)

        if fetched_from_api and not holidays_data:
            _logger.warning(
                "Skipping cleanup of unsupported imported holidays for %s / %s in %s "
                "because the Nager.Date API returned no data.",
                self.company_id.display_name,
                self.country_id.display_name,
                year,
            )
            return {
                "skipped": True,
                "unsupported_dates": set(),
                "calendar_public_holiday_lines": 0,
                "resource_calendar_leaves": 0,
            }

        unsupported_dates = self._get_unsupported_holiday_dates(holidays_data)
        if not unsupported_dates:
            return {
                "skipped": False,
                "unsupported_dates": set(),
                "calendar_public_holiday_lines": 0,
                "resource_calendar_leaves": 0,
            }

        holiday_year = self.env["calendar.public.holiday"].sudo().search(
            [
                ("year", "=", year),
                ("country_id", "=", self.country_id.id),
            ],
            limit=1,
        )
        holiday_lines = self.env["calendar.public.holiday.line"].sudo()
        if holiday_year:
            holiday_lines = holiday_lines.search(
                [
                    ("public_holiday_id", "=", holiday_year.id),
                    ("source", "=", "nagerdate"),
                    ("date", "in", sorted(unsupported_dates)),
                ]
            )
        else:
            holiday_lines = holiday_lines.browse()

        resource_leaves = self.env["resource.calendar.leaves"].sudo().search(
            [
                ("source", "=", "nagerdate"),
                ("nagerdate_setting_id", "=", self.id),
                ("nagerdate_holiday_date", "in", sorted(unsupported_dates)),
            ]
        )

        removed_holiday_lines = len(holiday_lines)
        removed_resource_leaves = len(resource_leaves)

        if holiday_lines:
            holiday_lines.unlink()
        if resource_leaves:
            resource_leaves.unlink()

        if removed_holiday_lines or removed_resource_leaves:
            _logger.info(
                "Removed unsupported imported Nager.Date holidays for %s / %s in %s: "
                "%s OCA holiday lines, %s resource leaves, dates=%s",
                self.company_id.display_name,
                self.country_id.display_name,
                year,
                removed_holiday_lines,
                removed_resource_leaves,
                sorted(str(d) for d in unsupported_dates),
            )

        return {
            "skipped": False,
            "unsupported_dates": unsupported_dates,
            "calendar_public_holiday_lines": removed_holiday_lines,
            "resource_calendar_leaves": removed_resource_leaves,
        }

    def sync_year(self, year):
        self.ensure_one()
        _logger.info(
            "Starting Nager.Date sync for year %s, company %s, country %s",
            year,
            self.company_id.display_name,
            self._get_country_code(),
        )

        holidays_data = self._fetch_holidays_from_api(year)
        if not holidays_data:
            _logger.warning(
                "No holidays data received for year %s, country %s",
                year,
                self._get_country_code(),
            )
            return None

        holiday_year = self._get_or_create_public_holiday_year(year)
        targets = self._get_resource_sync_targets()
        expected_catalog_dates = set()
        expected_resource_keys = set()
        processed_count = 0

        for holiday_data in holidays_data:
            holiday_values = self._prepare_holiday_values(holiday_data)
            if not holiday_values:
                continue
            processed_count += 1
            try:
                if self._upsert_calendar_public_holiday_line(holiday_year, holiday_values):
                    expected_catalog_dates.add(holiday_values["date"])
                for target in targets:
                    if self._upsert_resource_leave(
                        holiday_values,
                        target["calendar"],
                        target["company"],
                    ):
                        expected_resource_keys.add(
                            (
                                target["calendar"].id if target["calendar"] else False,
                                holiday_values["date"],
                            )
                        )
            except Exception as exc:
                _logger.exception(
                    "Unexpected error while syncing %s on %s: %s",
                    holiday_values["name"],
                    holiday_values["date"],
                    str(exc),
                )

        self._cleanup_removed_calendar_public_holidays(
            holiday_year, expected_catalog_dates
        )
        self._cleanup_removed_resource_leaves(year, expected_resource_keys)

        _logger.info(
            "Processed %s holidays for year %s, company %s, country %s",
            processed_count,
            year,
            self.company_id.display_name,
            self._get_country_code(),
        )
        return processed_count

    def sync_all_years(self):
        self.ensure_one()
        current_year = date.today().year
        start_year = current_year - self.years_back
        end_year = current_year + self.years_ahead

        total_count = 0
        successful_years = 0
        for year in range(start_year, end_year + 1):
            count = self.sync_year(year)
            if count is None:
                continue
            successful_years += 1
            total_count += count

        if successful_years:
            self.write({"last_sync_date": fields.Datetime.now()})

        return total_count

    def action_sync_now(self):
        self.ensure_one()
        previous_sync_date = self.last_sync_date
        count = self.sync_all_years()
        if count or self.last_sync_date != previous_sync_date:
            title = _("Sync Completed")
            message = _("Processed %d holidays for %s.") % (
                count,
                self.country_id.name,
            )
            msg_type = "success"
        else:
            title = _("Sync Incomplete")
            message = _(
                "No holiday data was imported. Please verify the API base URL and country code."
            )
            msg_type = "warning"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": msg_type,
                "sticky": False,
            },
        }

    @api.model
    def cron_sync_all_settings(self):
        settings = self.search([("auto_sync_enabled", "=", True)])
        total_count = 0

        for setting in settings:
            try:
                count = setting.sync_all_years()
                total_count += count
                _logger.info(
                    "Cron sync completed for %s / %s: %d holidays",
                    setting.company_id.display_name,
                    setting.country_id.name,
                    count,
                )
            except Exception as exc:
                _logger.exception(
                    "Cron sync failed for %s / %s: %s",
                    setting.company_id.display_name,
                    setting.country_id.name,
                    str(exc),
                )

        _logger.info("Total holidays processed in cron job: %d", total_count)
        return True

    def action_test_api(self):
        self.ensure_one()
        current_year = date.today().year
        holidays = self._fetch_holidays_from_api(current_year)
        if holidays:
            message = _("API connection successful. Found %d holidays for %s.") % (
                len(holidays),
                current_year,
            )
            msg_type = "success"
        else:
            message = _(
                "API returned no data. Please verify the country code and API base URL."
            )
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

