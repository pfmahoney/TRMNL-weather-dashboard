#!/usr/bin/env python3
"""Render Home Assistant data as TRMNL screens and push them to Terminus.

Edit config.json to add/remove sensors. Run every few minutes from a systemd timer.
"""
import datetime as dt
import html
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, "config.json")))
STATE_FILE = os.path.join(BASE, "state.json")
URIS_FILE = os.path.join(BASE, "screens.json")
HA = CFG["ha_url"].rstrip("/")
TERMINUS = CFG["terminus_url"].rstrip("/")
HA_TOKEN = open(CFG["ha_token_file"]).read().strip()
TZ = ZoneInfo(CFG.get("timezone", "America/Denver"))
BAD = ("unavailable", "unknown", "none", "")


# ---------- Home Assistant ----------
def ha_get(path):
    req = urllib.request.Request(HA + path, headers={"Authorization": f"Bearer {HA_TOKEN}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get_states():
    return {s["entity_id"]: s for s in ha_get("/api/states")}


def num(states, entity):
    s = states.get(entity)
    if not s or s["state"].lower() in BAD:
        return None
    try:
        return float(s["state"])
    except ValueError:
        return None


def history(entity, start, end):
    q = urllib.parse.urlencode({
        "filter_entity_id": entity,
        "end_time": end.isoformat(),
        "minimal_response": "1",
        "no_attributes": "1",
    })
    data = ha_get(f"/api/history/period/{urllib.parse.quote(start.isoformat())}?{q}")
    return data[0] if data else []


def power_samples(entity, start, end, max_w):
    """[(datetime, watts)] with unavailable -> 0 and implausible spikes dropped."""
    out = []
    for p in history(entity, start, end):
        t = dt.datetime.fromisoformat(p["last_changed"]).astimezone(TZ)
        t = max(t, start)
        try:
            v = float(p["state"])
        except ValueError:
            v = 0.0
        if v < 0 or v > max_w:
            continue
        out.append((t, v))
    return out


def hourly_kwh(samples, start, end, max_gap=None):
    """max_gap: a reading counts for at most this long; a source that stops
    reporting (inverter off at night) then contributes nothing after the gap."""
    kwh = [0.0] * 24
    for i, (t, w) in enumerate(samples):
        t2 = samples[i + 1][0] if i + 1 < len(samples) else end
        if max_gap is not None:
            t2 = min(t2, t + max_gap)
        while t < t2:
            nxt = min(t2, (t.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)))
            if t.date() == start.date():
                kwh[t.hour] += w * (nxt - t).total_seconds() / 3600 / 1000
            t = nxt
    return kwh


# ---------- formatting ----------
def f_temp(c):
    return "--" if c is None else f"{c * 9 / 5 + 32:.1f}"


def c_temp(c):
    return "--" if c is None else f"{c:.1f}"


def both_temp(c, digits=1):
    """'20.8°C · 69.5°F' for a Celsius value."""
    if c is None:
        return "--"
    return f"{c:.{digits}f}°C · {c * 9 / 5 + 32:.{digits}f}°F"


def esc(x):
    return html.escape(str(x))


def kw(w):
    return f"{w / 1000:.2f}"


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body,html{width:800px;height:480px;background:#fff;color:#000;font-family:'DejaVu Sans',Arial,Helvetica,sans-serif;overflow:hidden}
.page{width:800px;height:480px;display:flex;flex-direction:column}
.bar{height:44px;background:#000;color:#fff;display:flex;justify-content:space-between;align-items:center;padding:0 18px;font-size:22px;font-weight:700;letter-spacing:2px}
.bar span.t{font-size:18px;font-weight:400;letter-spacing:0}
.grid{flex:1;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr}
.tile{padding:12px 18px;border-right:3px solid #000;border-bottom:3px solid #000;overflow:hidden}
.tile:nth-child(2n){border-right:none}.tile:nth-child(n+3){border-bottom:none}
h2{font-size:15px;letter-spacing:2px;text-transform:uppercase;font-weight:700;margin-bottom:6px;color:#333}
.big{font-size:72px;font-weight:700;line-height:1}
.big small{font-size:30px;font-weight:400}
.sub{font-size:20px;margin-top:8px}
.row{display:flex;justify-content:space-between;align-items:center;font-size:22px;padding:5px 0;border-bottom:1px solid #999}
.row:last-child{border-bottom:none}
.row.sm{font-size:19px;padding:3px 0}
.pill{background:#000;color:#fff;padding:2px 12px;border-radius:14px;font-weight:700;font-size:20px}
.pill.ok{background:#fff;color:#000;border:2px solid #000}
.dim{color:#555}
.cols{flex:1;display:flex}
.left{width:280px;border-right:3px solid #000;padding:8px 16px;display:flex;flex-direction:column;justify-content:space-between}
.stat .l{font-size:14px;letter-spacing:2px;text-transform:uppercase;font-weight:700;color:#333}
.stat .v{font-size:46px;font-weight:700;line-height:1.05}
.stat .v small{font-size:20px;font-weight:400}
.stat .v.m{font-size:34px}
.right{flex:1;padding:8px 6px 0 6px}
.wtop{height:220px;display:flex;border-bottom:3px solid #000}
.wnow{width:400px;padding:12px 18px;border-right:3px solid #000;position:relative}
.wicon{position:absolute;right:16px;top:26px}
.wtoday{flex:1;padding:12px 18px}
.wword{font-size:40px;font-weight:700;line-height:1.1}
.whl{font-size:34px;font-weight:700;margin-top:6px}
.wdays{flex:1;display:flex}
.wday{flex:1;padding:8px 6px;border-right:2px solid #000;text-align:center}
.wday:last-child{border-right:none}
.wd{font-size:20px;font-weight:700;letter-spacing:2px;text-transform:uppercase}
.ww{font-size:19px;line-height:1.15;margin:6px 0 6px;height:44px;display:flex;align-items:center;justify-content:center}
.wc{font-size:24px;font-weight:700}
.wf{font-size:17px;margin-top:4px}
.wp{font-size:15px;margin-top:5px;color:#333}
"""


def wrap(title, right_text, body):
    return f"<style>{CSS}</style><div class='page'><div class='bar'><div>{esc(title)}</div><span class='t'>{esc(right_text)}</span></div>{body}</div>"


# ---------- page 1: house ----------
def page_house(states, now):
    c = CFG["house"]
    ecobee = states.get(c["thermostat"], {"attributes": {}, "state": "?"})
    a = ecobee["attributes"]
    temp = num(states, c["indoor_temp"])
    if temp is None:
        temp = a.get("current_temperature")
    hum = num(states, c["indoor_humidity"])
    target = a.get("temperature") or a.get("target_temp_low")
    mode = ecobee["state"]
    action = a.get("hvac_action", "")
    mode_txt = f"{mode.upper()}" + (f" · {action}" if action and action != "idle" else "")
    tgt_txt = f" → {target:.1f}°C / {target * 9 / 5 + 32:.0f}°F" if isinstance(target, (int, float)) and mode != "off" else ""
    indoor = f"""<div class='tile'><h2>Indoor · Ecobee</h2>
      <div class='big'>{c_temp(temp)}<small>°C</small></div>
      <div class='sub' style='font-size:30px;font-weight:700'>{f_temp(temp)}°F</div>
      <div class='sub'>{'--' if hum is None else f'{hum:.0f}'}% humidity</div>
      <div class='sub dim'>{esc(mode_txt)}{tgt_txt}</div></div>"""

    rows = ""
    for g in c["garage"]:
        st = states.get(g["entity"], {"state": "unknown"})["state"]
        closed = st == "closed"
        pill = f"<span class='pill ok'>CLOSED</span>" if closed else f"<span class='pill'>{esc(st.upper())}</span>"
        rows += f"<div class='row'><span>{esc(g['label'])}</span>{pill}</div>"
    garage = f"<div class='tile'><h2>Garage</h2>{rows}</div>"

    r = c["radon"]
    rv = num(states, r["entity"])
    rs = states.get(r["entity"], {})
    if rv is None:
        since = rs.get("last_updated", "")[:10]
        radon_body = f"""<div class='big' style='font-size:54px'>NO DATA</div>
          <div class='sub dim'>sensor offline{f' since {since}' if since else ''}</div>"""
    else:
        # HA may report radon in Bq/m³ or (after unit conversion in HA) pCi/L
        def to_pci(eid, v):
            u = states.get(eid, {"attributes": {}})["attributes"].get("unit_of_measurement", "")
            return v if u.lower().startswith("pci") else v / 37.0
        pci = to_pci(r["entity"], rv)
        lvl = "LOW" if pci < 2.7 else ("ELEVATED" if pci < 4.0 else "HIGH")
        lt = num(states, r.get("longterm", ""))
        lt_txt = f" · long-term {to_pci(r['longterm'], lt):.1f} pCi/L" if lt is not None else ""
        radon_body = f"""<div class='big'>{pci:.1f}<small> pCi/L</small></div>
          <div class='sub'><b>{lvl}</b> · EPA action level 4.0</div>
          <div class='sub dim' style='font-size:18px'>1-day avg{lt_txt} · {esc(rs.get('last_updated','')[:10])}</div>"""
    radon = f"<div class='tile'><h2>Radon · Airthings</h2>{radon_body}</div>"

    rows = ""
    for e in c.get("extras", []):
        v = num(states, e["entity"])
        k = e.get("kind", "number")
        if k == "temp":
            val = both_temp(v)
        elif k == "humidity":
            val = "--" if v is None else f"{v:.0f}%"
        elif k == "leak":
            st = states.get(e["entity"], {"state": "unknown"})["state"]
            val = "<span class='pill ok'>DRY</span>" if st == "off" else (
                "<span class='pill'>WET!</span>" if st == "on" else "<span class='dim'>offline</span>")
        else:
            u = states.get(e["entity"], {"attributes": {}})["attributes"].get("unit_of_measurement", "")
            val = "--" if v is None else f"{v:g} {u}"
        rows += f"<div class='row sm'><span>{esc(e['label'])}</span><span>{val}</span></div>"
    if not rows:
        rows = "<div class='sub dim'>No extra sensors configured</div>"
    extras = f"<div class='tile'><h2>Rooms &amp; water</h2>{rows}</div>"

    return wrap("HOME", now.strftime("%a %b %-d  %-I:%M %p"), f"<div class='grid'>{indoor}{garage}{radon}{extras}</div>")


# ---------- page 2: solar ----------
def nice_max(v):
    for s in (0.4, 0.8, 1.2, 2, 2.4, 3.2, 4, 6, 8, 12, 16, 20):
        if v <= s:
            return s
    return v


def chart_svg(gen, use, now_hour):
    W, H, ml, mb, mt = 500, 360, 38, 26, 10
    pw, ph = W - ml - 6, H - mb - mt
    ymax = nice_max(max(max(gen), max(use), 0.1))
    gw = pw / 24
    bw = gw * 0.42
    out = [f"<svg width='{W}' height='{H}' viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' font-family='DejaVu Sans,Arial' font-size='13'>"]
    for i in range(5):
        y = mt + ph - ph * i / 4
        out.append(f"<line x1='{ml}' y1='{y:.1f}' x2='{W - 6}' y2='{y:.1f}' stroke='#555' stroke-width='1' stroke-dasharray='2 4'/>")
        out.append(f"<text x='{ml - 5}' y='{y + 4:.1f}' text-anchor='end'>{ymax * i / 4:g}</text>")
    for h in range(24):
        x0 = ml + h * gw + gw * 0.08
        for j, (val, fill, stroke) in enumerate(((gen[h], "#000", "#000"), (use[h], "#fff", "#000"))):
            bh = ph * val / ymax
            if bh > 0.5:
                out.append(f"<rect x='{x0 + j * bw:.1f}' y='{mt + ph - bh:.1f}' width='{bw:.1f}' height='{bh:.1f}' fill='{fill}' stroke='{stroke}' stroke-width='1'/>")
    for h in range(0, 24, 3):
        lab = "12a" if h == 0 else ("12p" if h == 12 else (f"{h}a" if h < 12 else f"{h - 12}p"))
        out.append(f"<text x='{ml + h * gw + gw / 2:.1f}' y='{H - 8}' text-anchor='middle'>{lab}</text>")
    out.append(f"<line x1='{ml}' y1='{mt + ph}' x2='{W - 6}' y2='{mt + ph}' stroke='#000' stroke-width='2'/>")
    out.append("</svg>")
    return "".join(out)


def page_solar(states, now):
    c = CFG["solar"]
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stale = dt.timedelta(seconds=c.get("stale_after_s", 300))
    gen_w = num(states, c["power"])
    gen_w = 0.0 if gen_w is None or gen_w < 0 or gen_w > c["max_w"] else gen_w
    # The inverter powers down at dusk and HA keeps its last value forever.
    last = states.get(c["power"], {}).get("last_reported") or states.get(c["power"], {}).get("last_updated")
    if last and now - dt.datetime.fromisoformat(last).astimezone(TZ) > stale:
        gen_w = 0.0
    use_w = num(states, c["usage_power"]) or 0.0

    gen_s = power_samples(c["power"], start, now, c["max_w"])
    use_s = power_samples(c["usage_power"], start, now, 60000)
    gen_h, use_h = hourly_kwh(gen_s, start, now, stale), hourly_kwh(use_s, start, now)

    # Daily generation from the cleaned lifetime counter (robust to bad polls)
    gen_day = None
    cum = num(states, c["energy_total_kwh"])
    first = [p for p in history(c["energy_total_kwh"], start, now) if p["state"].replace(".", "", 1).isdigit()]
    if cum is not None and first:
        gen_day = max(cum - float(first[0]["state"]), 0.0)
    if gen_day is None:
        gen_day = sum(gen_h)
    use_wh = num(states, c["usage_daily_wh"])
    use_day = use_wh / 1000 if use_wh is not None else sum(use_h)

    net = use_w - gen_w
    net_txt = f"Export {abs(net) / 1000:.2f} kW" if net < 0 else f"Import {net / 1000:.2f} kW"

    left = f"""<div class='left'>
      <div class='stat'><div class='l'>Solar now</div><div class='v'>{kw(gen_w)}<small> kW</small></div></div>
      <div class='stat'><div class='l'>Using now</div><div class='v'>{kw(use_w)}<small> kW</small></div></div>
      <div class='stat'><div class='l'>Net</div><div class='v m' style='font-size:24px'>{net_txt}</div></div>
      <div class='stat'><div class='l'>Generated today</div><div class='v m'>{gen_day:.1f}<small> kWh</small></div></div>
      <div class='stat'><div class='l'>Used today</div><div class='v m'>{use_day:.1f}<small> kWh</small></div></div></div>"""
    legend = "<div style='font-size:13px;display:flex;gap:16px;padding:0 0 0 38px'><span>■ Solar</span><span>□ Usage</span><span>kWh per hour</span></div>"
    right = f"<div class='right'>{legend}{chart_svg(gen_h, use_h, now.hour)}</div>"
    return wrap("SOLAR", now.strftime("%a %b %-d  %-I:%M %p"), f"<div class='cols'>{left}{right}</div>")



# ---------- weather icons (1-bit friendly inline SVG, 64x64 viewBox) ----------
SYNODIC = 29.530588853
NEW_MOON_REF = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)
INK = "stroke='#000' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round'"


def moon_phase(when):
    """0 = new, 0.25 = first quarter, 0.5 = full, 0.75 = last quarter."""
    return ((when - NEW_MOON_REF).total_seconds() / 86400 / SYNODIC) % 1.0


def _sun(cx, cy, r):
    rays = ""
    for i in range(8):
        a = math.pi * i / 4
        x1, y1 = cx + math.cos(a) * (r + 5), cy + math.sin(a) * (r + 5)
        x2, y2 = cx + math.cos(a) * (r + 11), cy + math.sin(a) * (r + 11)
        rays += f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' {INK}/>"
    return f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='#fff' {INK}/>{rays}"


def _moon(cx, cy, r, phase):
    """Calendar convention: dark part filled black, lit part white (full = open circle, new = black disk).
    Northern-hemisphere orientation (waxing lit on the right)."""
    k = (1 - math.cos(2 * math.pi * phase)) / 2          # illuminated fraction
    edge = f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='none' {INK}/>"
    if k < 0.03:
        return f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='#000'/>" + edge
    if k > 0.97:
        return f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='#fff'/>" + edge
    rx = r * abs(1 - 2 * k)
    top, bot = f"{cx} {cy - r}", f"{cx} {cy + r}"
    gibbous = k > 0.5
    if phase < 0.5:   # waxing: lit on the right
        lit = f"M {top} A {r} {r} 0 0 1 {bot} A {rx:.2f} {r} 0 0 {1 if gibbous else 0} {top} Z"
    else:             # waning: lit on the left
        lit = f"M {top} A {r} {r} 0 0 0 {bot} A {rx:.2f} {r} 0 0 {0 if gibbous else 1} {top} Z"
    return (f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='#000'/>"
            f"<path d='{lit}' fill='#fff' stroke='none'/>" + edge)


def _star(x, y, r):
    return (f"<path d='M{x} {y - r} L{x + r * .3:.1f} {y - r * .3:.1f} L{x + r} {y} L{x + r * .3:.1f} {y + r * .3:.1f} "
            f"L{x} {y + r} L{x - r * .3:.1f} {y + r * .3:.1f} L{x - r} {y} L{x - r * .3:.1f} {y - r * .3:.1f} Z' fill='#000'/>")


def _cloud(dx=0, dy=0, s=1.0):
    d = "M18 46 H48 A10 10 0 0 0 48 26 A14 14 0 0 0 21 23 A11.6 11.6 0 0 0 18 46 Z"
    return f"<g transform='translate({dx} {dy}) scale({s})'><path d='{d}' fill='#fff' {INK}/></g>"


def _drops(n=3, y=50):
    xs = (22, 32, 42)[:n] if n == 3 else (26, 38)
    return "".join(f"<line x1='{x}' y1='{y}' x2='{x - 4}' y2='{y + 9}' {INK}/>" for x in xs)


def _flakes(y=55):
    out = ""
    for x in (19, 32, 45):
        for a in (90, 30, 150):
            r = math.radians(a)
            out += (f"<line x1='{x - 4.5 * math.cos(r):.1f}' y1='{y - 4.5 * math.sin(r):.1f}' "
                    f"x2='{x + 4.5 * math.cos(r):.1f}' y2='{y + 4.5 * math.sin(r):.1f}' "
                    f"stroke='#000' stroke-width='2' stroke-linecap='round'/>")
    return out


def _bolt():
    return "<path d='M34 44 L26 56 H32 L28 64 L40 50 H34 L38 44 Z' fill='#000' stroke='#000' stroke-width='1.5' stroke-linejoin='round'/>"


def _behind(name, phase):
    """Small sun or moon peeking out behind a cloud (upper left)."""
    return _sun(22, 20, 8) if name.endswith("-day") else _moon(22, 20, 11, phase)


def weather_icon(name, when, size=96):
    name = name or "cloudy"
    phase = moon_phase(when)
    if name == "clear-day":
        body = _sun(32, 32, 13)
    elif name == "clear-night":
        body = _moon(28, 34, 19, phase) + _star(54, 10, 5) + _star(56, 30, 3.5)
    elif name.startswith("partly-cloudy"):
        body = _behind(name, phase) + _cloud(4, 8)
    elif name == "cloudy":
        body = _cloud(-8, -6, 0.8) + _cloud(4, 6)
    elif name == "foggy":
        body = _cloud(0, -8) + "".join(
            f"<line x1='{x1}' y1='{y}' x2='{x2}' y2='{y}' {INK}/>" for x1, x2, y in ((12, 52, 46), (16, 48, 53), (12, 52, 60)))
    elif name.startswith("possibly-rainy"):
        body = _behind(name, phase) + _cloud(4, -2) + _drops(2)
    elif name == "rainy":
        body = _cloud(0, -4) + _drops(3)
    elif name.startswith("possibly-snow"):
        body = _behind(name, phase) + _cloud(4, -2) + _flakes()
    elif name == "snow":
        body = _cloud(0, -4) + _flakes()
    elif "sleet" in name:
        body = (_behind(name, phase) if name.startswith("possibly") else "") + _cloud(0, -4) + _drops(2) + \
            "".join(f"<circle cx='{x}' cy='57' r='2.2' fill='#000'/>" for x in (32, 44))
    elif "thunderstorm" in name:
        body = (_behind(name, phase) if name.startswith("possibly") else "") + _cloud(0, -6) + _bolt()
    elif name == "windy":
        body = "".join(
            f"<path d='M8 {y} H{x} a6 6 0 1 0 -6 -6' fill='none' {INK}/>" for x, y in ((40, 26), (48, 38))) + \
            f"<line x1='8' y1='50' x2='36' y2='50' {INK}/>"
    else:
        body = _cloud()
    return (f"<svg width='{size}' height='{size}' viewBox='-2 -2 68 68' xmlns='http://www.w3.org/2000/svg'>"
            f"{body}</svg>")


HA_TO_ICON = {
    "clear-night": "clear-night", "sunny": "clear-day", "partlycloudy": "partly-cloudy-day",
    "cloudy": "cloudy", "fog": "foggy", "hail": "sleet", "lightning": "thunderstorm",
    "lightning-rainy": "thunderstorm", "pouring": "rainy", "rainy": "rainy", "snowy": "snow",
    "snowy-rainy": "sleet", "windy": "windy", "windy-variant": "windy",
}


# ---------- page 3: weather ----------
WORD = {
    "clear-night": "Clear", "sunny": "Sunny", "partlycloudy": "Fair", "cloudy": "Cloudy",
    "fog": "Fog", "hail": "Hail", "lightning": "Storms", "lightning-rainy": "Storms",
    "pouring": "Downpour", "rainy": "Rain", "snowy": "Snow", "snowy-rainy": "Sleet",
    "windy": "Windy", "windy-variant": "Windy", "exceptional": "Severe",
}


def word(cond):
    return WORD.get(cond or "", (cond or "--").capitalize())


def daily_forecast(entity):
    req = urllib.request.Request(
        f"{HA}/api/services/weather/get_forecasts?return_response",
        data=json.dumps({"entity_id": entity, "type": "daily"}).encode(), method="POST",
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["service_response"][entity]["forecast"]


def tempest_forecast(c, now):
    """Verbatim Tempest daily forecast + per-day max wind/gust (km/h) from the hourly forecast."""
    q = urllib.parse.urlencode({"station_id": c["tempest_station_id"],
                                "token": open(c["tempest_token_file"]).read().strip(),
                                "units_temp": "c", "units_wind": "kph", "units_precip": "mm"})
    with urllib.request.urlopen(f"https://swd.weatherflow.com/swd/rest/better_forecast?{q}", timeout=30) as r:
        d = json.load(r)
    wind = {}
    for h in d["forecast"]["hourly"]:
        day = dt.datetime.fromtimestamp(h["time"], TZ).date()
        w, g = wind.get(day, (0.0, 0.0))
        wind[day] = (max(w, h.get("wind_avg") or 0), max(g, h.get("wind_gust") or 0))
    days = []
    for f in d["forecast"]["daily"]:
        day = dt.datetime.fromtimestamp(f["day_start_local"], TZ).date()
        w, g = wind.get(day, (None, None))
        days.append({"day": day, "text": f.get("conditions"), "hi": f.get("air_temp_high"),
                     "lo": f.get("air_temp_low"), "pp": f.get("precip_probability"),
                     "wind": w, "gust": g, "icon": f.get("icon")})
    cc = d.get("current_conditions", {})
    return cc.get("conditions"), cc.get("icon"), days


def ha_forecast(c, now):
    """Fallback: HA's normalized forecast if the Tempest API is unreachable."""
    days = []
    for f in daily_forecast(c["entity"]):
        days.append({"day": dt.datetime.fromisoformat(f["datetime"]).astimezone(TZ).date(),
                     "text": word(f.get("condition")), "hi": f.get("temperature"), "lo": f.get("templow"),
                     "pp": f.get("precipitation_probability"), "wind": None, "gust": None,
                     "icon": HA_TO_ICON.get(f.get("condition"))})
    return None, None, days


def observed_max(entity, start, now):
    vals = []
    for p in history(entity, start, now):
        try:
            vals.append(float(p["state"]))
        except ValueError:
            pass
    return max(vals) if vals else None


def hilo(f):
    hi, lo = f.get("hi"), f.get("lo")
    if hi is None or lo is None:
        return "--", ""
    return f"{hi:.0f}° / {lo:.0f}°C", f"{hi * 9 / 5 + 32:.0f}° / {lo * 9 / 5 + 32:.0f}°F"


def wind_txt(f):
    if f.get("wind") is None:
        return ""
    return f"Wind {f['wind']:.0f} · gust {f['gust']:.0f} km/h"


def page_weather(states, now):
    c = CFG["weather"]
    w = states.get(c["entity"], {"state": "", "attributes": {}})
    a = w["attributes"]
    temp = num(states, c.get("temp", "")) if c.get("temp") else None
    temp = a.get("temperature") if temp is None else temp
    feels = num(states, c.get("feels_like", "")) if c.get("feels_like") else None
    hum = num(states, c.get("humidity", "")) if c.get("humidity") else None
    hum = a.get("humidity") if hum is None else hum
    wind = num(states, c.get("wind", "")) if c.get("wind") else None
    wind = a.get("wind_speed") if wind is None else wind

    try:
        now_text, now_icon, fc = tempest_forecast(c, now)
        src = ""
    except Exception as e:
        print(f"tempest forecast failed, using HA: {e!r}", file=sys.stderr)
        now_text, now_icon, fc = ha_forecast(c, now)
        src = " (HA)"
    now_text = now_text or word(w["state"])
    if not now_icon:
        now_icon = HA_TO_ICON.get(w["state"], "cloudy")
        if states.get("sun.sun", {}).get("state") == "below_horizon":
            now_icon = now_icon.replace("-day", "-night")
    today = next((f for f in fc if f["day"] == now.date()), None)
    rest = [f for f in fc if f["day"] > now.date()][:5]

    # Today's max = max(observed since midnight, forecast for the rest of the day)
    if today is not None:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for key, ent in (("wind", c.get("wind_obs")), ("gust", c.get("gust_obs"))):
            obs = observed_max(ent, midnight, now) if ent else None
            if obs is not None:
                today[key] = max(obs, today[key] or 0)

    details = []
    if feels is not None:
        details.append(f"Feels {feels:.0f}°C")
    if hum is not None:
        details.append(f"{hum:.0f}% RH")
    if wind is not None:
        details.append(f"Wind {wind:.0f} km/h")
    cur = f"""<div class='wnow'><div class='wicon'>{weather_icon(now_icon, now, 112)}</div><h2>Now</h2>
      <div class='big'>{c_temp(temp)}<small>°C</small></div>
      <div class='sub'><b>{f_temp(temp)}°F</b> · {esc(now_text)}</div>
      <div class='sub dim' style='font-size:18px'>{esc(' · '.join(details))}</div></div>"""

    if today:
        tc, tf = hilo(today)
        pp = today.get("pp")
        tday = f"""<div class='wtoday'><h2>Today{src}</h2>
          <div class='wword' style='font-size:{40 if len(today["text"] or "") <= 16 else 28}px'>{esc(today['text'])}</div>
          <div class='whl'>{tc} <span style='font-size:20px;font-weight:400'>{tf}</span></div>
          <div class='sub' style='font-size:18px'>{'' if pp is None else f'{pp:.0f}% chance of precip'}</div>
          <div class='sub' style='font-size:18px'>{'' if today.get('wind') is None else f"Max wind {today['wind']:.0f} · gust {today['gust']:.0f} km/h"}</div></div>"""
    else:
        tday = "<div class='wtoday'><h2>Today</h2><div class='sub dim'>no forecast</div></div>"

    cols = ""
    for f in rest:
        fc_c, fc_f = hilo(f)
        pp = f.get("pp")
        wt = "" if f.get("wind") is None else f"wind {f['wind']:.0f}<br>gust {f['gust']:.0f} km/h"
        cols += f"""<div class='wday'><div class='wd'>{f['day'].strftime('%a')}</div>
          <div class='ww'>{esc(f['text'])}</div>
          <div class='wc'>{fc_c}</div><div class='wf'>{fc_f}</div>
          <div class='wp'>{'' if not pp else f'{pp:.0f}% precip'}</div>
          <div class='wp'>{wt}</div></div>"""
    body = f"<div class='wtop'>{cur}{tday}</div><div class='wdays'>{cols}</div>"
    return wrap("WEATHER", now.strftime("%a %b %-d  %-I:%M %p"), body)


# ---------- Terminus ----------
def tj(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(TERMINUS + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:300]}")


def push(pages):
    pw = open(CFG["terminus_password_file"]).read().strip()
    token = tj("POST", "/login", {"login": CFG["terminus_login"], "password": pw})["access_token"]
    state = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}
    uris = json.load(open(URIS_FILE)) if os.path.exists(URIS_FILE) else {}
    for name, label, content in pages:
        screen = {"model_id": str(CFG["model_id"]), "label": label, "name": name,
                  "content": content, "file_name": f"{name}.png"}
        if name in state:
            res = tj("PATCH", f"/api/screens/{state[name]}", {"screen": screen}, token)
        else:
            screen["playlist_id"] = CFG["playlist_id"]
            res = tj("POST", "/api/screens", {"screen": screen}, token)
            state[name] = res["data"]["id"]
            json.dump(state, open(STATE_FILE, "w"))
        uris[name] = res["data"]["uri"]
        print(f"pushed {name}")
    # Current image path per page, read by display_proxy.py to pick what the device shows.
    tmp = URIS_FILE + ".tmp"
    json.dump(uris, open(tmp, "w"))
    os.replace(tmp, URIS_FILE)


def main():
    now = dt.datetime.now(TZ)
    states = get_states()
    pages = []
    for name, label, fn in (("house", "House", page_house), ("solar", "Solar", page_solar), ("weather", "Weather", page_weather)):
        try:
            pages.append((name, label, fn(states, now)))
        except Exception as e:  # keep the other page alive
            print(f"render {name} failed: {e!r}", file=sys.stderr)
    if "--dump" in sys.argv:
        for name, _, content in pages:
            open(f"/tmp/{name}.html", "w").write(f"<!doctype html><meta charset='utf-8'>{content}")
        return
    push(pages)


if __name__ == "__main__":
    main()
