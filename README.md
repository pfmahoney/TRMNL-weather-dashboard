# TRMNL weather dashboard

Home Assistant pages for a [TRMNL](https://usetrmnl.com) OG e-ink display running against a
self-hosted [Terminus](https://github.com/usetrmnl/byos_hanami) server. Plain Python 3 standard
library, no dependencies.

The key thing that makes this interesting is the weather icon and format which is a bit different from others. 
Additionally the integration with Tempest for the weather is a bit different than others out there.   There are
other pages added - like a house page and a solar generation and house usage graph which could be useful as
templates for others.

Three 800×480 pages:

- **Weather** (home page): current conditions from a local Tempest station via Home Assistant,
  a hand-drawn 1-bit weather icon with the real moon phase at night, and today plus a 5-day forecast
  taken verbatim from the Tempest `better_forecast` API, with per-day max wind and gust. Falls back
  to Home Assistant's `weather.get_forecasts` if the Tempest API is unreachable.
- **House**: thermostat, garage doors, radon, and a configurable list of extra sensors
  (temperature, humidity, water leak, or any numeric sensor).
- **Solar**: generation and usage now, today's totals, and an hourly kWh bar chart.

Temperatures are shown in both °C and °F.

## How it works

- `render.py` reads Home Assistant over its REST API, builds HTML for each page, and creates or
  updates one Terminus screen per page. Run it every few minutes (a systemd timer works well).
- `display_proxy.py` sits in front of Terminus' `GET /api/display` and decides which page the
  device gets. The TRMNL firmware doesn't report why it woke, so it goes by timing:
  - a wake at the normal interval is a timer wake and gets the **weather** page;
  - a wake well before that is a button press and gets the **next page** in `rotation`.

  It also rewrites `refresh_rate`: the weather page uses the device's refresh rate from Terminus
  (for example 1 hour), while the other pages get `page_refresh_s` (5 minutes), so the display
  returns to weather shortly after you browse away from it.

  Route `/api/display` to the proxy in your reverse proxy (for example Caddy) and send everything
  else straight to Terminus.

## Setup

1. Copy `config.example.json` to `config.json` and fill in your Home Assistant URL, entity IDs,
   Terminus model and playlist IDs, and Tempest station ID.
2. Put secrets in the files the config points to (each file holds just the secret):
   a Home Assistant long-lived access token, the password of a Terminus account for the renderer,
   and a Tempest API token.
3. Run `./render.py --dump` to write the pages to `/tmp/*.html` for a quick look in a browser,
   then `./render.py` to push them to Terminus.
4. Run `./display_proxy.py` as a service and point `/api/display` at it.

`state.json`, `screens.json` and `display_state.json` are created at runtime. Delete
`display_state.json` to reset the proxy's page tracking.

## License

MIT. See [LICENSE](LICENSE).
