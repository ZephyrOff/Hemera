"""Gradient stop interpolation — independent of any specific device.

Ported from the alex_light_studio Home Assistant integration (same author,
same real hardware; see /NOTICE) rather than written from scratch, because
it exists to solve a problem already solved and validated there: Aqara's
LED Strip T1 (and similar) has no onboard interpolation between segments at
all — every physical LED segment is set to an explicit, independent color.
A real Hue Gradient Lightstrip's own driver silicon smooths N colour points
across however many physical LEDs it has; Aqara's doesn't, so *something*
has to compute one color per physical segment from however many colour
points the Hue app actually sent — which, per real-world testing, is fewer
than the strip's real segment count (the app appears to cap how many
gradient points it lets you place well below what devices like this
actually have). Without this, a bridge that just forwards the app's N
points 1:1 as `segment_colors` only lights the first N physical segments,
leaving the rest of the strip showing whatever they last displayed.

A gradient is stored as anchor points (position 0.0-1.0, hex colour) rather
than a fixed number of colours — exactly the same principle as a CSS
gradient — so it stays meaningful regardless of how many colours were
supplied versus how many physical segments the target strip has.
`resample_stops` resamples those anchors into exactly N colours by linear
interpolation at the point of sending a command, not before.
"""

from __future__ import annotations


def colors_to_stops(colors: list[str]) -> list[dict]:
    """Turn N colours (assumed evenly spaced along the original source) into
    {position, color} anchor points."""
    n = len(colors)
    if n == 0:
        return []
    if n == 1:
        return [{"position": 0.0, "color": colors[0]}]
    return [{"position": i / (n - 1), "color": color} for i, color in enumerate(colors)]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "#ffffff").lstrip("#")
    if len(h) != 6:
        return (255, 255, 255)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp_color(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex((r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t))


def resample_stops(stops: list[dict], segments: int) -> list[str]:
    """Resample anchor points into exactly `segments` hex colours by linear
    interpolation — the same principle as rendering a CSS gradient at a
    given resolution. Anchors don't need to be pre-sorted or to cover the
    full [0,1] range."""
    if segments <= 0:
        return []
    if not stops:
        return ["#ffffff"] * segments

    sorted_stops = sorted(stops, key=lambda s: s["position"])
    if len(sorted_stops) == 1:
        return [sorted_stops[0]["color"]] * segments

    result: list[str] = []
    for i in range(segments):
        pos = i / (segments - 1) if segments > 1 else 0.0
        lo, hi = sorted_stops[0], sorted_stops[-1]
        for j in range(len(sorted_stops) - 1):
            if sorted_stops[j]["position"] <= pos <= sorted_stops[j + 1]["position"]:
                lo, hi = sorted_stops[j], sorted_stops[j + 1]
                break
        span = hi["position"] - lo["position"]
        t = 0.0 if span <= 0 else (pos - lo["position"]) / span
        result.append(_lerp_color(lo["color"], hi["color"], t))
    return result


def hex_to_rgb_obj(hex_color: str) -> dict:
    """hex -> {r,g,b}, the shape Aqara's `segment_colors` payload needs for
    each segment (distinct from the plain hex array Hue-format gradients use)."""
    r, g, b = _hex_to_rgb(hex_color)
    return {"r": r, "g": g, "b": b}
