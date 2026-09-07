"""
Disable the legacy calendar public-read record rule.

Why:
- Record rules are conjunctive (AND). A rule restricting to `privacy='public'` for
  internal users will hide normal meetings and pending invitations.

We keep the XML record for backwards compatibility, but enforce it disabled at
registry load time to make upgrades/restarts safe.
"""

import logging

from odoo import api, models

from ..hooks import normalize_hr_holidays_public_menu

_logger = logging.getLogger(__name__)


class IrRule(models.Model):
    _inherit = "ir.rule"

    @api.model
    def _register_hook(self):
        res = super()._register_hook()
        # Be defensive: disable the rule even if it was reactivated manually or by data reload.
        rule = self.env.ref(
            "hr_holidays_public_nagerdate.calendar_event_public_read_rule",
            raise_if_not_found=False,
        )
        if rule and rule.active:
            try:
                rule.sudo().write({"active": False})
                _logger.warning(
                    "Disabled record rule %s (%s) to prevent calendar invitation visibility issues.",
                    rule.name,
                    rule.id,
                )
            except Exception:
                _logger.exception("Failed to disable legacy calendar public-read rule.")
        # Keep registry-load side effects lightweight to avoid concurrent writes
        # when multiple workers rebuild the registry at the same time.
        try:
            normalize_hr_holidays_public_menu(self.env)
        except Exception:
            _logger.exception("Failed to normalize OCA public holiday menus.")
        return res

