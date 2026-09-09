"""Entrypoint: load config, start the v1 + v2 HTTP(S) APIs, mDNS
advertisement, and the Zigbee2MQTT client.

SSDP and Hue Entertainment (DTLS/HueStream) are added in later steps of the
project plan — this wires up enough for the Hue app to discover, pair with,
and control Zigbee2MQTT lights through both the v1 and v2 (CLIP) APIs.
"""

from __future__ import annotations

import asyncio
import ssl
import signal
import sys

from aiohttp import web

from hemera.api.v1.routes import HueV1Api
from hemera.api.v2.eventstream import stream_v2_events, trim_eventstream_forever
from hemera.api.v2.routes import HueV2Api
from hemera.config.bootstrap import ensure_certificate, load_settings
from hemera.config.handler import Config, default_config
from hemera.logging_setup import configure_logging, get_logger
from hemera.services.mdns import MdnsAdvertiser
from hemera.services.mqtt_client import MqttClient

logging = get_logger(__name__)

_CONFIG_SAVE_INTERVAL_S = 5.0


async def _periodic_config_save(cfg: Config, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=_CONFIG_SAVE_INTERVAL_S)
        except TimeoutError:
            pass
        cfg.save_dirty_if_needed()


async def async_main() -> None:
    configure_logging()
    settings = load_settings()
    logging.info(
        "Starting Hemera: id=%s mac=%s host_ip=%s config_dir=%s",
        settings.bridge_id, settings.mac, settings.host_ip, settings.config_dir,
    )

    cfg = Config(settings.config_dir)
    cfg.load_config(default_config(settings.bridge_id, settings.mac, settings.host_ip))
    cfg.yaml_config["config"]["mqtt"] = {
        "host": settings.mqtt_host, "port": settings.mqtt_port,
        "user": settings.mqtt_user, "password": settings.mqtt_password,
        "base_topic": settings.mqtt_base_topic,
    }

    cert_path = ensure_certificate(settings.config_dir, settings.mac)

    stop_event = asyncio.Event()

    async def _on_entertainment_start(group, owner: str) -> None:
        # hemera.services.entertainment (DTLS/HueStream) is wired in here in a later
        # project-plan step; for now the resource's `stream.active` flag is the only
        # observable effect, which is enough for the Hue app / Sync app to see the
        # area as "active" and for the two API surfaces to agree on state.
        logging.info("Entertainment area %s (%s) started by %s — no streaming engine wired up yet", group.name, group.id_v1, owner)

    async def _on_entertainment_stop(group) -> None:
        logging.info("Entertainment area %s (%s) stopped", group.name, group.id_v1)

    hue_v1 = HueV1Api(cfg)
    hue_v1.set_entertainment_callbacks(_on_entertainment_start, _on_entertainment_stop)
    v1_app = web.Application()
    hue_v1.register_routes(v1_app)
    v1_runner = web.AppRunner(v1_app)
    await v1_runner.setup()
    v1_site = web.TCPSite(v1_runner, settings.bind_ip, settings.http_port)
    await v1_site.start()
    logging.info("Hue v1 API listening on %s:%d", settings.bind_ip, settings.http_port)

    hue_v2 = HueV2Api(cfg)
    hue_v2.set_entertainment_callbacks(_on_entertainment_start, _on_entertainment_stop)
    v2_app = web.Application()
    hue_v2.register_routes(v2_app)
    v2_app.router.add_get("/eventstream/clip/v2", stream_v2_events)
    v2_runner = web.AppRunner(v2_app)
    await v2_runner.setup()
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(cert_path)  # key + cert concatenated by ensure_certificate()
    v2_site = web.TCPSite(v2_runner, settings.bind_ip, settings.https_port, ssl_context=ssl_context)
    await v2_site.start()
    logging.info("Hue v2/CLIP API listening on %s:%d (https)", settings.bind_ip, settings.https_port)

    eventstream_trim_task = asyncio.create_task(trim_eventstream_forever(stop_event), name="eventstream-trim")

    mdns = MdnsAdvertiser(settings.bridge_id, settings.host_ip, settings.http_port)
    await mdns.start()

    mqtt_client = MqttClient(
        cfg, settings.mqtt_host, settings.mqtt_port, settings.mqtt_user, settings.mqtt_password, settings.mqtt_base_topic
    )
    mqtt_client.start()

    save_task = asyncio.create_task(_periodic_config_save(cfg, stop_event), name="config-autosave")

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            with_handler = lambda: stop_event.set()  # noqa: E731
            try:
                loop.add_signal_handler(sig, with_handler)
            except NotImplementedError:
                pass  # Windows: Ctrl+C still raises KeyboardInterrupt below

    # Re-arm the link button without a restart: `kill -USR1 <pid>` (Linux only).
    sigusr1 = getattr(signal, "SIGUSR1", None)
    if sigusr1 is not None:
        try:
            loop.add_signal_handler(sigusr1, hue_v1.arm_link_button)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        logging.info("Shutting down")
        stop_event.set()
        save_task.cancel()
        eventstream_trim_task.cancel()
        await mqtt_client.stop()
        await mdns.stop()
        await v1_runner.cleanup()
        await v2_runner.cleanup()
        cfg.save_config()


def main() -> None:
    if sys.platform == "win32":
        # zeroconf (mDNS) needs add_reader/add_writer, which Windows's default
        # ProactorEventLoop doesn't implement — only relevant for local dev;
        # the Linux deployment target's default loop supports this natively.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
