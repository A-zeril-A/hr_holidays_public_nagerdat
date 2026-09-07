import logging

from odoo import SUPERUSER_ID, api
from odoo.addons.hr_holidays_public_nagerdate.hooks import (
    normalize_nagerdate_resource_leave_bounds,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    normalize_nagerdate_resource_leave_bounds(env)
    _logger.info(
        "Nager.Date resource leave timezone normalization completed during upgrade to 18.0.2.0.2 from %s.",
        version,
    )
