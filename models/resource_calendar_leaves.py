from odoo import fields, models


class ResourceCalendarLeaves(models.Model):
    _inherit = "resource.calendar.leaves"

    source = fields.Selection(
        selection=[
            ("manual", "Manual"),
            ("nagerdate", "Nager.Date API"),
        ],
        string="Source",
        default="manual",
        index=True,
        help="Indicates how this public holiday was created.",
    )
    nagerdate_setting_id = fields.Many2one(
        comodel_name="nagerdate.settings",
        string="Nager.Date Setting",
        index=True,
        copy=False,
        help="Sync settings record that produced this public holiday.",
    )
    nagerdate_holiday_date = fields.Date(
        string="Holiday Date",
        index=True,
        copy=False,
        help="Calendar date received from Nager.Date. Used for safe upserts.",
    )
    nagerdate_types = fields.Char(
        string="Holiday Types",
        copy=False,
        help="Holiday type categories returned by Nager.Date.",
    )
