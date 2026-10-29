#!/usr/bin/env python3
"""Build iOS-style (dark mode, Liquid Glass) KWGT presets.

Each widget is described once with the small helpers below and exported as
`dist/<name>.kwgt` (a zip holding `preset.json` + thumbnails). The same tree
also renders to `previews/<name>.svg` using sample values, so layouts can be
checked without a phone.

    python3 kwgt/build.py            # writes dist/*.kwgt and previews/*.svg
    node kwgt/render_previews.mjs    # optional: svg -> jpg thumbnails + gallery

Units are KWGT editor units at 2x iOS points (small widget 170pt -> 340).
The root layer rescales itself to whatever cell size the widget is given.
"""

import json
import math
import pathlib
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
DIST = HERE / "dist"
PREVIEWS = HERE / "previews"

S, M, L = (340, 340), (728, 340), (728, 764)
PAD = 32
RADIUS = 46

# iOS dark-mode system colors.
WHITE = "#FFFFFFFF"
LABEL2 = "#99EBEBF5"  # secondaryLabel
LABEL3 = "#4DEBEBF5"  # tertiaryLabel
FILL = "#33787880"  # quaternary fill, used for ring/bar tracks
RED = "#FFFF453A"
ORANGE = "#FFFF9F0A"
YELLOW = "#FFFFD60A"
GREEN = "#FF30D158"
BLUE = "#FF0A84FF"
CLEAR = "#00000000"
MOVE, EXERCISE, STAND = "#FFFA114F", "#FFA6FF00", "#FF00F0FF"

GOOGLE_CLOCK = ("intent:#Intent;action=android.intent.action.MAIN;"
                "category=android.intent.category.LAUNCHER;"
                "component=com.google.android.deskclock/"
                "com.android.deskclock.DeskClock;end")
GOOGLE_CALENDAR = ("intent:#Intent;action=android.intent.action.MAIN;"
                   "category=android.intent.category.LAUNCHER;"
                   "component=com.google.android.calendar/"
                   "com.android.calendar.AllInOneActivity;end")


# --------------------------------------------------------------------------
# Module helpers. Every child is placed TOPLEFT + offset inside its parent
# layer; "_s" carries preview-only sample values and is stripped on export.

def _base(kind, x, y, title=None):
    m = {"internal_type": kind, "position_anchor": "TOPLEFT",
         "position_offset_x": float(x), "position_offset_y": float(y)}
    if title:
        m["internal_title"] = title
    return m


def formula(m, key, expr, sample=None):
    """Drive property `key` by a KWGT formula (toggle 10 = formula)."""
    m.setdefault("internal_formulas", {})[key] = expr
    m.setdefault("internal_toggles", {})[key] = 10
    if sample is not None:
        m.setdefault("_s", {})[key] = sample
    return m


def rect(x, y, w, h, color, r=0, title=None, stroke=None, grad=None,
         shadow=None, shape="RECT"):
    m = _base("ShapeModule", x, y, title)
    m.update(shape_type=shape, shape_width=float(w), shape_height=float(h),
             paint_color=color)
    if r:
        m["shape_corners"] = float(r)
    if stroke:
        m.update(paint_style="STROKE", paint_stroke=float(stroke))
    if grad:  # (end color, VERTICAL|HORIZONTAL|RADIAL)
        m.update(fx_gradient=grad[1], fx_gradient_color=grad[0])
    if shadow:  # (color, blur, distance)
        m.update(fx_shadow="OUTER", fx_shadow_color=shadow[0],
                 fx_shadow_blur=shadow[1], fx_shadow_distance=float(shadow[2]),
                 fx_shadow_direction=90)
    return m


def circle(cx, cy, d, color, title=None, stroke=None):
    m = rect(cx - d / 2, cy - d / 2, d, d, color, title=title, stroke=stroke,
             shape="CIRCLE")
    return m


def text(x, y, expr, size, color=WHITE, bold=False, align="LEFT", width=None,
         lines=1, sample=None, title=None):
    """Text whose box starts at (x, y). Centered/right text needs `width`:
    the box is fixed-width and aligned inside it, so every module can stay
    TOPLEFT-anchored (no sign conventions of right/center anchors)."""
    m = _base("TextModule", x, y, title)
    m.update(text_expression=f"[b]{expr}[/b]" if bold else expr,
             text_size=float(size), paint_color=color)
    if width:
        m.update(text_size_type="FIXED_WIDTH", text_width=float(width),
                 text_lines=float(lines))
    if align != "LEFT":
        m["text_align"] = align
    m["_s"] = {"text": sample if sample is not None else expr,
               "bold": bold, "align": align}
    return m


def icon(x, y, name, size, color=WHITE, title=None):
    m = _base("FontIconModule", x, y, title)
    m.update(icon_icon=name, icon_size=float(size), paint_color=color)
    return m


def ring(cx, cy, d, thick, level, fg, bg=FILL, sample=50, maximum=100,
         title=None):
    """Circular gauge: ProgressModule in CUSTOM mode fed by a formula."""
    m = _base("ProgressModule", cx - d / 2, cy - d / 2, title)
    m.update(progress_progress="CUSTOM", progress_max=float(maximum),
             progress_level=float(sample), style_style="CIRCLE",
             style_size=float(d), style_height=float(thick),
             color_fgcolor=fg, color_bgcolor=bg)
    formula(m, "progress_level", level, sample)
    return m


def layer(children, x=0, y=0, title=None, visible=None, tap=None,
          rotate=None, rotate_formula=None, sample_angle=0.0):
    m = _base("OverlapLayerModule", x, y, title)
    m["viewgroup_items"] = children
    if visible:  # formula returning ALWAYS / REMOVE
        formula(m, "config_visible", visible)
    if tap:
        m["internal_events"] = [dict(type="SINGLE_TAP", **tap)]
    if rotate:  # CLOCK_HOUR_SMOOTH / CLOCK_MINUTE / CLOCK_SECOND
        m["config_rotate_mode"] = rotate
    if rotate_formula:
        m["config_rotate_mode"] = "MANUAL"
        formula(m, "config_rotate_offset", rotate_formula)
    if rotate or rotate_formula:
        m["_s"] = {"angle": sample_angle}
    return m


def color_if(m, key, expr, sample):
    return formula(m, key, expr, sample)


def tap_app(intent):
    return {"action": "LAUNCH_APP", "intent": intent}


TAP_MUSIC_APP = {"action": "MUSIC", "music_action": "OPEN_APP"}


# --------------------------------------------------------------------------
# Liquid Glass panel (dark). Android widgets cannot blur what is behind
# them, so the glass is a translucent dark body + a light rim that fades
# downward + a soft top sheen, which is how the iOS 26 material reads.

