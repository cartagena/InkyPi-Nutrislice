# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A single third-party plugin for [InkyPi](https://github.com/jtn0123/InkyPi) (an e-ink display framework). It renders a school cafeteria's Nutrislice menu — optionally with per-item carb counts — onto the display.

**Requires the [jtn0123/InkyPi](https://github.com/jtn0123/InkyPi) fork, not upstream**. `nutrislice.py` imports four host APIs that exist only in that fork — `plugins.base_plugin.settings_schema` (the schema DSL), `DeviceConfigLike`, `utils.http_client.get_http_session`, and `utils.time_utils.get_timezone` — plus `BasePlugin.get_oriented_dimensions`. On upstream this fails at import time. Unlike the sibling [InkyPi-BloodSugar](https://github.com/cartagena/InkyPi-BloodSugar) plugin, which guards its one fork-only import and degrades to `settings.html`, there is no upstream fallback path here; don't add fork-only imports without deciding which of those two stances this repo is taking. It is not a standalone runnable app: `inkypi plugin install` clones this repo and expects the plugin folder at the *repo root* (matching `install/cli/inkypi-plugin`'s `git sparse-checkout set "$PLUGIN_ID"` convention, shared with upstream) — this repo's top-level `nutrislice/` is that folder. It gets copied into an InkyPi checkout at `src/plugins/nutrislice/` and loaded via `src/plugins/nutrislice/plugin-info.json`.

## Commands

There's no build step — this is a Python plugin consumed by a host app.

- **Tests**: two suites, split by what they require. **The old "copy the test file into an InkyPi checkout" workflow is gone** — both suites now run from this repo.
  ```bash
  pip install -r requirements-dev.txt
  pytest tests/unit                    # anywhere: no InkyPi, no network, no browser
  INKYPI_PATH=../InkyPi pytest         # everything, against a real InkyPi checkout
  ```
  `tests/conftest.py` is what makes that work. It registers stand-ins for the host modules `nutrislice.py` imports (`BasePlugin`, `DeviceConfigLike`, the settings-schema DSL, `get_http_session`, `get_timezone`) **only when a real InkyPi isn't importable**; when `INKYPI_PATH` is set it puts `<inkypi>/src` on `sys.path` and stubs nothing, so the identical unit tests run against real host code. CI runs the unit suite both ways deliberately — that's the mechanism that stops these stubs from drifting away from InkyPi's actual behaviour.

  Two consequences worth keeping in mind when editing these files:
  - **The stubs must stay minimal**, covering exactly what `nutrislice.py` imports. A rich fake is precisely what starts passing when the real host has changed. In particular, the stubbed `render_image` *raises* rather than returning a placeholder image, and the stubbed HTTP session raises on `.get()` — so neither a template regression nor an accidental live request can pass the unit suite.
  - **If `INKYPI_PATH` is set but the host still won't import, the conftest raises** rather than falling back to stubs. Silently stubbing there would let CI's integration job report green while having quietly run the unit suite twice.

  `tests/integration/` needs `nutrislice/` symlinked into the checkout (`ln -s <this-repo>/nutrislice <inkypi-checkout>/src/plugins/nutrislice`) because `BasePlugin` resolves `render_dir` relative to `src/plugins/<id>`; the conftest's skip message says so if it's missing. Its tests cover only what needs real host code: loading through the real registry, `plugin-info.json` agreeing with the registered class, a full Jinja + headless-Chromium render, and the schema rendered through the real `settings_schema.html` macros (which is what catches a field kwarg the macros silently ignore — a stubbed schema DSL cannot).
- **Single test**: append `::test_name` to the path (standard pytest selection).
- **Installing the plugin** into an InkyPi instance: `inkypi plugin install nutrislice https://github.com/cartagena/InkyPi-Nutrislice`.

## Architecture

- `nutrislice/nutrislice.py` — the entire plugin. Subclasses InkyPi's `BasePlugin` (imported from the host app, not present in this repo) and implements:
  - `build_settings_schema` — declares the settings UI (menu URL, days-to-show, show-carbs toggle) using InkyPi's schema DSL (`schema`/`section`/`field`/`row`/`option`).
  - `validate_settings` — delegates to `parse_menu_url` so a bad URL is rejected in the settings form before `generate_image` ever runs.
  - `generate_image` — the main entry point InkyPi calls each refresh: parses the configured menu URL, fetches menu data, and renders `render/nutrislice.html` + `render/nutrislice.css` to an image via `BasePlugin.render_image`.
- `parse_menu_url` extracts `(district, school, menu_type)` from a Nutrislice site URL via `NUTRISLICE_URL_PATTERN`; these three values drive the API request in `fetch_week`.
- **Two-week fetch fallback**: `fetch_menu` fetches the current week via `fetch_week`/`extract_days`, and only fetches the following week if the first week didn't yield enough upcoming days (e.g. requesting "Full Week" late on a Friday, or the district hasn't published next week's menu). `seen_dates` is threaded through both calls to prevent a second week's response from duplicating a date already picked from the first.
- **Item scaling**: `compute_item_scale` shrinks font size/spacing proportionally to the busiest day's item count (tuned for ~7 items, clamped to `[0.4, 1.15]`) so districts that publish many entrees/sides don't get clipped off the bottom of the display. This is a proportional heuristic, not pagination — an extreme item count can still overflow.
- **External dependency**: Nutrislice has no official/public API. This plugin calls the same unauthenticated JSON endpoint Nutrislice's own site frontend uses (`https://<district>.api.nutrislice.com/menu/api/weeks/school/<school>/menu-type/<meal-type>/<year>/<month>/<day>/?format=json`), reverse-engineered from a MagicMirror module for the same service (see README for the link). No API key. Because it's unofficial, the response shape can change without notice — if the plugin stops working, that endpoint's response shape is the first thing to check.
- `render/nutrislice.html` + `render/nutrislice.css` — Jinja template extending InkyPi's `plugin.html`, styled per day column; `--day-count` and `--item-scale` CSS custom properties are set inline from `template_params` to drive the responsive layout.
- `tests/unit/test_nutrislice.py` covers URL parsing, meal-type label formatting, item-scale bounds, settings validation, menu-item parsing, date filtering/dedup in `extract_days`, and the two-week fetch fallback logic. `tests/integration/test_nutrislice_integration.py` holds the settings-schema render check that catches field kwargs the Jinja macros would otherwise silently drop — it needs the host's real templates, so it can't live in the unit suite.
