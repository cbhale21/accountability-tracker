#!/usr/bin/env python3
"""
Generate a self-contained, multi-section HTML site from goals.json + log.json + quote_of_day.json.
Sections: Today's Quote/Tip, Daily & Weekday Goals, Weekly Goals, Nutrition (7 days),
Habit Calendar (current month heatmap), Daily Log (full history table), Nutrition Log (full history).
Run from this directory: python3 generate_dashboard.py
Produces dashboard.html (no external dependencies, works fully offline).
"""
import json
import datetime
import os
import calendar as cal

HERE = os.path.dirname(os.path.abspath(__file__))
GOALS_PATH = os.path.join(HERE, "goals.json")
LOG_PATH = os.path.join(HERE, "log.json")
QUOTE_PATH = os.path.join(HERE, "quote_of_day.json")
CONFIG_PATH = os.path.join(HERE, "write_backend_config.json")
OUT_PATH = os.path.join(HERE, "dashboard.html")

DOW_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def load():
    with open(GOALS_PATH) as f:
        goals = json.load(f)["goals"]
    with open(LOG_PATH) as f:
        log = json.load(f)
    quote = None
    if os.path.exists(QUOTE_PATH):
        with open(QUOTE_PATH) as f:
            quote = json.load(f)
    apps_script_url = ""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            apps_script_url = json.load(f).get("apps_script_url", "")
    return goals, log, quote, apps_script_url


def parse_date(s):
    return datetime.datetime.strptime(s, "%Y-%m-%d").date()


def fmt_date(d):
    return d.strftime("%Y-%m-%d")


def applies_on(goal, d):
    cadence = goal["cadence"]
    dow = DOW_ABBR[d.weekday()]
    if cadence == "daily":
        return True
    if cadence in ("weekdays", "custom_nights"):
        return dow in goal.get("days", [])
    return False  # weekly_count goals aren't per-day


def goal_success(goal, entry):
    if entry is None:
        return False
    if goal["type"] == "boolean":
        return bool(entry.get("done"))
    if goal["type"] == "minimum":
        val = entry.get("value")
        return val is not None and val >= goal["target"]
    if goal["type"] == "cap":
        val = entry.get("value")
        return val is not None and val <= goal["target"]
    return False


def compute_streak(goal, log, today):
    start_date = parse_date(log.get("start_date", fmt_date(today)))
    streak = 0
    d = today - datetime.timedelta(days=1)
    while d >= start_date:
        if applies_on(goal, d):
            day_entry = log["daily"].get(fmt_date(d), {})
            g_entry = day_entry.get("goals", {}).get(goal["id"])
            if goal_success(goal, g_entry):
                streak += 1
            else:
                break
        d -= datetime.timedelta(days=1)
    return streak


def today_status(goal, log, today):
    day_entry = log["daily"].get(fmt_date(today), {})
    g_entry = day_entry.get("goals", {}).get(goal["id"])
    if g_entry is None:
        return "not yet logged"
    return "done" if goal_success(goal, g_entry) else "missed"


def week_bounds(d):
    monday = d - datetime.timedelta(days=d.weekday())
    sunday = monday + datetime.timedelta(days=6)
    return monday, sunday


def weekly_count(goal, log, today):
    monday, _ = week_bounds(today)
    count = 0
    d = monday
    while d <= today:
        day_entry = log["daily"].get(fmt_date(d), {})
        g_entry = day_entry.get("goals", {}).get(goal["id"])
        if g_entry and g_entry.get("done"):
            count += 1
        d += datetime.timedelta(days=1)
    return count


def nutrition_last_days(log, today, n=7):
    out = []
    d = today
    for _ in range(n):
        day_entry = log["daily"].get(fmt_date(d), {})
        nut = day_entry.get("nutrition")
        if nut:
            out.append((fmt_date(d), nut))
        d -= datetime.timedelta(days=1)
    return out


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def badge(text, cls):
    return f'<span class="badge {cls}">{esc(text)}</span>'


def interactive_cell(goal, g_entry):
    """Render today's cell as tappable (boolean) or an inline-editable number
    (minimum/cap), so Chris can log today's result directly on the live site.
    Only ever used for TODAY -- history stays read-only static HTML."""
    gid = goal["id"]
    if goal["type"] == "boolean":
        if g_entry is None:
            state, cls, text = "none", "pending", "not yet logged"
        elif g_entry.get("done"):
            state, cls, text = "done", "ok", "done"
        else:
            state, cls, text = "missed", "bad", "missed"
        return (
            f'<button type="button" class="cell-toggle {cls}" '
            f'data-goal-id="{esc(gid)}" data-state="{state}" '
            f'onclick="cycleGoal(this)">{esc(text)}</button>'
        )
    else:
        value = g_entry.get("value") if g_entry else None
        target = goal.get("target", "")
        unit = goal.get("unit", "")
        if value is None:
            cls = "pending"
        elif goal["type"] == "minimum":
            cls = "ok" if value >= target else "bad"
        else:  # cap
            cls = "ok" if value <= target else "bad"
        val_attr = "" if value is None else esc(value)
        return (
            f'<span class="cell-num-wrap">'
            f'<input type="number" inputmode="numeric" class="cell-input {cls}" '
            f'data-goal-id="{esc(gid)}" data-goal-type="{esc(goal["type"])}" '
            f'data-target="{esc(target)}" value="{val_attr}" placeholder="--" '
            f'onchange="updateNumeric(this)">'
            f'<span class="cell-unit">/{esc(target)} {esc(unit)}</span>'
            f'</span>'
        )