def glass(w, h, tint=None):
    body = rect(0, 0, w, h, "#9E1C1C1E", RADIUS, "Glass body",
                grad=("#B80B0B0D", "VERTICAL"),
                shadow=("#66000000", 28, 10))
    items = [body]
    if tint:  # formula for an extra color wash (e.g. album art dominant)
        wash = rect(0, 0, w, h, CLEAR, RADIUS, "Glass tint")
        formula(wash, "paint_color", tint[0], tint[1])
        items.append(wash)
    items += [
        rect(0, 0, w, h * 0.55, "#1FFFFFFF", RADIUS, "Glass sheen",
             grad=("#00FFFFFF", "VERTICAL")),
        rect(1, 1, w - 2, h - 2, "#73FFFFFF", RADIUS - 1, "Glass rim",
             stroke=2, grad=("#14FFFFFF", "VERTICAL")),
    ]
    return items


# --------------------------------------------------------------------------
# Date helpers (KWGT date modifiers are strings like "a3d" / "r2h").

def shift(expr, unit):
    return (f'if(({expr})<0, "r"+(0-({expr}))+"{unit}", '
            f'"a"+({expr})+"{unit}")')


def month_grid(x0, y0, colw, rowh, size, head_size, head_gap):
    """Sunday-first month grid driven by globals cs/wt (see CAL_GLOBALS)."""
    items = []
    for c in range(7):
        t = text(x0 + c * colw, y0, f'$df(EEEEE, {shift(f"{c}-gv(wt)", "d")})$',
                 head_size, LABEL2, bold=True, align="CENTER", width=colw,
                 sample="일월화수목금토"[c])
        items.append(t)
    today_cell = 3 + 28 - 1  # sample month: starts Thursday, today 29th
    for i in range(42):
        r, c = divmod(i, 7)
        cx = x0 + c * colw + colw / 2
        ty = y0 + head_gap + r * rowh
        mod = shift(f"{i}-gv(cs)", "d")
        d = size * 1.7
        dot = circle(cx, ty + size * 0.62, d, CLEAR, f"Today {i}")
        color_if(dot, "paint_color", f"$if(gv(cs)={i}, {RED}, {CLEAR})$",
                 RED if i == today_cell else CLEAR)
        day = i - 3 + 1
        t = text(cx - colw / 2, ty, f"$df(d, {mod})$", size, WHITE, bold=True,
                 align="CENTER", width=colw,
                 sample=str(day) if 1 <= day <= 31 else "")
        color_if(t, "paint_color",
                 f"$if(df(M, {mod})=df(M), {WHITE}, {CLEAR})$", WHITE)
        items += [dot, t]
    return items


CAL_GLOBALS = {
    # days between the first grid cell (a Sunday) and today
    "cs": {"type": "NUMBER", "title": "cs", "value": 31.0, "min": 0, "max": 50,
           "global_formula": '$df(d)-1+if(df(f, "r"+(df(d)-1)+"d")=7, 0, '
                             'df(f, "r"+(df(d)-1)+"d"))$'},
    # today's column, Sunday = 0
    "wt": {"type": "NUMBER", "title": "wt", "value": 4.0, "min": 0, "max": 6,
           "global_formula": "$if(df(f)=7, 0, df(f))$"},
}


def event_rows(x, y, n, step, title_size, time_size, width, ell):
    rows = []
    samples = [("디자인 리뷰", "오후 2:00–3:00", BLUE),
               ("헬스장", "오후 6:30–7:30", GREEN),
               ("저녁 약속", "오후 8:00–10:00", ORANGE),
               ("주간 회의", "내일 오전 10:00", "#FFBF5AF2"),
               ("치과", "11/2 오전 9:30", RED)]
    for i in range(n):
        st, en = f"ci(start, {i})", f"ci(end, {i})"
        when = (f'$if(ci(allday, {i})=1, "하루 종일", '
                f'if(df(D, {st})=df(D), "", '
                f'if(df(D, {st})=df(D, a1d), "내일 ", df("M/d ", {st})))'
                f'+df("a h:mm", {st})+if(df(D, {st})=df(D), "–"+df("h:mm", {en}), ""))$')
        bar = rect(0, 0, 6, step - 22, BLUE, 3, "Calendar color")
        color_if(bar, "paint_color", f"$ci(color, {i})$", samples[i][2])
        rows.append(layer([
            bar,
            text(18, -2, f"$tc(ell, ci(title, {i}), {ell})$", title_size,
                 WHITE, bold=True, width=width - 18, sample=samples[i][0]),
            text(18, title_size * 1.25, when, time_size, LABEL2,
                 width=width - 18, sample=samples[i][1]),
        ], x, y + i * step, f"Event {i}",
            visible=f"$if(tc(len, ci(title, {i}))>0, ALWAYS, REMOVE)$"))
    rows.append(layer([
        text(0, 0, "예정된 이벤트 없음", time_size + 2, LABEL2, width=width,
             lines=2, sample=""),
    ], x, y, "No events",
        visible="$if(tc(len, ci(title, 0))>0, REMOVE, ALWAYS)$"))
    return rows


# --------------------------------------------------------------------------
# Weather helpers. wi(icon)/wf(icon) are mapped to emoji, which Android
# draws in color like the iOS weather glyphs.

def wx_emoji(icon_expr):
    return (f'if({icon_expr}~="STORM|TSH", "⛈️", '
            f'{icon_expr}~="SNOW|SLEET|HAIL|ICE", "❄️", '
            f'{icon_expr}~="RAIN|SHOWER|DRIZZLE", "🌧️", '
            f'{icon_expr}~="FOG|HAZE|MIST|SMOKE", "🌫️", '
            f'{icon_expr}~="WIND", "💨", '
            f'{icon_expr}~="PCLOUD|PARTLY", if(ai(isday)=1, "⛅", "☁️"), '
            f'{icon_expr}~="CLOUD", "☁️", '
            f'if(ai(isday)=1, "☀️", "🌙"))')


