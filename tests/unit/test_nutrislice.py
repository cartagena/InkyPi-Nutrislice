# pyright: reportMissingImports=false
"""Tests for the Nutrislice plugin (src/plugins/nutrislice).

Type annotations below are typed throughout to avoid adding to the tests/
mypy debt ratchet (see scripts/mypy_tests_baseline.txt). pytest's
`@pytest.fixture()`/`@pytest.mark.parametrize()` decorators aren't fully
typed in this project's stub setup, so annotated functions they wrap need an
explicit `type: ignore[untyped-decorator]` — the annotations themselves are
still checked, this only silences mypy's complaint about the decorator.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from plugins.nutrislice.nutrislice import Nutrislice


@pytest.fixture()  # type: ignore[untyped-decorator]
def plugin_config() -> dict[str, str]:
    return {"id": "nutrislice", "class": "Nutrislice", "name": "Nutrislice"}


@pytest.fixture()  # type: ignore[untyped-decorator]
def plugin(plugin_config: dict[str, str]) -> Nutrislice:
    from plugins.nutrislice.nutrislice import Nutrislice

    return Nutrislice(plugin_config)


def _food_item(name: str = "Pizza", carbs: float = 30.0) -> dict[str, Any]:
    return {
        "food": {
            "name": name,
            "rounded_nutrition_info": {"g_carbs": carbs},
        }
    }


class _FakeDeviceConfig:
    """Minimal DeviceConfigLike stand-in.

    generate_image only reads the timezone and the resolution/orientation, so
    a real InkyPi Config would add nothing here beyond a host dependency.
    """

    def __init__(self, timezone: str = "UTC", resolution: tuple[int, int] = (800, 480)):
        self._timezone = timezone
        self._resolution = resolution

    def get_resolution(self) -> tuple[int, int]:
        return self._resolution

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._timezone if key == "timezone" else default

    def load_env_key(self, key: str) -> str | None:
        return None


def _mock_week_response(days: list[dict[str, Any]]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"days": days}
    return resp


# ---------------------------------------------------------------------------
# parse_menu_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    "url",
    [
        "https://district.nutrislice.com/menu/some-school/lunch/",
        "https://district.nutrislice.com/menus/some-school/lunch/",
        "http://district.nutrislice.com/menu/some-school/lunch",
        "https://district.nutrislice.com/menu/elementary-school/elementary-lunch-menu/",
    ],
)
def test_parse_menu_url_accepts_valid_urls(plugin: Nutrislice, url: str) -> None:
    district, school, menu_type = plugin.parse_menu_url(url)
    assert district == "district"
    assert school in ("some-school", "elementary-school")
    assert menu_type in ("lunch", "elementary-lunch-menu")


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    "url",
    [
        "",
        "not a url",
        "https://example.com/menu/school/lunch/",
        "https://district.nutrislice.com/media/gallery/foo",
        "https://district.nutrislice.com/monthly/school/lunch/",
        "ftp://district.nutrislice.com/menu/school/lunch/",
    ],
)
def test_parse_menu_url_rejects_invalid_urls(plugin: Nutrislice, url: str) -> None:
    with pytest.raises(RuntimeError):
        plugin.parse_menu_url(url)


# ---------------------------------------------------------------------------
# format_meal_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    "menu_type,expected",
    [
        ("lunch", "Lunch Menu"),
        ("breakfast", "Breakfast Menu"),
        ("secondary-lunch", "Secondary Lunch Menu"),
        ("elementary-lunch-menu", "Elementary Lunch Menu"),
        ("menu", "Menu"),
    ],
)
def test_format_meal_type(plugin: Nutrislice, menu_type: str, expected: str) -> None:
    assert plugin.format_meal_type(menu_type) == expected


# ---------------------------------------------------------------------------
# compute_item_scale
# ---------------------------------------------------------------------------


def test_compute_item_scale_no_items_returns_max_scale(plugin: Nutrislice) -> None:
    assert plugin.compute_item_scale(0) == 1.15


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    "max_items", [1, 5, 7, 11, 20, 100]
)
def test_compute_item_scale_stays_within_readable_bounds(
    plugin: Nutrislice, max_items: int
) -> None:
    scale = plugin.compute_item_scale(max_items)
    assert 0.4 <= scale <= 1.15


def test_compute_item_scale_decreases_as_items_increase(plugin: Nutrislice) -> None:
    scales = [plugin.compute_item_scale(n) for n in [3, 7, 11, 20]]
    assert scales == sorted(scales, reverse=True)


# ---------------------------------------------------------------------------
# validate_settings
# ---------------------------------------------------------------------------


def test_validate_settings_requires_url(plugin: Nutrislice) -> None:
    assert plugin.validate_settings({}) is not None
    assert plugin.validate_settings({"menuUrl": "   "}) is not None


def test_validate_settings_rejects_bad_url(plugin: Nutrislice) -> None:
    err = plugin.validate_settings({"menuUrl": "https://example.com/not-nutrislice"})
    assert err is not None
    assert "Nutrislice" in err


def test_validate_settings_accepts_good_url(plugin: Nutrislice) -> None:
    err = plugin.validate_settings(
        {"menuUrl": "https://district.nutrislice.com/menu/school/lunch/"}
    )
    assert err is None


# ---------------------------------------------------------------------------
# parse_menu_items
# ---------------------------------------------------------------------------


def test_parse_menu_items_extracts_name_and_carbs(plugin: Nutrislice) -> None:
    items = plugin.parse_menu_items([_food_item("Taco Salad", 41.0)])
    assert items == [{"name": "Taco Salad", "carbs": 41.0}]


def test_parse_menu_items_skips_section_titles_and_blank_entries(
    plugin: Nutrislice,
) -> None:
    menu_items = [
        {"text": "Gluten Free Option", "is_section_title": True},
        {"text": ""},
        _food_item("Corn", 17.0),
        {"food": {}},  # food with no name
    ]
    items = plugin.parse_menu_items(menu_items)
    assert items == [{"name": "Corn", "carbs": 17.0}]


def test_parse_menu_items_handles_missing_nutrition_info(plugin: Nutrislice) -> None:
    items = plugin.parse_menu_items([{"food": {"name": "Mystery Item"}}])
    assert items == [{"name": "Mystery Item", "carbs": None}]


# ---------------------------------------------------------------------------
# extract_days
# ---------------------------------------------------------------------------


def test_extract_days_skips_past_dates(plugin: Nutrislice) -> None:
    today = datetime(2026, 8, 18).date()
    raw_days = [
        {"date": "2026-08-17", "menu_items": [_food_item()]},
        {"date": "2026-08-18", "menu_items": [_food_item()]},
        {"date": "2026-08-19", "menu_items": [_food_item()]},
    ]
    days = plugin.extract_days(raw_days, today, limit=10, seen_dates=set())
    assert [d["date_label"] for d in days] == ["Aug 18", "Aug 19"]


def test_extract_days_handles_null_menu_items(plugin: Nutrislice) -> None:
    """A day with menu_items explicitly set to null must not crash (not just missing)."""
    today = datetime(2026, 8, 18).date()
    raw_days: list[dict[str, Any]] = [{"date": "2026-08-18", "menu_items": None}]
    days = plugin.extract_days(raw_days, today, limit=10, seen_dates=set())
    assert days == []


def test_extract_days_skips_days_with_no_food_items(plugin: Nutrislice) -> None:
    today = datetime(2026, 8, 18).date()
    raw_days = [
        {"date": "2026-08-18", "menu_items": []},
        {
            "date": "2026-08-19",
            "menu_items": [{"text": "Closed", "is_section_title": True}],
        },
    ]
    days = plugin.extract_days(raw_days, today, limit=10, seen_dates=set())
    assert days == []


def test_extract_days_respects_limit(plugin: Nutrislice) -> None:
    today = datetime(2026, 8, 18).date()
    raw_days = [
        {"date": f"2026-08-{d}", "menu_items": [_food_item()]} for d in range(18, 24)
    ]
    days = plugin.extract_days(raw_days, today, limit=2, seen_dates=set())
    assert len(days) == 2


def test_extract_days_skips_dates_already_seen(plugin: Nutrislice) -> None:
    today = datetime(2026, 8, 18).date()
    raw_days = [{"date": "2026-08-18", "menu_items": [_food_item()]}]
    seen: set[date] = {today}
    days = plugin.extract_days(raw_days, today, limit=10, seen_dates=seen)
    assert days == []


# ---------------------------------------------------------------------------
# fetch_menu
# ---------------------------------------------------------------------------


def test_fetch_menu_skips_second_week_when_first_week_is_enough(
    plugin: Nutrislice,
) -> None:
    today = datetime(2026, 8, 18)
    week = [{"date": "2026-08-18", "menu_items": [_food_item()]}]

    with patch.object(plugin, "fetch_week", return_value=week) as mock_fetch_week:
        days = plugin.fetch_menu("district", "school", "lunch", 1, today)

    assert len(days) == 1
    mock_fetch_week.assert_called_once()


def test_fetch_menu_fetches_second_week_when_first_week_is_short(
    plugin: Nutrislice,
) -> None:
    today = datetime(2026, 8, 18)
    week1 = [{"date": "2026-08-18", "menu_items": [_food_item()]}]
    week2 = [{"date": "2026-08-25", "menu_items": [_food_item()]}]

    with patch.object(plugin, "fetch_week", side_effect=[week1, week2]) as mock_fetch:
        days = plugin.fetch_menu("district", "school", "lunch", 3, today)

    assert len(days) == 2
    assert mock_fetch.call_count == 2


def test_fetch_menu_raises_when_first_week_fetch_fails(plugin: Nutrislice) -> None:
    with (
        patch.object(plugin, "fetch_week", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError, match="Failed to fetch menu"),
    ):
        plugin.fetch_menu("district", "school", "lunch", 3, datetime(2026, 8, 18))


def test_fetch_menu_tolerates_second_week_fetch_failure(plugin: Nutrislice) -> None:
    today = datetime(2026, 8, 18)
    week1 = [{"date": "2026-08-18", "menu_items": [_food_item()]}]

    with patch.object(plugin, "fetch_week", side_effect=[week1, RuntimeError("boom")]):
        days = plugin.fetch_menu("district", "school", "lunch", 3, today)

    assert len(days) == 1


def test_fetch_menu_raises_when_no_upcoming_days(plugin: Nutrislice) -> None:
    with (
        patch.object(plugin, "fetch_week", return_value=[]),
        pytest.raises(RuntimeError, match="No upcoming menu items"),
    ):
        plugin.fetch_menu("district", "school", "lunch", 3, datetime(2026, 8, 18))


# ---------------------------------------------------------------------------
# generate_image
#
# Only the paths that fail *before* rendering live here — the actual
# Jinja/Chromium render needs a real host and is covered in
# tests/integration/test_nutrislice_integration.py.
# ---------------------------------------------------------------------------


def test_generate_image_rejects_missing_menu_url(plugin: Nutrislice) -> None:
    with pytest.raises(RuntimeError, match="required"):
        plugin.generate_image({}, _FakeDeviceConfig())


def test_generate_image_rejects_unrecognized_menu_url(plugin: Nutrislice) -> None:
    with pytest.raises(RuntimeError, match="Unrecognized"):
        plugin.generate_image({"menuUrl": "https://example.com/lunch"}, _FakeDeviceConfig())


# ---------------------------------------------------------------------------
# build_settings_schema — the shape assertions. Rendering the schema through
# InkyPi's real Jinja macros (which is what catches a silently-dropped field
# kwarg) needs the host's templates/, so it lives in the integration suite.
# ---------------------------------------------------------------------------


def test_settings_schema_has_expected_fields(plugin: Nutrislice) -> None:
    schema = plugin.build_settings_schema()
    field_names = {
        item["name"]
        for section in schema["sections"]
        for item in section["items"]
        if item.get("kind") == "field"
    }
    row_field_names = {
        row_item["name"]
        for section in schema["sections"]
        for item in section["items"]
        if item.get("kind") == "row"
        for row_item in item["items"]
        if row_item.get("kind") == "field"
    }
    assert {"menuUrl"} <= field_names
    assert {"daysToShow", "showCarbs"} <= row_field_names