# ---------------------------------------------------------------- Dashboard section (split into independently placeable cards)

def build_quote_section(quote):
    if not quote:
        return ""
    label = "Today's Health Tip" if quote.get("type") == "tip" else "Today's Quote"
    return f'''
  <div class="card quote-card">
    <h2>{esc(label)}</h2>
    <p class="quote-text">{esc(quote.get("text", ""))}</p>
  </div>'''


def build_daily_weekday_goals_section(goals, log, today):
    daily_goals = [g for g in goals if g["cadence"] in ("daily", "weekdays", "custom_nights")]
    today_str = fmt_date(today)
    rows = []
    for g in daily_goals:
        streak = compute_streak(g, log, today)
        applies_today = applies_on(g, today)
        if not applies_today:
            cell_html = badge("n/a today", "muted")
        else:
            day_entry = log["daily"].get(today_str, {})
            g_entry = day_entry.get("goals", {}).get(g["id"])
            cell_html = interactive_cell(g, g_entry)
        rows.append((g["label"], f"{streak}-day streak", cell_html))

    daily_rows_html = "".join(
        f'<tr><td>{esc(l)}</td><td>{esc(s)}</td><td>{c}</td></tr>'
        for l, s, c in rows
    )

    return f'''
  <div class="card">
    <h2>Daily &amp; Weekday Goals</h2>
    <table><tr><th>Goal</th><th>Streak</th><th>Today</th></tr>{daily_rows_html}</table>
  </div>'''


def build_weekly_goals_section(goals, log, today):
    weekly_goals = [g for g in goals if g["cadence"] == "weekly_count"]
    weekly_rows = []
    for g in weekly_goals:
        count = weekly_count(g, log, today)
        target = g["target"]
        cls = "ok" if count >= target else ("pending" if count > 0 else "bad")
        weekly_rows.append((g["label"], f"{count}/{target} this week", cls))

    weekly_rows_html = "".join(
        f'<tr><td>{esc(l)}</td><td>{badge(t, c)}</td></tr>' for l, t, c in weekly_rows
    )

    return f'''
  <div class="card">
    <h2>Weekly Goals</h2>
    <table><tr><th>Goal</th><th>This Week</th></tr>{weekly_rows_html}</table>
  </div>'''


def build_nutrition_water_section(log, today):
    nutrition_days = nutrition_last_days(log, today, 7)
    water_values = [n.get("water_oz") for _, n in nutrition_days if n.get("water_oz") is not None]
    avg_water = round(sum(water_values) / len(water_values), 1) if water_values else None

    nutrition_html = ""
    if nutrition_days:
        for date_str, nut in nutrition_days:
            meals = nut.get("meals", [])
            water = nut.get("water_oz")
            meal_lines = "".join(
                f"<li><strong>{esc(m.get('time',''))}</strong> - {esc(m.get('description',''))}"
                f"<div class='assessment'>{esc(m.get('assessment',''))}</div></li>"
                for m in meals
            )
            nutrition_html += f'''
            <div class="nut-day">
              <div class="nut-date">{esc(date_str)}{' (today)' if date_str == fmt_date(today) else ''}</div>
              <ul>{meal_lines or '<li class="muted">No meals logged</li>'}</ul>
              <div class="water">Water: {esc(water) if water is not None else '-'} oz</div>
            </div>'''
    else:
        nutrition_html = "<p class='muted'>No nutrition entries yet.</p>"

    avg_html = f'<div class="avg-water">7-day avg water: {avg_water} oz</div>' if avg_water is not None else ""

    return f'''
  <div class="card">
    <h2>Nutrition &amp; Water (last 7 days)</h2>
    {nutrition_html}
    {avg_html}
  </div>'''


# ---------------------------------------------------------------- Calendar section