def weather_header(w, compact):
    items = [
        text(PAD, 28, "$li(loc)$", 26, WHITE, bold=True, width=w / 2,
             sample="서울"),
        text(PAD - 4, 58, "$wi(temp)$°", 84, WHITE, sample="18°"),
    ]
    if compact:
        items += [
            text(PAD, 196, f"${wx_emoji('wi(icon)')}$", 34, sample="⛅"),
            text(PAD, 240, "$wi(cond)$", 24, WHITE, bold=True, width=w - 2 * PAD,
                 sample="대체로 흐림"),
            text(PAD, 272, "최고:$wf(max, 0)$° 최저:$wf(min, 0)$°", 24, WHITE,
                 bold=True, width=w - 2 * PAD, sample="최고:21° 최저:12°"),
        ]
    else:
        rw = 320
        rx = w - PAD - rw
        items += [
            text(rx, 30, f"${wx_emoji('wi(icon)')}$", 32, align="RIGHT",
                 width=rw, sample="⛅"),
            text(rx, 76, "$wi(cond)$", 24, WHITE, bold=True, align="RIGHT",
                 width=rw, sample="대체로 흐림"),
            text(rx, 108, "최고:$wf(max, 0)$° 최저:$wf(min, 0)$°", 24, WHITE,
                 bold=True, align="RIGHT", width=rw, sample="최고:21° 최저:12°"),
        ]
    return items


def hourly_row(w, y):
    items = []
    n = 6
    colw = (w - 2 * PAD) / n
    temps = [18, 18, 17, 16, 15, 14]
    icons = ["⛅", "⛅", "☁️", "🌧️", "🌧️", "☁️"]
    for i in range(n):
        x = PAD + i * colw
        label = "지금" if i == 0 else f'$df("a h시", a{i}h)$'
        t = "$wi(temp)$°" if i == 0 else f"$wf(temp, {i}h)$°"
        em = (f"${wx_emoji('wi(icon)')}$" if i == 0
              else f"${wx_emoji(f'wf(icon, {i}h)')}$")
        items += [
            text(x, y, label, 20, LABEL2, bold=True, align="CENTER", width=colw,
                 sample="지금" if i == 0 else f"오후 {2 + i}시"),
            text(x, y + 32, em, 30, align="CENTER", width=colw, sample=icons[i]),
            text(x, y + 78, t, 24, WHITE, bold=True, align="CENTER", width=colw,
                 sample=f"{temps[i]}°"),
        ]
    return items


WX_GLOBALS = {
    "lo": {"type": "NUMBER", "title": "lo", "value": 8.0, "min": -60, "max": 60,
           "global_formula": "$mu(min, wf(min, 0), mu(min, wf(min, 1), mu(min, "
                             "wf(min, 2), mu(min, wf(min, 3), wf(min, 4)))))$"},
    "hi": {"type": "NUMBER", "title": "hi", "value": 23.0, "min": -60, "max": 60,
           "global_formula": "$mu(max, wf(max, 0), mu(max, wf(max, 1), mu(max, "
                             "wf(max, 2), mu(max, wf(max, 3), wf(max, 4)))))$"},
}


def daily_rows(w, y0, step):
    items = []
    bar_x, bar_w = 350, 210
    sample = [(12, 21, "⛅"), (10, 19, "☀️"), (11, 17, "🌧️"),
              (8, 15, "🌧️"), (9, 18, "☀️")]
    lo, hi = 8, 23
    for i in range(5):
        y = y0 + i * step
        mn, mx, em = sample[i]
        seg = rect(bar_x, y + 14, 40, 8, GREEN, 4, f"Range {i}",
                   grad=(YELLOW, "HORIZONTAL"))
        formula(seg, "position_offset_x",
                f"${bar_x}+{bar_w}*(wf(min, {i})-gv(lo))/mu(max, 1, gv(hi)-gv(lo))$",
                bar_x + bar_w * (mn - lo) / (hi - lo))
        formula(seg, "shape_width",
                f"$mu(max, 8, {bar_w}*(wf(max, {i})-wf(min, {i}))"
                f"/mu(max, 1, gv(hi)-gv(lo)))$",
                bar_w * (mx - mn) / (hi - lo))
        items += [
            text(PAD, y, "오늘" if i == 0 else f"$df(EEE, a{i}d)$", 26, WHITE,
                 bold=True, sample="오늘" if i == 0 else "금토일월"[i - 1]),
            text(170, y - 2, f"${wx_emoji(f'wf(icon, {i})')}$", 28, sample=em),
            text(250, y, f"$wf(min, {i})$°", 26, LABEL2, bold=True,
                 align="RIGHT", width=80, sample=f"{mn}°"),
            rect(bar_x, y + 14, bar_w, 8, FILL, 4, f"Track {i}"),
            seg,
            text(580, y, f"$wf(max, {i})$°", 26, WHITE, bold=True,
                 sample=f"{mx}°"),
        ]
    return items


# --------------------------------------------------------------------------
# Analog clocks.

def hand(d, w, length, color, tail=0, title="Hand"):
    """A hand drawn pointing at 12 inside a d x d box (rotation center)."""
    return [
        rect(0, 0, d, d, CLEAR, title=f"{title} box"),
        rect(d / 2 - w / 2, d / 2 - length, w, length + tail, color, w / 2,
             title),
    ]


def clock_face(cx, cy, d, num_size, num_r, face, ink, second=True,
               hour_rot=None, min_rot=None, samples=(304.75, 57.0, 180.0),
               face_formula=None, ink_formula=None, title="Clock"):
    def ink_it(m, key="paint_color"):
        if ink_formula:
            formula(m, key, ink_formula, ink)
        return m

    f = circle(cx, cy, d, face, f"{title} face")
    if face_formula:
        formula(f, "paint_color", face_formula, face)
    items = [f, circle(cx, cy, d, "#26FFFFFF", f"{title} edge", stroke=1.5)]
    for n in range(1, 13):
        a = math.radians(n * 30)
        tx, ty = cx + num_r * math.sin(a), cy - num_r * math.cos(a)
        items.append(ink_it(text(tx - num_size, ty - num_size * 0.62, str(n),
                                 num_size, ink, bold=True, align="CENTER",
                                 width=num_size * 2)))
    hs = d  # rotation boxes share the face center
    hw, hl = max(4, d * 0.035), d * 0.26
    mw, ml = max(3, d * 0.028), d * 0.40
    hour = layer([ink_it(m) if m["paint_color"] != CLEAR else m
                  for m in hand(hs, hw, hl, ink, title="Hour")],
                 cx - hs / 2, cy - hs / 2, "Hour hand",
                 rotate=None if hour_rot else "CLOCK_HOUR_SMOOTH",
                 rotate_formula=hour_rot, sample_angle=samples[0])
    minute = layer([ink_it(m) if m["paint_color"] != CLEAR else m
                    for m in hand(hs, mw, ml, ink, title="Minute")],
                   cx - hs / 2, cy - hs / 2, "Minute hand",
                   rotate=None if min_rot else "CLOCK_MINUTE",
                   rotate_formula=min_rot, sample_angle=samples[1])
    items += [hour, minute]
    cap = ink_it(circle(cx, cy, max(8, d * 0.05), ink, f"{title} cap"))
    items.append(cap)
    if second:
        items.append(layer(hand(hs, max(2, d * 0.01), d * 0.45, ORANGE,
                                tail=d * 0.08, title="Second"),
                           cx - hs / 2, cy - hs / 2, "Second hand",
                           rotate="CLOCK_SECOND", sample_angle=samples[2]))
        items.append(circle(cx, cy, max(4, d * 0.022), ORANGE, f"{title} pin"))
    return items


