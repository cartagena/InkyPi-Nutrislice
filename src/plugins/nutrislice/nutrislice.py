import logging
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from PIL.Image import Image as ImageType

from plugins.base_plugin.base_plugin import BasePlugin, DeviceConfigLike
from plugins.base_plugin.settings_schema import field, option, row, schema, section
from utils.http_client import get_http_session
from utils.time_utils import get_timezone

logger = logging.getLogger(__name__)

# Matches Nutrislice school menu urls, e.g.
# https://<district>.nutrislice.com/menu/<school>/<meal-type>/
NUTRISLICE_URL_PATTERN = re.compile(
    r"^https?://([\w-]+)\.nutrislice\.com/menus?/([\w-]+)/([\w-]+)", re.IGNORECASE
)

DAYS_TO_SHOW_OPTIONS = {"1": 1, "3": 3, "week": 7}


class Nutrislice(BasePlugin):
    @staticmethod
    def get_menu_url(settings: Mapping[str, object]) -> str:
        raw = settings.get("menuUrl")
        return raw.strip() if isinstance(raw, str) else ""

    def validate_settings(self, settings: Mapping[str, object]) -> str | None:
        try:
            self.parse_menu_url(self.get_menu_url(settings))
        except RuntimeError as e:
            return str(e)
        return None

    def build_settings_schema(self) -> dict[str, object]:
        return schema(
            section(
                "Menu",
                field(
                    "menuUrl",
                    "url",
                    label="School Menu Url",
                    placeholder="https://<district>.nutrislice.com/menu/<school>/<meal-type>/",
                    required=True,
                    pattern="https?://.+",
                    hint=(
                        "Visit your school district's Nutrislice site, pick your school "
                        "and a meal (lunch or breakfast), and copy that page's url."
                    ),
                ),
                row(
                    field(
                        "daysToShow",
                        "select",
                        label="Days to Show",
                        default="week",
                        options=[
                            option("1", "1 Day"),
                            option("3", "3 Days"),
                            option("week", "Full Week"),
                        ],
                    ),
                    field(
                        "showCarbs",
                        "checkbox",
                        label="Show Carbs",
                        submit_unchecked=True,
                        checked_value="true",
                        unchecked_value="false",
                    ),
                ),
            )
        )

    def generate_settings_template(self) -> dict[str, object]:
        template_params = super().generate_settings_template()
        template_params["style_settings"] = True
        return template_params

    def generate_image(
        self, settings: Mapping[str, object], device_config: DeviceConfigLike
    ) -> ImageType:
        district, school, menu_type = self.parse_menu_url(self.get_menu_url(settings))

        show_carbs = settings.get("showCarbs") == "true"
        days_setting = settings.get("daysToShow")
        days_to_show = DAYS_TO_SHOW_OPTIONS.get(
            days_setting if isinstance(days_setting, str) else "", 7
        )

        tz_name = device_config.get_config("timezone", default="UTC")
        now = datetime.now(get_timezone(tz_name if isinstance(tz_name, str) else None))

        days = self.fetch_menu(district, school, menu_type, days_to_show, now)

        dimensions = self.get_oriented_dimensions(device_config)

        max_items = max((len(day["foods"]) for day in days), default=0)

        template_params = {
            "days": days,
            "show_carbs": show_carbs,
            "school": school.replace("-", " ").title(),
            "meal_type": self.format_meal_type(menu_type),
            "item_scale": self.compute_item_scale(max_items),
            "plugin_settings": settings,
        }

        return self.render_image(
            dimensions, "nutrislice.html", "nutrislice.css", template_params
        )

    def format_meal_type(self, menu_type: str) -> str:
        """Build a display label for a menu-type slug, e.g. ``elementary-lunch-menu``.

        Some districts already bake the word "menu" into their menu-type slug
        (as a whole word, anywhere in it — including a slug that's just
        "menu"), so it's filtered out by word rather than stripped as a
        trailing substring, then re-appended once here so the rendered label
        never reads "Elementary Lunch Menu Menu" or "Menu Menu".
        """
        words = menu_type.replace("-", " ").title().split()
        label = " ".join(word for word in words if word.lower() != "menu")
        return f"{label} Menu".strip()

    def compute_item_scale(self, max_items: int) -> float:
        """Scale item text/spacing down as the busiest visible day gets fuller.

        Font sizes are tuned for a handful of items; some districts publish
        10+ items for a single day (entrees, sides, condiments), which would
        otherwise overflow the display and clip items off the bottom.
        Shrinking proportionally reduces that risk, though a day with an
        extreme item count can still overflow — there's no substitute for
        pagination at that point, and this plugin doesn't paginate.
        """
        if max_items <= 0:
            return 1.15
        # Roughly fit `max_items` lines into the space tuned for ~7,
        # clamped to a readable range.
        return max(0.4, min(1.15, 7 / max_items))

    def parse_menu_url(self, menu_url: str) -> tuple[str, str, str]:
        if not menu_url:
            raise RuntimeError("School Menu Url is required.")
        match = NUTRISLICE_URL_PATTERN.match(menu_url)
        if not match:
            raise RuntimeError(
                "Unrecognized School Menu Url. Expected a Nutrislice menu url, e.g. "
                "https://<district>.nutrislice.com/menu/<school>/<meal-type>/"
            )
        return match.group(1), match.group(2), match.group(3)

    def fetch_menu(
        self,
        district: str,
        school: str,
        menu_type: str,
        days_to_show: int,
        today: datetime,
    ) -> list[dict[str, Any]]:
        session = get_http_session()

        try:
            raw_days = self.fetch_week(session, district, school, menu_type, today)
        except Exception as e:
            logger.error(f"Failed to fetch Nutrislice menu: {e}")
            raise RuntimeError(
                "Failed to fetch menu from Nutrislice. Please check the School Menu Url."
            ) from e

        today_date = today.date()
        seen_dates: set[Any] = set()
        days = self.extract_days(raw_days, today_date, days_to_show, seen_dates)

        # Only pay for a second round-trip if the first week didn't already
        # have enough upcoming days (e.g. requesting the full week late on a
        # Friday, or the district hasn't published this week's menu yet).
        if len(days) < days_to_show:
            try:
                next_week_raw_days = self.fetch_week(
                    session, district, school, menu_type, today + timedelta(days=7)
                )
            except Exception as e:
                logger.warning(f"Failed to fetch next week's Nutrislice menu: {e}")
            else:
                days += self.extract_days(
                    next_week_raw_days,
                    today_date,
                    days_to_show - len(days),
                    seen_dates,
                )

        if not days:
            raise RuntimeError("No upcoming menu items were found for this school.")

        return days

    def extract_days(
        self,
        raw_days: list[dict[str, Any]],
        today_date: Any,
        limit: int,
        seen_dates: set[Any],
    ) -> list[dict[str, Any]]:
        """Filter/normalize raw API days into display-ready day dicts.

        ``seen_dates`` is shared (and mutated) across calls so a second week's
        response can't reintroduce a date already picked from the first.
        """
        days: list[dict[str, Any]] = []
        for day in raw_days:
            if limit <= 0:
                break

            date_str = day.get("date")
            if not date_str:
                continue
            try:
                day_datetime = datetime.strptime(date_str, "%Y-%m-%d")  # noqa: DTZ007
            except ValueError:
                continue
            day_date = day_datetime.date()

            if day_date in seen_dates or day_date < today_date:
                continue

            foods = self.parse_menu_items(day.get("menu_items") or [])
            if not foods:
                continue

            seen_dates.add(day_date)
            days.append(
                {
                    "weekday": day_date.strftime("%A"),
                    "date_label": day_date.strftime("%b ") + str(day_date.day),
                    "foods": foods,
                }
            )
            limit -= 1

        return days

    def fetch_week(
        self,
        session: Any,
        district: str,
        school: str,
        menu_type: str,
        query_date: datetime,
    ) -> list[dict[str, Any]]:
        base_url = (
            f"https://{district}.api.nutrislice.com/menu/api/weeks/school/"
            f"{school}/menu-type/{menu_type}"
        )
        endpoint = (
            f"{base_url}/{query_date.year}/{query_date.month}/{query_date.day}/"
            "?format=json"
        )

        resp = session.get(endpoint, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        raw_days = data.get("days", [])
        return raw_days if isinstance(raw_days, list) else []

    def parse_menu_items(
        self, menu_items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        items = []
        for item in menu_items:
            food = item.get("food")
            if not food or not food.get("name"):
                continue

            nutrition = food.get("rounded_nutrition_info") or {}
            items.append({"name": food.get("name"), "carbs": nutrition.get("g_carbs")})

        return items