def build_calendar_section(goals, log, today):
    daily_goals = [g for g in goals if g["cadence"] in ("daily", "weekdays", "custom_nights")]
    year, month = today.year, today.month
    days_in_month = cal.monthrange(year, month)[1]
    start_date = parse_date(log.get("start_date", fmt_date(today)))

    header_cells = "".join(
        f'<th>{d}<div class="dow">{DOW_ABBR[datetime.date(year, month, d).weekday()]}</div></th>'
        for d in range(1, days_in_month + 1)
    )

    body_rows = ""
    for g in daily_goals:
        cells = ""
        for day in range(1, days_in_month + 1):
            d = datetime.date(year, month, day)
            if d > today or d < start_date:
                cells += '<td class="cal-blank"></td>'
                continue
            if not applies_on(g, d):
                cells += '<td class="cal-na">-</td>'
                continue
            day_entry = log["daily"].get(fmt_date(d), {})
            g_entry = day_entry.get("goals", {}).get(g["id"])
            if d == today and g_entry is None:
                cells += '<td class="cal-pending">?</td>'
            elif goal_success(g, g_entry):
                cells += '<td class="cal-ok">&#10003;</td>'
            else:
                cells += '<td class="cal-bad">&#10007;</td>'
        body_rows += f'<tr><td class="cal-label">{esc(g["label"])}</td>{cells}</tr>'

    return f'''
  <div class="card cal-card">
    <h2>Habit Calendar &mdash; {esc(today.strftime("%B %Y"))}</h2>
    <div class="cal-legend">Green = hit &middot; Red = missed &middot; Gray = not applicable &middot; Yellow = today, pending</div>
    <div class="cal-scroll">
    <table class="cal-table"><tr><th>Goal</th>{header_cells}</tr>{body_rows}</table>
    </div>
  </div>'''


# ---------------------------------------------------------------- Daily Log section

# One compact glyph per goal so the Daily Log table can show every column without
# horizontal scrolling. Full name is still available on hover (<th title="...">) and
# in the legend printed above the table.
GOAL_ICONS = {
    "wake_6am": "⏰",           # alarm clock
    "morning_prayer": "\U0001F64F",  # praying hands
    "bom_reading": "\U0001F4D6",     # open book
    "pushups_30": "\U0001F4AA",      # flexed bicep
    "squats_30": "\U0001F9B5",       # leg
    "steps_5000": "\U0001F45F",      # running shoe
    "read_20min": "\U0001F4DA",      # books
    "phone_games_cap": "\U0001F3AE", # game controller
    "social_media_cap": "\U0001F4F1",# mobile phone
    "couple_prayer": "\U0001F49E",   # revolving hearts
    "evening_prayer": "\U0001F319",  # crescent moon
    "sleep_11pm": "\U0001F634",      # sleeping face
    "gym_session": "\U0001F3CB️", # weight lifter
    "temple_attendance": "⛪",   # church
}


def goal_icon(goal):
    return GOAL_ICONS.get(goal["id"], goal["label"][:1].upper())


def build_daily_log_section(goals, log, today=None):
    all_goals = [g for g in goals if g["cadence"] != "weekly_count"] + \
                [g for g in goals if g["cadence"] == "weekly_count"]
    dates = sorted(log["daily"].keys(), reverse=True)

    today_str = fmt_date(today) if today else None
    if today_str and today_str not in dates:
        dates = [today_str] + dates
        log = {**log, "daily": {**log["daily"], today_str: {}}}

    header = "".join(
        f'<th title="{esc(g["label"])}">{goal_icon(g)}</th>' for g in all_goals
    )
    rows_html = ""
    for date_str in dates:
        day_entry = log["daily"][date_str]
        cells = ""
        for g in all_goals:
            g_entry = day_entry.get("goals", {}).get(g["id"])
            attrs = f'data-date="{esc(date_str)}" data-log-goal-id="{esc(g["id"])}"'
            if g_entry is None:
                cells += f'<td class="cal-blank" {attrs}></td>'
                continue
            success = goal_success(g, g_entry)
            cls = "cal-ok" if success else "cal-bad"
            if g["type"] == "boolean":
                val = "&#10003;" if g_entry.get("done") else "&#10007;"
            else:
                val = esc(g_entry.get("value", ""))
            cells += f'<td class="{cls}" {attrs}>{val}</td>'
        rows_html += f'<tr><td class="cal-label">{esc(date_str)}</td>{cells}</tr>'

    if not dates:
        rows_html = f'<tr><td colspan="{len(all_goals)+1}" class="muted">No entries yet.</td></tr>'

    return f'''
  <div class="card cal-card">
    <h2>Daily Log (full history)</h2>
    <div class="cal-scroll">
    <table class="cal-table log-table"><tr><th>Date</th>{header}</tr>{rows_html}</table>
    </div>
  </div>'''


# ---------------------------------------------------------------- Weight tracker section

