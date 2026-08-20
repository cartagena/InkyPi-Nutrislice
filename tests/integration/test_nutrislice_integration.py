"""Integration tests: Nutrislice against a real InkyPi host.

What earns a place here is anything that can only be verified against real
host code — the plugin loading through InkyPi's own registry, the real
Jinja + headless-Chromium render pipeline, and the real settings-schema
macros. Everything expressible with fakes belongs in ``tests/unit/``, which
runs everywhere and runs fast.

Nutrislice's own upstream API is still mocked here. A CI run must never depend
on a school district's servers being up, and the response shape is already
pinned by the unit suite.
"""

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


@pytest.fixture()
def plugin() -> Any:
    """Load Nutrislice the way InkyPi itself does, through the real registry."""
    from plugins.plugin_registry import get_plugin_instance, load_plugins

    plugin_config = {"id": "nutrislice", "class": "Nutrislice"}
    load_plugins([plugin_config])
    return get_plugin_instance(plugin_config)


def _food_item(name: str, carbs: float) -> dict[str, Any]:
    return {"food": {"name": name, "rounded_nutrition_info": {"g_carbs": carbs}}}


def _mock_week_response(days: list[dict[str, Any]]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"days": days}
    return resp


def test_plugin_loads_through_the_real_registry(plugin: Any) -> None:
    from plugins.base_plugin.base_plugin import BasePlugin

    assert isinstance(plugin, BasePlugin)
    assert plugin.get_plugin_id() == "nutrislice"


def test_plugin_info_json_matches_the_registered_class(plugin: Any) -> None:
    """The installed folder name, id, and class must agree.

    `inkypi plugin install` sparse-checkouts the folder named after the plugin
    id, so a mismatch here breaks installation for every end user while
    everything still works locally.
    """
    from utils.app_utils import resolve_path

    with open(resolve_path("plugins/nutrislice/plugin-info.json"), encoding="utf-8") as f:
        info = json.load(f)

    assert info["id"] == "nutrislice"
    assert info["class"] == type(plugin).__name__


def test_generate_image_renders_through_the_real_pipeline(
    plugin: Any, device_config: Any
) -> None:
    """Full Jinja + headless-Chromium render, with only the menu API mocked.

    This is the one path the unit suite genuinely cannot cover: the stub
    BasePlugin raises on render_image rather than faking an image, precisely
    so a template regression can't slip through green.
    """
    week = [
        {
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "menu_items": [_food_item("Pizza", 30.0), _food_item("Salad", 12.0)],
        }
    ]

    with patch("plugins.nutrislice.nutrislice.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.return_value = _mock_week_response(week)
        result = plugin.generate_image(
            {
                "menuUrl": "https://district.nutrislice.com/menu/school/lunch/",
                "daysToShow": "1",
                "showCarbs": "true",
            },
            device_config,
        )

    assert isinstance(result, Image.Image)
    assert result.size == (800, 480)
    # Not a blank canvas — the template actually drew the menu.
    assert len(result.getcolors(maxcolors=1 << 20)) > 1


def test_settings_schema_renders_through_the_real_template(plugin: Any) -> None:
    """Render the schema through InkyPi's real settings_schema.html template.

    Guards against typos in field kwargs (e.g. a field description under the
    wrong key) that the Jinja macros silently ignore instead of erroring —
    the schema would build fine but the setting would be invisible in the UI.
    A stubbed schema DSL can't catch this; only the host's macros can.
    """
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    from utils.app_utils import resolve_path

    env = Environment(
        loader=FileSystemLoader(resolve_path("templates")),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("settings_schema.html")

    html = template.render(
        settings_schema=plugin.build_settings_schema(), plugin_settings={}
    )

    assert 'name="menuUrl"' in html
    assert 'name="daysToShow"' in html
    assert 'name="showCarbs"' in html
    assert "Visit your school district" in html
    assert "Nutrislice site" in html