# --------------------------------------------------------------------------
# Widgets.

def w_clock_small():
    w, h = S
    return dict(size=S, title="iOS Clock · Small", features="ANALOG_CLOCK",
                desc="시계 앱: 아날로그 시계 (스몰)",
                items=[layer(clock_face(w / 2, h / 2, 292, 26, 116,
                                        "#8C000000", WHITE),
                             tap=tap_app(GOOGLE_CLOCK), title="Clock")])


WORLD = [("서울", 0), ("쿠퍼티노", -16), ("런던", -8), ("뉴욕", -13)]


def w_world_clock():
    w, h = M
    globals_ = {}
    items = []
    colw = (w - 2 * PAD) / 4
    sample_h = [10, 18, 2, 21]
    for i, (city, off) in enumerate(WORLD):
        k = i + 1
        globals_[f"c{k}"] = {"type": "TEXT", "title": f"도시 {k}", "value": city,
                             "description": "표시할 도시 이름"}
        globals_[f"o{k}"] = {"type": "NUMBER", "title": f"시차 {k}",
                             "value": float(off), "min": -24, "max": 24,
                             "description": "현지 시간과의 차이(시간). 서머타임 때 1 조정"}
        mod = shift(f"gv(o{k})", "h")
        day = f"(df(H, {mod})>=6 & df(H, {mod})<18)"
        is_day = 6 <= sample_h[i] < 18
        cx = PAD + colw * i + colw / 2
        cy = 128
        items += clock_face(
            cx, cy, 140, 15, 54,
            "#FFF2F2F7" if is_day else "#FF1C1C1E",
            "#FF000000" if is_day else WHITE,
            hour_rot=f"$df(h, {mod})*30+df(m)/2$",
            min_rot="$df(m)*6$",
            samples=(sample_h[i] % 12 * 30 + 4.5, 54, 180),
            face_formula=f"$if({day}, #FFF2F2F7, #FF1C1C1E)$",
            ink_formula=f"$if({day}, #FF000000, {WHITE})$",
            title=city)
        items += [
            text(cx - colw / 2, 212, f"$gv(c{k})$", 26, WHITE, bold=True,
                 align="CENTER", width=colw, sample=city),
            text(cx - colw / 2, 248,
                 f'$if(gv(o{k})=0, "현지 시간", df("a h:mm", {mod}))$', 21,
                 LABEL2, align="CENTER", width=colw,
                 sample="현지 시간" if off == 0 else
                 ["", "오후 6:09", "오전 2:09", "오후 9:09"][i]),
        ]
    return dict(size=M, title="iOS World Clock · Medium",
                features="ANALOG_CLOCK", globals=globals_,
                desc="시계 앱: 세계 시계 (미디엄). 전역 변수에서 도시/시차 편집",
                items=[layer(items, tap=tap_app(GOOGLE_CLOCK),
                             title="World clock")])


def w_alarm_small():
    w, h = S
    on = "tc(len, si(alarmt))>0"
    nd = "si(alarmd)"
    items = [
        icon(PAD - 2, 28, "alarm", 40, ORANGE),
        text(PAD + 46, 33, "알람", 26, ORANGE, bold=True),
        text(PAD, 150, f'$if({on}, df(a, {nd}), "")$', 28, LABEL2, bold=True,
             sample="오전"),
        text(PAD - 4, 176, f'$if({on}, df("h:mm", {nd}), "--:--")$', 84, WHITE,
             sample="7:00"),
        text(PAD, 282,
             f'$if({on}, if(df(D, {nd})=df(D), "오늘", df(D, {nd})=df(D, a1d), '
             f'"내일", df(EEEE, {nd})), "설정된 알람 없음")$',
             24, LABEL2, bold=True, width=w - 2 * PAD, sample="내일"),
    ]
    return dict(size=S, title="iOS Alarm · Small", desc="시계 앱: 다음 알람 (스몰)",
                items=[layer(items, tap=tap_app(GOOGLE_CLOCK), title="Alarm")])


def big_date(x, y, w):
    return [
        text(x, y, "$tc(up, df(EEEE))$", 26, RED, bold=True, width=w,
             sample="목요일"),
        text(x - 3, y + 26, "$df(d)$", 84, WHITE, sample="29"),
    ]


def w_cal_upnext_small():
    w, h = S
    items = big_date(PAD, 28, w - 2 * PAD)
    items += event_rows(PAD, 172, 2, 80, 25, 21, w - 2 * PAD, 11)
    return dict(size=S, title="iOS Calendar Up Next · Small",
                desc="캘린더 앱: 다음 일정 (스몰)",
                items=[layer(items, tap=tap_app(GOOGLE_CALENDAR),
                             title="Up next")])


def w_cal_month_small():
    w, h = S
    items = [text(30, 24, "$tc(up, df(MMMM))$", 24, RED, bold=True,
                  sample="10월")]
    items += month_grid(20, 64, 300 / 7, 39, 19, 16, 32)
    return dict(size=S, title="iOS Calendar Month · Small", globals=CAL_GLOBALS,
                desc="캘린더 앱: 월간 달력 (스몰)",
                items=[layer(items, tap=tap_app(GOOGLE_CALENDAR),
                             title="Month")])


def w_cal_list_medium():
    w, h = M
    items = big_date(PAD, 28, 200)
    items += event_rows(250, 34, 3, 92, 26, 22, w - 250 - PAD, 22)
    return dict(size=M, title="iOS Calendar List · Medium",
                desc="캘린더 앱: 일정 목록 (미디엄)",
                items=[layer(items, tap=tap_app(GOOGLE_CALENDAR),
                             title="List")])


def w_cal_large():
    w, h = L
    items = big_date(PAD, 28, 300)
    items += [text(400, 30, "$tc(up, df(MMMM))$", 20, RED, bold=True,
                   sample="10월")]
    items += month_grid(396, 58, 300 / 7, 24, 15, 13, 24)
    items += [rect(PAD, 232, w - 2 * PAD, 1.5, "#26FFFFFF", title="Divider")]
    items += event_rows(PAD, 258, 5, 98, 28, 23, w - 2 * PAD, 30)
    return dict(size=L, title="iOS Calendar · Large", globals=CAL_GLOBALS,
                desc="캘린더 앱: 날짜 + 월간 + 일정 (라지)",
                items=[layer(items, tap=tap_app(GOOGLE_CALENDAR),
                             title="Calendar")])


