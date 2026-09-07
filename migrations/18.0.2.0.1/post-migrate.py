import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _get_imported_years(setting):
    env = setting.env
    years = {
        holiday_date.year
        for holiday_date in env["resource.calendar.leaves"]
        .sudo()
        .search(
            [
                ("source", "=", "nagerdate"),
                ("nagerdate_setting_id", "=", setting.id),
                ("nagerdate_holiday_date", "!=", False),
            ]
        )
        .mapped("nagerdate_holiday_date")
        if holiday_date
    }
    years.update(
        year
        for year in env["calendar.public.holiday.line"]
        .sudo()
        .search(
            [
                ("source", "=", "nagerdate"),
                ("public_holiday_id.country_id", "=", setting.country_id.id),
            ]
        )
        .mapped("public_holiday_id.year")
        if year
    )
    return sorted(years)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    settings = env["nagerdate.settings"].sudo().with_context(active_test=False).search([])
    if not settings:
        _logger.info("No Nager.Date settings found. Skipping unsupported holiday cleanup.")
        return

    total_holiday_lines = 0
    total_resource_leaves = 0
    removed_cases = set()
    skipped_years = []
    payload_cache = {}

    for setting in settings:
        years = _get_imported_years(setting)
        if not years:
            continue

        country_code = (setting.country_id.code or setting.country_code or "").upper()
        for year in years:
            cache_key = (country_code, year)
            if cache_key not in payload_cache:
                payload_cache[cache_key] = setting._fetch_holidays_from_api(year)

            holidays_data = payload_cache[cache_key]
            if not holidays_data:
                skipped_years.append(f"{country_code}:{year}")
                _logger.warning(
                    "Skipping unsupported holiday cleanup for %s / %s in %s "
                    "because the Nager.Date API returned no data.",
                    setting.company_id.display_name,
                    setting.country_id.display_name,
                    year,
                )
                continue

            result = setting.cleanup_unsupported_imported_holidays(
                year, holidays_data=holidays_data
            )
            total_holiday_lines += result["calendar_public_holiday_lines"]
            total_resource_leaves += result["resource_calendar_leaves"]
            removed_cases.update(
                (setting.country_id.id, year, holiday_date)
                for holiday_date in result["unsupported_dates"]
            )

    _logger.info(
        "Unsupported Nager.Date holiday cleanup completed: removed %s OCA holiday lines "
        "and %s resource leaves across %s holiday dates.",
        total_holiday_lines,
        total_resource_leaves,
        len(removed_cases),
    )
    if skipped_years:
        _logger.warning(
            "Unsupported Nager.Date holiday cleanup skipped years with empty API payload: %s",
            ", ".join(sorted(set(skipped_years))),
        )