def build_weight_chart_svg(entries, goal_weight):
    """entries: list of (date_str, weight) sorted ascending. Renders an inline SVG
    line chart -- no chart library, keeps the site fully self-contained/offline."""
    if len(entries) < 2:
        return '<p class="muted">Log a few weigh-ins to see your trend line here.</p>'

    W, H = 700, 220
    margin_l, margin_r, margin_t, margin_b = 8, 8, 20, 24
    plot_w = W - margin_l - margin_r
    plot_h = H - margin_t - margin_b

    values = [w for _, w in entries] + [goal_weight]
    lo = min(values) - 3
    hi = max(values) + 3
    if hi == lo:
        hi = lo + 1

    def x_for(i):
        if len(entries) == 1:
            return margin_l
        return margin_l + plot_w * i / (len(entries) - 1)

    def y_for(v):
        return margin_t + plot_h * (hi - v) / (hi - lo)

    points = " ".join(f"{x_for(i):.1f},{y_for(w):.1f}" for i, (d, w) in enumerate(entries))
    circles = "".join(
        f'<circle cx="{x_for(i):.1f}" cy="{y_for(w):.1f}" r="3.5" fill="var(--crimson)"></circle>'
        for i, (d, w) in enumerate(entries)
    )
    goal_y = y_for(goal_weight)
    first_date, last_date = entries[0][0], entries[-1][0]

    return f'''
    <div class="weight-chart-wrap">
    <svg viewBox="0 0 {W} {H}" class="weight-chart" preserveAspectRatio="none">
      <line x1="{margin_l}" y1="{goal_y:.1f}" x2="{W - margin_r}" y2="{goal_y:.1f}"
        stroke="var(--gold)" stroke-width="1.5" stroke-dasharray="5,4"></line>
      <text x="{W - margin_r}" y="{goal_y - 6:.1f}" text-anchor="end" class="weight-goal-label">Goal {esc(goal_weight)} lbs</text>
      <polyline points="{points}" fill="none" stroke="var(--crimson)" stroke-width="2.5"></polyline>
      {circles}
      <text x="{margin_l}" y="{H - 6}" class="weight-axis-label">{esc(first_date)}</text>
      <text x="{W - margin_r}" y="{H - 6}" text-anchor="end" class="weight-axis-label">{esc(last_date)}</text>
    </svg>
    </div>'''


def build_weight_section(log, today):
    entries = []
    for date_str, day in sorted(log.get("daily", {}).items()):
        w = day.get("weight_lbs")
        if w is not None:
            entries.append((date_str, w))

    goal_weight = log.get("goal_weight_lbs", 200)
    today_str = fmt_date(today)
    today_weight = log["daily"].get(today_str, {}).get("weight_lbs")
    latest_weight = entries[-1][1] if entries else None

    distance_text = ""
    if latest_weight is not None:
        diff = latest_weight - goal_weight
        if abs(diff) < 0.05:
            distance_text = f"You've reached your goal weight of {goal_weight} lbs!"
        elif diff > 0:
            distance_text = f"{round(diff, 1)} lbs to go to reach your goal of {goal_weight} lbs"
        else:
            distance_text = f"{round(-diff, 1)} lbs under your goal of {goal_weight} lbs"

    chart_html = build_weight_chart_svg(entries, goal_weight)
    weight_val = "" if today_weight is None else esc(today_weight)

    return f'''
  <div class="card weight-card">
    <h2>Weight Progress</h2>
    <div class="weight-controls">
      <div class="weight-field">
        <label>Today's weigh-in</label>
        <span class="weight-input-wrap">
          <input type="number" step="0.1" inputmode="decimal" class="weight-input"
            value="{weight_val}" placeholder="--" onchange="logWeight(this)">
          <span class="cell-unit">lbs</span>
        </span>
      </div>
      <div class="weight-field">
        <label>Goal weight</label>
        <span class="weight-input-wrap">
          <input type="number" step="0.1" inputmode="decimal" class="weight-input goal"
            value="{esc(goal_weight)}" onchange="updateGoalWeight(this)">
          <span class="cell-unit">lbs</span>
        </span>
      </div>
    </div>
    <div class="weight-distance" id="weightDistance">{esc(distance_text)}</div>
    {chart_html}
  </div>'''


# ---------------------------------------------------------------- Nutrition Log section

def build_nutrition_log_section(log):
    dates = sorted(log["daily"].keys(), reverse=True)
    rows_html = ""
    any_rows = False
    for date_str in dates:
        nut = log["daily"][date_str].get("nutrition")
        if not nut:
            continue
        any_rows = True
        meals = nut.get("meals", [])
        meal_txt = "<br>".join(
            f"<strong>{esc(m.get('time',''))}</strong>: {esc(m.get('description',''))} "
            f"<span class='assessment'>({esc(m.get('assessment',''))})</span>"
            for m in meals
        )
        water = nut.get("water_oz", "-")
        rows_html += f'<tr><td class="cal-label">{esc(date_str)}</td><td class="nut-cell">{meal_txt or "-"}</td><td>{esc(water)}</td></tr>'

    if not any_rows:
        rows_html = '<tr><td colspan="3" class="muted">No nutrition entries yet.</td></tr>'

    return f'''
  <div class="card">
    <h2>Nutrition Log (full history)</h2>
    <div class="cal-scroll">
    <table class="cal-table"><tr><th>Date</th><th>Meals</th><th>Water (oz)</th></tr>{rows_html}</table>
    </div>
  </div>'''


# ---------------------------------------------------------------- Vision board section

# Chris's chosen layout: each inner list is one row, in the order he wants them to appear.
# Row 1 (largest, top) = the core "why" -- family and faith. Rows below = identity/fitness/
# recreation, then material/lifestyle goals.
VISION_BOARD_ROWS = [
    [1, 6],
    [3, 4, 5, 10, 12],
    [8, 9, 11, 2, 13],
]