def w_weather_small():
    return dict(size=S, title="iOS Weather · Small", desc="날씨 앱 (스몰)",
                items=[layer(weather_header(S[0], True), title="Weather",
                             tap={"action": "KUSTOM_ACTION",
                                  "kustom_action": "WEATHER_UPDATE"})])


def w_weather_medium():
    w, h = M
    items = weather_header(w, False)
    items += [rect(PAD, 186, w - 2 * PAD, 1.5, "#26FFFFFF", title="Divider")]
    items += hourly_row(w, 206)
    return dict(size=M, title="iOS Weather · Medium",
                desc="날씨 앱: 시간별 예보 (미디엄)",
                items=[layer(items, title="Weather",
                             tap={"action": "KUSTOM_ACTION",
                                  "kustom_action": "WEATHER_UPDATE"})])


def w_weather_large():
    w, h = L
    items = weather_header(w, False)
    items += [rect(PAD, 186, w - 2 * PAD, 1.5, "#26FFFFFF", title="Divider")]
    items += hourly_row(w, 206)
    items += [rect(PAD, 340, w - 2 * PAD, 1.5, "#26FFFFFF", title="Divider")]
    items += daily_rows(w, 372, 76)
    return dict(size=L, title="iOS Weather · Large", globals=WX_GLOBALS,
                desc="날씨 앱: 시간별 + 5일 예보 (라지)",
                items=[layer(items, title="Weather",
                             tap={"action": "KUSTOM_ACTION",
                                  "kustom_action": "WEATHER_UPDATE"})])


BATT_COLOR = (f"$if(bi(charging)=1, {GREEN}, bi(level)<=20, {RED}, {GREEN})$")
BATT_ICON = '$if(bi(charging)=1, "battery_charging_full", "smartphone")$'


def batt_ring(cx, cy, d, thick, icon_size):
    r = ring(cx, cy, d, thick, "$bi(level)$", GREEN, sample=82,
             title="Battery ring")
    formula(r, "color_fgcolor", BATT_COLOR, GREEN)
    ic = icon(cx - icon_size / 2, cy - icon_size / 2, "smartphone", icon_size)
    formula(ic, "icon_icon", BATT_ICON, "smartphone")
    return [r, ic]


def w_batt_small():
    w, h = S
    items = batt_ring(w / 2, 136, 200, 20, 76)
    items += [text(PAD, 256, "$bi(level)$%", 44, WHITE, bold=True,
                   align="CENTER", width=w - 2 * PAD, sample="82%")]
    return dict(size=S, title="iOS Batteries · Small", desc="배터리 (스몰)",
                items=[layer(items, title="Batteries")])


def w_batt_medium():
    w, h = M
    items = batt_ring(PAD + 130, h / 2, 236, 22, 88)
    status = '$if(bi(charging)=1, "충전 중", bi(level)<=20, "배터리 부족", "배터리")$'
    items += [
        text(330, 70, status, 26, LABEL2, bold=True, sample="배터리"),
        text(326, 104, "$bi(level)$%", 96, WHITE, bold=True, sample="82%"),
        rect(330, 248, 360, 12, FILL, 6, "Battery track"),
    ]
    bar = rect(330, 248, 295, 12, GREEN, 6, "Battery bar")
    formula(bar, "shape_width", "$mu(max, 12, 360*bi(level)/100)$", 295)
    formula(bar, "paint_color", BATT_COLOR, GREEN)
    items.append(bar)
    return dict(size=M, title="iOS Batteries · Medium", desc="배터리 (미디엄)",
                items=[layer(items, title="Batteries")])


def cover(x, y, s, r):
    c = rect(x, y, s, s, "#FF2C2C2E", r, "Album art")
    c.update(fx_gradient="BITMAP")
    formula(c, "fx_gradient_bitmap", "$mi(cover)$", "art")
    return c


MUSIC_TINT = ("$if(mi(state)=NONE, #00000000, ce(bp(dominant, mi(cover)), "
              "alpha, 30))$", "#4DB3477A")


def w_music_small():
    w, h = S
    items = [
        cover(PAD, PAD, 150, 18),
        icon(w - PAD - 44, PAD, "music_note", 44, "#FFFF375F"),
        text(PAD, 206, '$if(mi(state)=NONE, "재생 중 아님", tc(ell, mi(title), 16))$',
             26, WHITE, bold=True, width=w - 2 * PAD, sample="Liquid Days"),
        text(PAD, 242, "$tc(ell, mi(artist), 20)$", 23, LABEL2,
             width=w - 2 * PAD, sample="Glass Animals"),
    ]
    return dict(size=S, title="iOS Music · Small", features="MUSIC",
                desc="음악/팟캐스트: 지금 재생 중 (스몰)", tint=MUSIC_TINT,
                items=[layer(items, tap=TAP_MUSIC_APP, title="Now playing")])


def w_music_medium():
    w, h = M
    x0 = PAD + 276 + 28
    bw = w - PAD - x0
    bar = rect(x0, 210, bw * 0.38, 6, WHITE, 3, "Progress")
    formula(bar, "shape_width", f"$mu(max, 6, {bw}*mi(percent)/100)$",
            bw * 0.38)
    play = icon(0, 0, "play_arrow", 68)
    formula(play, "icon_icon",
            '$if(mi(state)=PLAYING, "pause", "play_arrow")$', "pause")
    items = [
        layer([cover(0, 0, 276, 22)], PAD, PAD, "Art", tap=TAP_MUSIC_APP),
        text(x0, 40, '$if(mi(state)=NONE, "재생 중 아님", mi(title))$', 30,
             WHITE, bold=True, width=bw, sample="Liquid Days"),
        text(x0, 80, "$mi(artist)$", 25, LABEL2, width=bw,
             sample="Glass Animals"),
        text(x0, 114, "$mi(album)$", 22, LABEL3, width=bw, sample="Dreamland"),
        rect(x0, 210, bw, 6, "#40FFFFFF", 3, "Track"),
        bar,
        text(x0, 224, "$tf(mi(pos), m:ss)$", 18, LABEL2, sample="1:24"),
        text(x0, 224, "-$tf(mi(len)-mi(pos), m:ss)$", 18, LABEL2,
             align="RIGHT", width=bw, sample="-2:16"),
        layer([icon(0, 0, "skip_previous", 56)], x0 + 6, 252, "Prev",
              tap={"action": "MUSIC", "music_action": "PREVIOUS"}),
        layer([play], x0 + bw / 2 - 34, 246, "Play/Pause",
              tap={"action": "MUSIC"}),
        layer([icon(0, 0, "skip_next", 56)], x0 + bw - 62, 252, "Next",
              tap={"action": "MUSIC", "music_action": "NEXT"}),
    ]
    return dict(size=M, title="iOS Music · Medium", features="MUSIC",
                desc="음악/팟캐스트: 지금 재생 중 + 컨트롤 (미디엄)",
                tint=MUSIC_TINT, items=[layer(items, title="Now playing")])


