"""Parse HueStream (v1 and v2) Entertainment frames.

Ported from 83noit/ha-hue-entertainment's ``entertainment.py`` (MIT) — see
/NOTICE — ``parse_huestream_frame`` is a pure function with no dependency on
any object model, kept verbatim.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HUESTREAM_HEADER = b"HueStream"
HUESTREAM_HEADER_SIZE = 52  # v2 header
HUESTREAM_CHANNEL_SIZE = 7  # bytes per channel in v2

COLOR_SPACE_RGB = 0x00
COLOR_SPACE_XY = 0x01

_V1_HEADER_SIZE = 16
_V1_CHANNEL_SIZE = 9


@dataclass
class ChannelColor:
    """Colour state for a single channel.

    Values are raw 16-bit unsigned integers (0-65535) for both RGB and XY modes.
    The interpretation depends on the frame's colorspace byte:
    - RGB: r/g/b are red/green/blue intensities.
    - XY:  r/g are CIE x/y (scaled: x = r / 65535), b is brightness.
    """

    channel_id: int
    r: int
    g: int
    b: int


def _parse_v2_channels(data: bytes) -> list[ChannelColor]:
    """Parse v2 channel data (7 bytes per channel after 52-byte header)."""
    channels = []
    offset = HUESTREAM_HEADER_SIZE
    while offset + HUESTREAM_CHANNEL_SIZE <= len(data):
        channel_id = data[offset]
        val1 = struct.unpack(">H", data[offset + 1 : offset + 3])[0]
        val2 = struct.unpack(">H", data[offset + 3 : offset + 5])[0]
        val3 = struct.unpack(">H", data[offset + 5 : offset + 7])[0]
        channels.append(ChannelColor(channel_id, val1, val2, val3))
        offset += HUESTREAM_CHANNEL_SIZE
    return channels


def _parse_v1_channels(data: bytes) -> list[ChannelColor]:
    """Parse v1 channel data (9 bytes per channel after 16-byte header)."""
    channels = []
    offset = _V1_HEADER_SIZE
    while offset + _V1_CHANNEL_SIZE <= len(data):
        # v1: 1 byte type, 2 bytes light ID, 2+2+2 bytes colour
        light_id = struct.unpack(">H", data[offset + 1 : offset + 3])[0]
        val1 = struct.unpack(">H", data[offset + 3 : offset + 5])[0]
        val2 = struct.unpack(">H", data[offset + 5 : offset + 7])[0]
        val3 = struct.unpack(">H", data[offset + 7 : offset + 9])[0]
        channels.append(ChannelColor(light_id, val1, val2, val3))
        offset += _V1_CHANNEL_SIZE
    return channels


def parse_huestream_frame(data: bytes) -> tuple[int, int, list[ChannelColor]] | None:
    """Parse a HueStream frame into (version, colorspace, channels).

    Returns None if the frame is invalid (bad magic, too short, unknown version).
    Pure function — no dependency on the object model or MQTT.
    """
    if not data.startswith(HUESTREAM_HEADER):
        return None

    # Need at least 15 bytes to read version (byte 9) and colorspace (byte 14)
    if len(data) < 15:
        return None

    api_version = data[9]
    color_space = data[14]

    if api_version == 0x02:
        if len(data) < HUESTREAM_HEADER_SIZE:
            return None
        channels = _parse_v2_channels(data)
    elif api_version == 0x01:
        if len(data) < _V1_HEADER_SIZE + _V1_CHANNEL_SIZE:
            return None
        channels = _parse_v1_channels(data)
    else:
        return None

    return (api_version, color_space, channels)