def build_vision_board_section():
    rows_html = ""
    for row_idx, row in enumerate(VISION_BOARD_ROWS):
        row_class = "vision-row vision-row-hero" if row_idx == 0 else "vision-row"
        imgs = "".join(
            f'<img src="visionboard/vb{i:02d}.jpg" alt="Vision board image" loading="lazy">'
            for i in row
        )
        rows_html += f'<div class="{row_class}">{imgs}</div>'

    return f'''
  <div class="card vision-card">
    <h2>My Why &mdash; Vision Board</h2>
    <p class="vision-intro">True, Faithful, and Valiant in every responsibility and stewardship &mdash; this is the life these daily habits are building toward.</p>
    <div class="vision-rows">{rows_html}</div>
  </div>'''


# ---------------------------------------------------------------- Page assembly

CSS = '''
  :root {
    --bg-start: #f8ecd9;
    --bg-end: #f1e0bf;
    --card: #fffdf8;
    --ink: #2b2014;
    --muted: #8a7a63;
    --ok: #2f7d4f;
    --ok-bg: #e5f4ea;
    --bad: #b3432c;
    --bad-bg: #fbe8e3;
    --pending: #a5761f;
    --pending-bg: #fbf1de;
    --border: #e8d9b8;
    --crimson: #8a1207;
    --gold: #a9720f;
    --gold-bg: #fbeed2;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: linear-gradient(160deg, var(--bg-start) 0%, var(--bg-end) 100%);
    background-attachment: fixed;
    color: var(--ink);
    margin: 0;
    padding: 32px 16px 64px;
  }
  .wrap { max-width: 900px; margin: 0 auto; }
  h1 { font-size: 24px; margin-bottom: 4px; display: flex; align-items: center; gap: 16px; color: var(--crimson); }
  h1 img.header-logo {
    height: 72px; width: 72px; object-fit: contain; flex-shrink: 0; border-radius: 14px;
    background: var(--gold-bg);
    box-shadow: 0 0 0 3px var(--gold-bg), 0 0 0 4px var(--gold), 0 3px 8px rgba(43,32,20,0.25);
    padding: 4px;
  }
  .subtitle { color: var(--muted); font-size: 13px; margin-bottom: 20px; margin-left: 88px; }
  nav.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 24px; position: sticky; top: 0; background: #f4e3c6; padding: 8px 0; z-index: 10; border-bottom: 1px solid var(--border); }
  nav.tabs a {
    text-decoration: none; color: var(--ink); background: var(--card); border: 1px solid var(--border);
    padding: 6px 14px; border-radius: 999px; font-size: 13px; font-weight: 600;
  }
  nav.tabs a:hover { background: var(--gold-bg); border-color: var(--gold); }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px 22px;
    margin-bottom: 20px;
    scroll-margin-top: 60px;
    box-shadow: 0 2px 10px rgba(138,18,7,0.06);
  }
  .card h2 { font-size: 15px; margin: 0 0 14px 0; text-transform: uppercase; letter-spacing: 0.04em; color: var(--crimson); }
  .quote-card { background: linear-gradient(135deg, var(--gold-bg), var(--card)); }
  .quote-text { font-style: italic; font-size: 15px; margin: 0; line-height: 1.5; }
  .vision-card { background: linear-gradient(160deg, var(--card), var(--gold-bg)); }
  .vision-intro { font-size: 13px; color: var(--muted); margin: 0 0 16px 0; line-height: 1.5; }
  .vision-rows { display: flex; flex-direction: column; gap: 10px; }
  .vision-row { display: flex; gap: 10px; }
  .vision-row img {
    flex: 1 1 0; width: 0; min-width: 0; height: 120px; object-fit: cover; border-radius: 10px;
    border: 1px solid var(--border); box-shadow: 0 2px 6px rgba(43,32,20,0.12);
  }
  .vision-row-hero img { height: 190px; }
  @media (max-width: 640px) {
    .vision-row { flex-wrap: wrap; }
    .vision-row img { flex: 1 1 calc(33% - 8px); height: 90px; }
    .vision-row-hero img { flex: 1 1 calc(50% - 6px); height: 130px; }
  }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: 11px; text-transform: uppercase; color: var(--muted); padding: 6px 4px; border-bottom: 2px solid var(--border); }
  td { padding: 8px 4px; font-size: 14px; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: none; }
  .badge {
    display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
  }
  .badge.ok { background: var(--ok-bg); color: var(--ok); }
  .badge.bad { background: var(--bad-bg); color: var(--bad); }
  .badge.pending { background: var(--pending-bg); color: var(--pending); }
  .badge.muted { background: #f1ede6; color: var(--muted); }
  .cell-toggle {
    display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
    border: none; cursor: pointer; font-family: inherit; -webkit-tap-highlight-color: transparent;
    transition: transform 0.1s ease;
  }
  .cell-toggle:active { transform: scale(0.94); }
  .cell-toggle.ok { background: var(--ok-bg); color: var(--ok); }
  .cell-toggle.bad { background: var(--bad-bg); color: var(--bad); }
  .cell-toggle.pending { background: var(--pending-bg); color: var(--pending); }
  .cell-num-wrap { display: inline-flex; align-items: center; gap: 5px; }
  .cell-input {
    width: 56px; padding: 3px 6px; border-radius: 8px; font-size: 13px; font-weight: 600;
    font-family: inherit; text-align: center; border: 1px solid var(--border);
  }
  .cell-input.ok { background: var(--ok-bg); color: var(--ok); border-color: var(--ok); }
  .cell-input.bad { background: var(--bad-bg); color: var(--bad); border-color: var(--bad); }
  .cell-input.pending { background: var(--pending-bg); color: var(--pending); border-color: var(--pending); }
  .cell-unit { font-size: 11px; color: var(--muted); }
  .save-toast {
    position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%) translateY(20px);
    background: var(--crimson); color: #fff; padding: 8px 18px; border-radius: 999px;
    font-size: 13px; font-weight: 600; opacity: 0; pointer-events: none; transition: all 0.25s ease;
    box-shadow: 0 4px 14px rgba(0,0,0,0.2); z-index: 100;
  }
  .weight-controls { display: flex; gap: 28px; flex-wrap: wrap; margin-bottom: 10px; }
  .weight-field label { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); margin-bottom: 4px; }
  .weight-input-wrap { display: inline-flex; align-items: center; gap: 6px; }
  .weight-input {
    width: 72px; padding: 5px 8px; border-radius: 8px; font-size: 15px; font-weight: 700;
    font-family: inherit; text-align: center; border: 1px solid var(--border); background: var(--gold-bg); color: var(--ink);
  }
  .weight-input.goal { background: var(--card); }
  .weight-distance { font-size: 14px; font-weight: 600; color: var(--crimson); margin-bottom: 12px; }
  .weight-chart-wrap { width: 100%; }
  .weight-chart { width: 100%; height: auto; display: block; }
  .weight-axis-label { font-size: 10px; fill: var(--muted); }
  .weight-goal-label { font-size: 11px; fill: var(--gold); font-weight: 700; }
  .save-toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
  .nut-day { margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
  .nut-day:last-child { border-bottom: none; margin-bottom: 0; }
  .nut-date { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
  .nut-day ul { margin: 0 0 6px 0; padding-left: 18px; }
  .nut-day li { font-size: 13px; margin-bottom: 4px; }
  .assessment { color: var(--muted); font-size: 12px; }
  .water { font-size: 12px; color: var(--muted); }
  .muted { color: var(--muted); }
  .avg-water { font-size: 13px; color: var(--muted); margin-top: 4px; }
  .cal-card { overflow: hidden; }
  .cal-legend { font-size: 12px; color: var(--muted); margin-bottom: 12px; }
  .cal-scroll { overflow-x: auto; }
  table.cal-table { border-collapse: collapse; white-space: nowrap; }
  table.cal-table th, table.cal-table td { text-align: center; padding: 4px 6px; font-size: 12px; border: 1px solid var(--border); }
  table.cal-table th .dow { font-weight: 400; font-size: 9px; color: var(--muted); }
  td.cal-label { text-align: left; font-size: 12px; white-space: normal; min-width: 140px; }
  td.cal-ok { background: var(--ok-bg); color: var(--ok); font-weight: 700; }
  td.cal-bad { background: var(--bad-bg); color: var(--bad); font-weight: 700; }
  td.cal-na { background: #f1ede6; color: var(--muted); }
  td.cal-pending { background: var(--pending-bg); color: var(--pending); font-weight: 700; }
  td.cal-blank { background: transparent; }
  td.nut-cell { text-align: left; font-size: 12px; white-space: normal; min-width: 260px; }
  table.log-table { table-layout: fixed; }
  table.log-table th, table.log-table td { width: 30px; padding: 4px 2px; font-size: 15px; }
  table.log-table th { font-size: 15px; cursor: help; }
  table.log-table td.cal-label, table.log-table th:first-child { width: 84px; font-size: 12px; min-width: 0; }
  .footer { text-align: center; color: var(--muted); font-size: 12px; margin-top: 24px; }
'''