def w_fitness_small():
    w, h = S
    cx, cy = w / 2, 122
    goals = {"g1": ("움직이기 목표 (kcal)", 500), "g2": ("걸음 목표", 8000),
             "g3": ("거리 목표 (km)", 5)}
    globals_ = {k: {"type": "NUMBER", "title": t, "value": float(v), "min": 1,
                    "max": 100000} for k, (t, v) in goals.items()}
    rings = [
        (186, MOVE, "#40FA114F", "$100*fd(cals)/gv(g1)$", 72),
        (138, EXERCISE, "#40A6FF00", "$100*fd(steps)/gv(g2)$", 58),
        (90, STAND, "#4000F0FF", "$100*fd(dista)/1000/gv(g3)$", 85),
    ]
    items = [ring(cx, cy, d, 22, lvl, fg, bg, sample=s, title="Ring")
             for d, fg, bg, lvl, s in rings]
    items += [
        text(PAD, 226, "$mu(round, fd(cals))$/$gv(g1)$kcal", 23, MOVE,
             bold=True, width=w - 2 * PAD, sample="362/500kcal"),
        text(PAD, 256, "$fd(steps)$/$gv(g2)$걸음", 23, EXERCISE, bold=True,
             width=w - 2 * PAD, sample="4,630/8000걸음"),
        text(PAD, 286, "$mu(round, fd(dista)/100)/10$/$gv(g3)$km", 23, STAND,
             bold=True, width=w - 2 * PAD, sample="4.3/5km"),
    ]
    return dict(size=S, title="iOS Fitness · Small", globals=globals_,
                desc="피트니스: 활동 링 (스몰). 전역 변수에서 목표 편집",
                items=[layer(items, title="Activity")])


YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/"


def stock_exprs(k):
    url = f'"{YAHOO}"+gv(s{k})+"?range=1d&interval=1d"'
    meta = ".chart.result[0].meta"
    price = f'wg({url}, json, "{meta}.regularMarketPrice")'
    prev = f'wg({url}, json, "{meta}.chartPreviousClose")'
    pct = f"mu(round, ({price}-{prev})/{prev}*10000)/100"
    return price, prev, pct


STOCKS = [("^KS11", "코스피"), ("005930.KS", "삼성전자"), ("AAPL", "Apple"),
          ("TSLA", "Tesla")]


def stock_globals(n):
    g = {}
    for k in range(1, n + 1):
        sym, name = STOCKS[k - 1]
        g[f"s{k}"] = {"type": "TEXT", "title": f"종목 {k}", "value": sym,
                      "description": "Yahoo Finance 심볼 (예: AAPL, 005930.KS)"}
        g[f"n{k}"] = {"type": "TEXT", "title": f"이름 {k}", "value": name}
    return g


def w_stocks_small():
    w, h = S
    price, prev, pct = stock_exprs(1)
    up = f"{price}>={prev}"
    chg = text(PAD, 276, f'$if({up}, "+", "")+{pct}$%', 26, GREEN, bold=True,
               sample="+1.24%")
    formula(chg, "paint_color", f"$if({up}, {GREEN}, {RED})$", GREEN)
    items = [
        text(PAD, 28, "$gv(n1)$", 30, WHITE, bold=True, width=w - 2 * PAD,
             sample="코스피"),
        text(PAD, 68, "$gv(s1)$", 22, LABEL2, sample="^KS11"),
        text(PAD, 214, f"$mu(round, {price}*100)/100$", 48, WHITE, bold=True,
             width=w - 2 * PAD, sample="2,612.43"),
        chg,
    ]
    return dict(size=S, title="iOS Stocks · Small", globals=stock_globals(1),
                features="DOWNLOAD", desc="주식 (스몰). Yahoo Finance",
                items=[layer(items, title="Stock")])


def w_stocks_medium():
    w, h = M
    items = []
    samples = [("2,612.43", "+1.24%", True), ("61,300", "-0.81%", False),
               ("231.58", "+0.42%", True)]
    for i in range(3):
        k = i + 1
        y = 30 + i * 98
        price, prev, pct = stock_exprs(k)
        up = f"{price}>={prev}"
        pill = rect(w - PAD - 136, y + 6, 136, 52, GREEN, 12, f"Change {k}")
        formula(pill, "paint_color", f"$if({up}, {GREEN}, {RED})$",
                GREEN if samples[i][2] else RED)
        items += [
            text(PAD, y, f"$gv(n{k})$", 28, WHITE, bold=True, width=300,
                 sample=STOCKS[i][1]),
            text(PAD, y + 38, f"$gv(s{k})$", 21, LABEL2, sample=STOCKS[i][0]),
            text(330, y + 12, f"$mu(round, {price}*100)/100$", 30, WHITE,
                 bold=True, align="RIGHT", width=200, sample=samples[i][0]),
            pill,
            text(w - PAD - 136, y + 16, f'$if({up}, "+", "")+{pct}$%', 24,
                 WHITE, bold=True, align="CENTER", width=136,
                 sample=samples[i][1]),
        ]
        if i < 2:
            items.append(rect(PAD, y + 82, w - 2 * PAD, 1.5, "#1FFFFFFF",
                              title="Divider"))
    return dict(size=M, title="iOS Stocks · Medium", globals=stock_globals(3),
                features="DOWNLOAD", desc="주식: 관심 목록 (미디엄). Yahoo Finance",
                items=[layer(items, title="Stocks")])


TODO = ["장보기", "세탁소 들르기", "엄마께 전화", "운동 30분"]


