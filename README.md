# InkyPi-Nutrislice

Displays your school's cafeteria menu — with per-item carb counts — from Nutrislice on your [InkyPi](https://github.com/fatihak/InkyPi) e-ink display.

![Nutrislice plugin showing a 3-day school lunch menu with carb counts on an InkyPi display](docs/screenshot.png)

## Features

- Shows the menu for 1 day, 3 days, or the full week
- Optionally displays carb counts (grams) alongside each food item
- Works with any school district that uses Nutrislice
- Item text and spacing auto-scale so busy menu days (many entrees/sides) don't get clipped

## Installation

Install the plugin from this GitHub repository:

```bash
inkypi plugin install nutrislice https://github.com/cartagena/InkyPi-Nutrislice
```

If you're running a fork of InkyPi rather than the upstream project, check that fork's own documentation — plugin installation and loading steps can differ.

## Configuration

| Setting | Description |
| --- | --- |
| **School Menu Url** | Required. The url for your school's menu on your district's Nutrislice site, e.g. `https://<district>.nutrislice.com/menu/<school>/<meal-type>/`. Visit your district's Nutrislice site, select your school and a meal (lunch or breakfast), and copy that page's url. |
| **Days to Show** | `1 Day`, `3 Days`, or `Full Week`. Days with no published menu (weekends, holidays) are skipped automatically. |
| **Show Carbs** | Toggle to show/hide the carbohydrate count (in grams) for each food item. |

## External API

This plugin depends on **Nutrislice**, the vendor that powers school district meal-menu websites (e.g. `https://<district>.nutrislice.com`).

- **API documentation:** None published. Nutrislice does not offer a public/official API or developer docs — this plugin calls the same unauthenticated JSON endpoint their own website's frontend uses (`https://<district>.api.nutrislice.com/menu/api/weeks/school/<school>/menu-type/<meal-type>/<year>/<month>/<day>/?format=json`), reverse-engineered from [kblankenship1989/MMM-nutrislice-menu](https://github.com/kblankenship1989/MMM-nutrislice-menu), a MagicMirror module for the same service. The general [Nutrislice product site](https://www.nutrislice.com/) is the only official reference.
- **API key:** Not required. The endpoint is public and unauthenticated — you only need your district's Nutrislice menu url (see Configuration above).
- **Usage limits / cost:** Free, with no published rate limits or usage tiers (there's nothing to sign up for). Because the API is undocumented and unofficial, Nutrislice could change or restrict it without notice — see Maintenance status below.

## Testing

The plugin has a pytest suite (`tests/plugins/test_nutrislice.py`), but it depends on fixtures and templates from an InkyPi checkout (e.g. `device_config_dev`, `settings_schema.html`), so it isn't runnable from this repo standalone. To run it: drop the test file into `<inkypi-checkout>/tests/plugins/`, then from that checkout run `PYTHONPATH=$(pwd)/src pytest tests/plugins/test_nutrislice.py`.

## Development status

**Actively maintained.** This plugin relies on Nutrislice's unofficial API, which may change without notice. If it stops fetching data, check whether the JSON response shape at the endpoint above has changed, and open an issue in this repo.