def main():
    goals, log, quote, apps_script_url = load()
    today = datetime.date.today()

    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    vision_board_section = build_vision_board_section()
    quote_section = build_quote_section(quote)
    daily_weekday_goals_section = build_daily_weekday_goals_section(goals, log, today)
    weekly_goals_section = build_weekly_goals_section(goals, log, today)
    nutrition_water_section = build_nutrition_water_section(log, today)
    weight_section = build_weight_section(log, today)
    calendar_section = build_calendar_section(goals, log, today)
    daily_log_section = build_daily_log_section(goals, log, today)
    nutrition_log_section = build_nutrition_log_section(log)

    goal_weight_for_js = log.get("goal_weight_lbs", 200)
    weight_entries_for_js = sorted(
        (d, day.get("weight_lbs")) for d, day in log.get("daily", {}).items() if day.get("weight_lbs") is not None
    )
    latest_weight_for_js = weight_entries_for_js[-1][1] if weight_entries_for_js else None

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chris's Accountability Dashboard</title>
<link rel="icon" type="image/x-icon" href="favicon.ico">
<link rel="icon" type="image/png" sizes="16x16" href="favicon-16x16.png">
<link rel="icon" type="image/png" sizes="32x32" href="favicon-32x32.png">
<link rel="icon" type="image/png" sizes="48x48" href="favicon-48x48.png">
<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="192x192" href="android-chrome-192x192.png">
<link rel="icon" type="image/png" sizes="512x512" href="android-chrome-512x512.png">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <h1><img class="header-logo" src="header-logo.png" alt="Crest logo">Chris's Accountability Dashboard</h1>
  <div class="subtitle">Generated {esc(generated_at)} &middot; Today is {esc(today.strftime('%A, %B %d, %Y'))}</div>

  <nav class="tabs">
    <a href="#vision">Vision Board</a>
    <a href="#weight">Weight</a>
    <a href="#today">Today</a>
    <a href="#daily-log">Daily Log</a>
    <a href="#calendar">Calendar</a>
    <a href="#nutrition-log">Nutrition Log</a>
  </nav>

  <div id="vision"></div>
  {vision_board_section}

  <div id="weight"></div>
  {weight_section}

  <div id="today"></div>
  {quote_section}
  {daily_weekday_goals_section}
  {weekly_goals_section}

  <div id="daily-log"></div>
  {daily_log_section}

  <div id="calendar"></div>
  {calendar_section}

  <div id="nutrition-log"></div>
  {nutrition_log_section}
  {nutrition_water_section}

  <div class="footer">This page regenerates each time you log something new and get a check-in. Reopen it any time to see your latest progress.</div>