def w_reminders_medium():
    w, h = M
    g = {}
    for k in range(1, 5):
        g[f"t{k}"] = {"type": "TEXT", "title": f"할 일 {k}", "value": TODO[k - 1]}
        g[f"d{k}"] = {"type": "SWITCH", "title": f"완료 {k}",
                      "value": 1 if k == 2 else 0}
    left = "+".join(f"(tc(len, gv(t{k}))>0 & gv(d{k})=0)" for k in range(1, 5))
    items = [
        circle(PAD + 30, PAD + 30, 60, BLUE, "List badge"),
        icon(PAD + 10, PAD + 10, "format_list_bulleted", 40),
        text(PAD, 186, f"$({left})$", 72, WHITE, bold=True, sample="3"),
        text(PAD, 278, "미리 알림", 26, BLUE, bold=True, sample="미리 알림"),
    ]
    x0 = 250
    for k in range(1, 5):
        y = 36 + (k - 1) * 72
        done = k == 2
        ic = icon(0, 0, "radio_button_unchecked", 40, LABEL3)
        formula(ic, "icon_icon",
                f'$if(gv(d{k})=1, "check_circle", "radio_button_unchecked")$',
                "check_circle" if done else "radio_button_unchecked")
        formula(ic, "paint_color", f"$if(gv(d{k})=1, {ORANGE}, {LABEL3})$",
                ORANGE if done else LABEL3)
        tx = text(56, 4, f"$gv(t{k})$", 26, WHITE, width=w - PAD - x0 - 56,
                  sample=TODO[k - 1])
        formula(tx, "paint_color", f"$if(gv(d{k})=1, {LABEL2}, {WHITE})$",
                LABEL2 if done else WHITE)
        items.append(layer([ic, tx], x0, y, f"Todo {k}",
                           visible=f"$if(tc(len, gv(t{k}))>0, ALWAYS, REMOVE)$",
                           tap={"action": "SWITCH_GLOBAL", "switch": f"d{k}"}))
        if k < 4:
            items.append(rect(x0 + 56, y + 58, w - PAD - x0 - 56, 1.5,
                              "#1FFFFFFF", title="Divider"))
    return dict(size=M, title="iOS Reminders · Medium", globals=g,
                desc="미리 알림 (미디엄). 전역 변수에 할 일 입력, 탭해서 완료",
                items=[layer(items, title="Reminders")])


def w_notes_small():
    w, h = S
    g = {"t": {"type": "TEXT", "title": "제목", "value": "주말 계획"},
         "b": {"type": "TEXT", "title": "내용",
               "value": "토요일 오전 등산, 오후 카페에서 책 읽기. 일요일 장보기."}}
    items = [
        icon(PAD - 4, 26, "description", 36, YELLOW),
        text(PAD + 38, 30, "메모", 26, YELLOW, bold=True),
        text(PAD, 84, "$gv(t)$", 28, WHITE, bold=True, width=w - 2 * PAD,
             lines=2, sample="주말 계획"),
        text(PAD, 128, "$gv(b)$", 23, LABEL2, width=w - 2 * PAD, lines=5,
             sample="토요일 오전 등산, 오후 카페에서 책 읽기. 일요일 장보기."),
    ]
    return dict(size=S, title="iOS Notes · Small", globals=g,
                desc="메모 (스몰). 전역 변수에 제목/내용 입력",
                items=[layer(items, title="Note")])


def w_photos_small():
    w, h = S
    photo = rect(0, 0, w, h, "#FF2C2C2E", RADIUS, "Photo (pick image: FX > Bitmap)")
    photo.update(fx_gradient="BITMAP")
    photo["_s"] = {"fx_gradient_bitmap": "photo"}
    items = [
        photo,
        rect(0, h * 0.5, w, h * 0.5, "#00000000", RADIUS, "Scrim",
             grad=("#99000000", "VERTICAL")),
        text(PAD, h - 92, "추천 사진", 26, WHITE, bold=True),
        text(PAD, h - 58, '$df("yyyy년 M월 d일")$', 21, "#CCFFFFFF",
             sample="2026년 10월 29일"),
        rect(1, 1, w - 2, h - 2, "#73FFFFFF", RADIUS - 1, "Glass rim",
             stroke=2, grad=("#14FFFFFF", "VERTICAL")),
    ]
    return dict(size=S, title="iOS Photos · Small", glass=False,
                desc="사진 (스몰). 편집기에서 Photo 모듈의 비트맵 선택",
                items=[layer(items, title="Photo")])


WIDGETS = {
    "clock_analog_small": w_clock_small,
    "clock_world_medium": w_world_clock,
    "clock_alarm_small": w_alarm_small,
    "calendar_upnext_small": w_cal_upnext_small,
    "calendar_month_small": w_cal_month_small,
    "calendar_list_medium": w_cal_list_medium,
    "calendar_large": w_cal_large,
    "weather_small": w_weather_small,
    "weather_medium": w_weather_medium,
    "weather_large": w_weather_large,
    "batteries_small": w_batt_small,
    "batteries_medium": w_batt_medium,
    "music_small": w_music_small,
    "music_medium": w_music_medium,
    "fitness_small": w_fitness_small,
    "stocks_small": w_stocks_small,
    "stocks_medium": w_stocks_medium,
    "reminders_medium": w_reminders_medium,
    "notes_small": w_notes_small,
    "photos_small": w_photos_small,
}


# --------------------------------------------------------------------------
# Export.

MARGIN = 14  # room for the glass shadow inside the widget cell


def build_preset(spec):
    w, h = spec["size"]
    panel = (glass(w, h, spec.get("tint")) if spec.get("glass", True) else [])
    panel = layer(panel + spec["items"], title="Widget")
    panel["position_anchor"] = "CENTER"
    del panel["position_offset_x"], panel["position_offset_y"]
    root = {"internal_type": "RootLayerModule", "viewgroup_items": [panel]}
    formula(root, "config_scale_value",
            f"$mu(min, si(rwidth)/{w + 2 * MARGIN}, "
            f"si(rheight)/{h + 2 * MARGIN})*100$")
    globals_ = spec.get("globals") or {}
    if globals_:
        root["globals_list"] = {}
        for i, (k, g) in enumerate(globals_.items()):
            g = dict(g, index=i)
            if "global_formula" in g:
                g["toggles"] = 10
            root["globals_list"][k] = g
    info = {
        "archive": None, "author": "Phil iOS widget pack",
        "description": spec["desc"] + " · iOS 다크 모드 / Liquid Glass 스타일",
        "email": "", "features": spec.get("features", ""), "pflags": 0,
        "height": h + 2 * MARGIN, "locked": False, "release": 377435216,
        "title": spec["title"], "version": 13, "width": w + 2 * MARGIN,
        "xscreens": 0, "yscreens": 0,
    }
    return {"preset_info": info, "preset_root": root}


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o


# --------------------------------------------------------------------------
# Preview renderer (SVG) for the subset of modules used above.

def rgba(c):
    c = c.lstrip("#")
    a, r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4, 6))
    return f"rgba({r},{g},{b},{a / 255:.3f})"


def sample(m, key):
    return m.get("_s", {}).get(key, m.get(key))


