"""Real Hue firmware update check against Philips' own API.

Adapted from diyHue's BridgeEmulator/services/updateManager.py::versionCheck()
(Apache-2.0) — see /NOTICE. Queries the same public endpoint real Hue
bridges use, and if Philips reports firmware newer than whatever
swversion/apiversion we currently report, adopts it as our own.

This exists because there is no actual firmware to install here — the
official Hue app compares the bridge's reported version against the latest
one Philips publishes and shows a permanently-stuck "your bridge needs an
update" prompt once our hardcoded value falls behind, exactly like it did
with diyHue before this check existed. Querying Philips directly, like a
real bridge implicitly does, keeps us self-reporting as current indefinitely
instead of requiring a manual version bump in this add-on every time.
"""

from __future__ import annotations

import aiohttp

from hemera.logging_setup import get_logger

logging = get_logger(__name__)

_UPDATE_URL = "https://firmware.meethue.com/v1/checkupdate/?deviceTypeId=BSB002&version={version}"
_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def check_for_update(cfg) -> None:
    config = cfg.yaml_config["config"]
    swversion = config["swversion"]
    url = _UPDATE_URL.format(version=swversion)
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as exc:
        logging.warning("Firmware update check against Philips failed (offline?): %s", exc)
        return

    updates = data.get("updates") or []
    if not updates:
        logging.debug("No firmware update reported by Philips (swversion=%s)", swversion)
        return
    latest = updates[-1]
    try:
        new_version = str(int(latest["version"]))
        # Matches diyHue's slicing exactly: "1.70.1970084010" -> "1.70" + ".0"
        new_apiversion = str(latest["versionName"])[:4] + ".0"
    except (KeyError, ValueError, TypeError) as exc:
        logging.warning("Unexpected response shape from Philips update check: %s", exc)
        return

    if int(new_version) <= int(swversion):
        logging.debug("Already reporting the latest known swversion=%s", swversion)
        return
    logging.info(
        "Adopting newer swversion/apiversion reported by Philips: %s/%s (was %s/%s)",
        new_version, new_apiversion, swversion, config["apiversion"],
    )
    config["swversion"] = new_version
    config["apiversion"] = new_apiversion
    cfg.mark_dirty("config")