</div>
<div class="save-toast" id="saveToast">Saved</div>
<script>
  var TODAY_DATE = {json.dumps(fmt_date(today))};
  var WRITE_URL = {json.dumps(apps_script_url)};
  var GOAL_WEIGHT = {json.dumps(goal_weight_for_js)};
  var LATEST_WEIGHT = {json.dumps(latest_weight_for_js)};

  // The page is a static snapshot rebuilt once a day (or on-demand), so TODAY_DATE
  // above can go stale if you open/tap the page before the next rebuild (e.g. early
  // morning before the 7am check-in has run). Any WRITE to the backend or to the
  // local cache must use the device's real live date instead, so entries always
  // land on the actual day they were made, and naturally "reset" at midnight since
  // a new day means a new date string with no cached entries.
  function realTodayStr() {{
    var d = new Date();
    var pad = function(n) {{ return n < 10 ? '0' + n : '' + n; }};
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }}

  function showToast(msg) {{
    var t = document.getElementById('saveToast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._hideTimer);
    t._hideTimer = setTimeout(function() {{ t.classList.remove('show'); }}, 1600);
  }}

  function saveGoal(goalId, payload) {{
    if (!WRITE_URL) {{ showToast('Not connected'); return; }}
    payload.goalId = goalId;
    payload.date = realTodayStr();
    fetch(WRITE_URL, {{
      method: 'POST',
      mode: 'no-cors',
      headers: {{'Content-Type': 'text/plain;charset=utf-8'}},
      body: JSON.stringify(payload)
    }}).catch(function() {{ /* fire-and-forget */ }});
    showToast('Saved');
  }}

  // ---- local cache: remembers today's taps on this device so a refresh
  // before the next scheduled site rebuild still shows what you just did ----
  var CACHE_KEY = 'accountability_cache_v1';

  function loadCache() {{
    var rt = realTodayStr();
    try {{
      var raw = localStorage.getItem(CACHE_KEY);
      if (!raw) return {{date: rt, entries: {{}}}};
      var parsed = JSON.parse(raw);
      if (parsed.date !== rt) return {{date: rt, entries: {{}}}};
      return parsed;
    }} catch (e) {{
      return {{date: rt, entries: {{}}}};
    }}
  }}

  function cacheSet(key, value) {{
    try {{
      var cache = loadCache();
      cache.date = realTodayStr();
      cache.entries[key] = value;
      localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
    }} catch (e) {{ /* ignore, e.g. private browsing */ }}
  }}

  // ---- shared cell-update helpers (used by real taps AND cache restore) ----

  function syncDailyLogCell(goalId, cls, text) {{
    var td = document.querySelector('td[data-date="' + TODAY_DATE + '"][data-log-goal-id="' + goalId + '"]');
    if (!td) return;
    td.classList.remove('cal-ok', 'cal-bad', 'cal-blank');
    td.classList.add(cls);
    td.innerHTML = text;
  }}

  function setBooleanCell(btn, state, save) {{
    var goalId = btn.getAttribute('data-goal-id');
    var cls, text, logCls, logText, payload;
    if (state === 'done') {{
      cls = 'ok'; text = 'done'; logCls = 'cal-ok'; logText = '&#10003;';
      payload = {{kind: 'boolean', boolValue: true}};
    }} else if (state === 'missed') {{
      cls = 'bad'; text = 'missed'; logCls = 'cal-bad'; logText = '&#10007;';
      payload = {{kind: 'boolean', boolValue: false}};
    }} else {{
      cls = 'pending'; text = 'not yet logged'; logCls = 'cal-blank'; logText = '';
      payload = {{kind: 'boolean', clear: true}};
    }}
    btn.setAttribute('data-state', state);
    btn.className = 'cell-toggle ' + cls;
    btn.textContent = text;
    syncDailyLogCell(goalId, logCls, logText);
    if (save) {{
      saveGoal(goalId, payload);
      cacheSet('goal_' + goalId, {{type: 'boolean', state: state}});
    }}
  }}

  function cycleGoal(btn) {{
    var state = btn.getAttribute('data-state');
    var next = state === 'none' ? 'done' : (state === 'done' ? 'missed' : 'none');
    setBooleanCell(btn, next, true);
  }}

  function setNumericCell(input, rawVal, save) {{
    var goalId = input.getAttribute('data-goal-id');
    var goalType = input.getAttribute('data-goal-type');
    var target = parseFloat(input.getAttribute('data-target'));
    input.classList.remove('ok', 'bad', 'pending');
    var logCls, logText, payload, cacheEntry;
    if (rawVal === '' || rawVal === null || rawVal === undefined) {{
      input.value = '';
      input.classList.add('pending');
      logCls = 'cal-blank'; logText = '';
      payload = {{kind: 'value', clear: true}};
      cacheEntry = {{type: 'value', cleared: true}};
    }} else {{
      var val = parseFloat(rawVal);
      var success = goalType === 'minimum' ? (val >= target) : (val <= target);
      input.value = val;
      input.classList.add(success ? 'ok' : 'bad');
      logCls = success ? 'cal-ok' : 'cal-bad';
      logText = String(val);
      payload = {{kind: 'value', numValue: val}};
      cacheEntry = {{type: 'value', value: val}};
    }}
    syncDailyLogCell(goalId, logCls, logText);
    if (save) {{
      saveGoal(goalId, payload);
      cacheSet('goal_' + goalId, cacheEntry);
    }}
  }}

  function updateNumeric(input) {{
    setNumericCell(input, input.value, true);
  }}

  function updateDistanceText(latest) {{
    var el = document.getElementById('weightDistance');
    if (!el) return;
    if (latest === null || latest === undefined || isNaN(latest)) {{ el.textContent = ''; return; }}
    var diff = Math.round((latest - GOAL_WEIGHT) * 10) / 10;
    if (Math.abs(diff) < 0.05) {{
      el.textContent = "You've reached your goal weight of " + GOAL_WEIGHT + " lbs!";
    }} else if (diff > 0) {{
      el.textContent = diff + " lbs to go to reach your goal of " + GOAL_WEIGHT + " lbs";
    }} else {{
      el.textContent = (-diff) + " lbs under your goal of " + GOAL_WEIGHT + " lbs";
    }}
  }}

  function logWeight(input) {{
    var raw = input.value;
    LATEST_WEIGHT = raw === '' ? null : parseFloat(raw);
    saveGoal(null, raw === '' ? {{kind: 'weight', clear: true}} : {{kind: 'weight', numValue: LATEST_WEIGHT}});
    updateDistanceText(LATEST_WEIGHT);
    cacheSet('weight', raw === '' ? {{cleared: true}} : {{value: LATEST_WEIGHT}});
  }}

  function updateGoalWeight(input) {{
    var val = parseFloat(input.value);
    if (isNaN(val)) return;
    GOAL_WEIGHT = val;
    saveGoal(null, {{kind: 'goal_weight', numValue: val}});
    updateDistanceText(LATEST_WEIGHT);
    cacheSet('goalWeight', {{value: val}});
  }}

  function restoreFromCache() {{
    var cache = loadCache();
    var entries = cache.entries || {{}};
    Object.keys(entries).forEach(function(key) {{
      var entry = entries[key];
      if (key === 'weight') {{
        var wInput = document.querySelector('.weight-input:not(.goal)');
        if (wInput) wInput.value = entry.cleared ? '' : entry.value;
        LATEST_WEIGHT = entry.cleared ? null : entry.value;
        updateDistanceText(LATEST_WEIGHT);
      }} else if (key === 'goalWeight') {{
        var gInput = document.querySelector('.weight-input.goal');
        if (gInput) gInput.value = entry.value;
        GOAL_WEIGHT = entry.value;
        updateDistanceText(LATEST_WEIGHT);
      }} else if (key.indexOf('goal_') === 0) {{
        var goalId = key.slice(5);
        if (entry.type === 'boolean') {{
          var btn = document.querySelector('.cell-toggle[data-goal-id="' + goalId + '"]');
          if (btn) setBooleanCell(btn, entry.state, false);
        }} else if (entry.type === 'value') {{
          var inp = document.querySelector('.cell-input[data-goal-id="' + goalId + '"]');
          if (inp) setNumericCell(inp, entry.cleared ? '' : entry.value, false);
        }}
      }}
    }});
  }}

  restoreFromCache();
</script>
</body>
</html>
'''
    with open(OUT_PATH, "w") as f:
        f.write(html)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