class Svg:
    def __init__(self, prefix):
        self.defs, self.n, self.prefix = [], 0, prefix

    def uid(self):
        self.n += 1
        return f"{self.prefix}{self.n}"

    def paint(self, m, x, y, w, h):
        col = sample(m, "paint_color")
        g = m.get("fx_gradient")
        if g == "BITMAP":
            kind = sample(m, "fx_gradient_bitmap")
            i = self.uid()
            stops = (["#f7797d", "#c471ed", "#12c2e9"] if kind == "art"
                     else ["#355c7d", "#6c5b7b", "#f8b195"])
            self.defs.append(
                f'<linearGradient id="{i}" x1="0" y1="0" x2="1" y2="1">'
                + "".join(f'<stop offset="{k / 2}" stop-color="{s}"/>'
                          for k, s in enumerate(stops)) + "</linearGradient>")
            return f"url(#{i})"
        if g in ("VERTICAL", "HORIZONTAL"):
            i = self.uid()
            x2, y2 = ("0", "1") if g == "VERTICAL" else ("1", "0")
            self.defs.append(
                f'<linearGradient id="{i}" x1="0" y1="0" x2="{x2}" y2="{y2}">'
                f'<stop offset="0" stop-color="{rgba(col)}"/>'
                f'<stop offset="1" stop-color="{rgba(m["fx_gradient_color"])}"/>'
                "</linearGradient>")
            return f"url(#{i})"
        return rgba(col)

    def render(self, m, ox=0.0, oy=0.0):
        t = m["internal_type"]
        x = ox + sample(m, "position_offset_x") if "position_offset_x" in m else ox
        y = oy + sample(m, "position_offset_y") if "position_offset_y" in m else oy
        if t == "OverlapLayerModule":
            inner = "".join(self.render(c, x, y) for c in m["viewgroup_items"])
            ang = m.get("_s", {}).get("angle")
            if ang is not None:
                box = m["viewgroup_items"][0]
                cx = x + box["position_offset_x"] + box["shape_width"] / 2
                cy = y + box["position_offset_y"] + box["shape_height"] / 2
                return f'<g transform="rotate({ang} {cx} {cy})">{inner}</g>'
            return f"<g>{inner}</g>"
        if t == "ShapeModule":
            w, h = sample(m, "shape_width"), m["shape_height"]
            fill = self.paint(m, x, y, w, h)
            flt = ""
            if m.get("fx_shadow"):
                i = self.uid()
                self.defs.append(
                    f'<filter id="{i}" x="-20%" y="-20%" width="140%" height="140%">'
                    f'<feDropShadow dx="0" dy="{m["fx_shadow_distance"]}" '
                    f'stdDeviation="{m["fx_shadow_blur"] / 2}" '
                    f'flood-color="{rgba(m["fx_shadow_color"])}"/></filter>')
                flt = f' filter="url(#{i})"'
            if m.get("paint_style") == "STROKE":
                s = m["paint_stroke"]
                style = f'fill="none" stroke="{fill}" stroke-width="{s}"'
            else:
                style = f'fill="{fill}"'
            if m["shape_type"] == "CIRCLE":
                return (f'<circle cx="{x + w / 2}" cy="{y + h / 2}" r="{w / 2}" '
                        f'{style}{flt}/>')
            r = m.get("shape_corners", 0)
            return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
                    f'{style}{flt}/>')
        if t == "TextModule":
            s = m["_s"]
            size = m["text_size"]
            col = rgba(sample(m, "paint_color"))
            width = m.get("text_width")
            anchor, tx = "start", x
            if s["align"] == "CENTER":
                anchor, tx = "middle", x + width / 2
            elif s["align"] == "RIGHT":
                anchor, tx = "end", x + width
            weight = 700 if s["bold"] else 400
            lines = [s["text"]]
            if width and m.get("text_lines", 1) > 1:
                lines = wrap(s["text"], width, size, int(m["text_lines"]))
            out = ""
            for k, ln in enumerate(lines):
                out += (f'<text x="{tx}" y="{y + size * (0.95 + 1.25 * k)}" '
                        f'font-size="{size}" font-weight="{weight}" '
                        f'text-anchor="{anchor}" fill="{col}">{esc(ln)}</text>')
            return out
        if t == "FontIconModule":
            size = m["icon_size"]
            return (f'<text x="{x}" y="{y + size}" font-size="{size}" '
                    f'class="mi" fill="{rgba(sample(m, "paint_color"))}">'
                    f'{sample(m, "icon_icon")}</text>')
        if t == "ProgressModule":
            d, th = m["style_size"], m["style_height"]
            r = (d - th) / 2
            cx, cy = x + d / 2, y + d / 2
            circ = 2 * math.pi * r
            lv = sample(m, "progress_level") / m["progress_max"]
            fg = rgba(sample(m, "color_fgcolor"))
            return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
                    f'stroke="{rgba(m["color_bgcolor"])}" stroke-width="{th}"/>'
                    f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{fg}" '
                    f'stroke-width="{th}" stroke-dasharray="{circ * lv} {circ}" '
                    f'transform="rotate(-90 {cx} {cy})"/>')
        raise ValueError(t)


def wrap(s, width, size, max_lines):
    per = max(1, int(width / (size * 0.9)))
    out = [s[i:i + per] for i in range(0, len(s), per)]
    return out[:max_lines]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_svg(name, preset_tree, w, h):
    sv = Svg(name)
    panel = preset_tree["viewgroup_items"][0]
    body = "".join(sv.render(c, MARGIN, MARGIN) for c in panel["viewgroup_items"])
    W, H = w + 2 * MARGIN, h + 2 * MARGIN
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}"><defs>{"".join(sv.defs)}</defs>{body}</svg>')


def main():
    DIST.mkdir(exist_ok=True)
    PREVIEWS.mkdir(exist_ok=True)
    for name, fn in WIDGETS.items():
        spec = fn()
        preset = build_preset(spec)
        w, h = spec["size"]
        svg = render_svg(name, preset["preset_root"], w, h)
        (PREVIEWS / f"{name}.svg").write_text(svg)
        thumb = PREVIEWS / f"{name}.jpg"
        with zipfile.ZipFile(DIST / f"{name}.kwgt", "w",
                             zipfile.ZIP_DEFLATED) as z:
            z.writestr("preset.json",
                       json.dumps(strip(preset), ensure_ascii=False, indent=1))
            if thumb.exists():
                z.write(thumb, "preset_thumb_portrait.jpg")
                z.write(thumb, "preset_thumb_landscape.jpg")
        print(f"{name:24s} {w}x{h}")


if __name__ == "__main__":
    main()
