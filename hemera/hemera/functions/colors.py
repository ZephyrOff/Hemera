"""Colour-space conversions (RGB <-> CIE xy, HSV -> RGB).

Ported verbatim from diyHue's BridgeEmulator/functions/colors.py
(Apache-2.0) — see /NOTICE. Pure math, no protocol coupling.
"""

from __future__ import annotations


def clampRGB(rgb: list[float]) -> list[int]:
    r = sorted((0, int(rgb[0]), 255))[1]
    g = sorted((0, int(rgb[1]), 255))[1]
    b = sorted((0, int(rgb[2]), 255))[1]
    return [r, g, b]


def convert_rgb_xy(red: float, green: float, blue: float) -> list[float]:
    red = pow((red + 0.055) / 1.055, 2.4) if red > 0.04045 else red / 12.92
    green = pow((green + 0.055) / 1.055, 2.4) if green > 0.04045 else green / 12.92
    blue = pow((blue + 0.055) / 1.055, 2.4) if blue > 0.04045 else blue / 12.92

    X = red * 0.664511 + green * 0.154324 + blue * 0.162028
    Y = red * 0.283881 + green * 0.668433 + blue * 0.047685
    Z = red * 0.000088 + green * 0.072310 + blue * 0.986039

    div = X + Y + Z
    if div < 0.000001:
        return [0.0, 0.0]
    return [X / div, Y / div]


def convert_xy(x: float, y: float, bri: float) -> list[int]:
    X = x
    Y = y
    Z = 1.0 - x - y

    r = X * 3.2406 - Y * 1.5372 - Z * 0.4986
    g = -X * 0.9689 + Y * 1.8758 + Z * 0.0415
    b = X * 0.0557 - Y * 0.2040 + Z * 1.0570

    r = 12.92 * r if r <= 0.0031308 else 1.055 * pow(r, 1.0 / 2.4) - 0.055
    g = 12.92 * g if g <= 0.0031308 else 1.055 * pow(g, 1.0 / 2.4) - 0.055
    b = 12.92 * b if b <= 0.0031308 else 1.055 * pow(b, 1.0 / 2.4) - 0.055

    if r > b and r > g and r > 1:
        g, b, r = g / r, b / r, 1
    elif g > b and g > r and g > 1:
        r, b, g = r / g, b / g, 1
    elif b > r and b > g and b > 1:
        r, g, b = r / b, g / b, 1

    r = max(r, 0)
    g = max(g, 0)
    b = max(b, 0)
    return clampRGB([r * bri, g * bri, b * bri])


def hsv_to_rgb(h: float, s: float, v: float) -> list[int]:
    s = s / 254
    v = v / 254
    c = v * s
    x = c * (1 - abs(((h / 11850) % 2) - 1))
    m = v - c
    if h < 10992:
        r, g, b = c, x, 0
    elif h < 21845:
        r, g, b = x, c, 0
    elif h < 32837:
        r, g, b = 0, c, x
    elif h < 43830:
        r, g, b = 0, x, c
    elif h < 54813:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return clampRGB([r * 255, g * 255, b * 255])
