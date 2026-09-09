"""Entrypoint: load config, start the v1 + v2 HTTP(S) APIs, mDNS/SSDP
advertisement, the Zigbee2MQTT client, and the Hue Entertainment
(DTLS/HueStream) engine — the full set the Hue app and the Hue Sync Box
need to discover, pair with, control, and stream to Zigbee2MQTT lights.
"""

from __future__ import annotations

import asyncio
import os
import ssl
import signal
import sys

from aiohttp import web

from hemera.api.admin.routes import AdminApi
from hemera.api.v1.routes import HueV1Api
from hemera.api.v2.eventstream import stream_v2_events, trim_eventstream_forever
from hemera.api.v2.routes import HueV2Api
from hemera.config.bootstrap import ensure_certificate, load_settings
from hemera.config.handler import Config, default_config
from hemera.logging_setup import configure_logging, get_logger
from hemera.services.entertainment.dtls_psk.server import DTLSPSKServer
from hemera.services.entertainment.engine import EntertainmentEngine
from hemera.services.mdns import MdnsAdvertiser
from hemera.services.mqtt_client import MqttClient
from hemera.services.ssdp import SsdpService

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
    is_first_run = not os.path.exists(cfg._config_path("config"))
    cfg.load_config(default_config(settings.bridge_id, settings.mac, settings.host_ip))
    if is_first_run:
        # Seed from the add-on options / env vars on first boot only. Once
        # persisted, the admin panel is the source of truth for MQTT settings —
        # otherwise every restart would silently discard a change made there.
        cfg.yaml_config["config"]["mqtt"] = {
            "host": settings.mqtt_host, "port": settings.mqtt_port,
            "user": settings.mqtt_user, "password": settings.mqtt_password,
            "base_topic": settings.mqtt_base_topic,
        }
        cfg.mark_dirty("config")
    mqtt_cfg = cfg.yaml_config["config"]["mqtt"]

    cert_path = ensure_certificate(settings.config_dir, settings.mac)

    stop_event = asyncio.Event()

    mqtt_client = MqttClient(
        cfg, mqtt_cfg["host"], mqtt_cfg["port"], mqtt_cfg["user"], mqtt_cfg["password"], mqtt_cfg["base_topic"]
    )
    mqtt_client.start()

    engine = EntertainmentEngine(mqtt_client.publish, target_fps=settings.entertainment_fps)

    def _psk_lookup(identity: str) -> bytes | None:
        user = cfg.yaml_config["apiUsers"].get(identity)
        return bytes.fromhex(user.client_key) if user is not None else None

    dtls_server = DTLSPSKServer(
        host=settings.bind_ip,
        port=settings.entertainment_port,
        psk_callback=_psk_lookup,
        frame_callback=engine.handle_frame,
    )

    async def _on_entertainment_start(group, owner: str) -> None:
        await engine.start_session(group)

    async def _on_entertainment_stop(group) -> None:
        await engine.stop_session()

    hue_v1 = HueV1Api(cfg)
    hue_v1.set_entertainment_callbacks(_on_entertainment_start, _on_entertainment_stop)
    v1_app = web.Application()
    hue_v1.register_routes(v1_app)
    v1_runner = web.AppRunner(v1_app)
    await v1_runner.setup()
    v1_site = web.TCPSite(v1_runner, settings.bind_ip, settings.http_port)
    await v1_site.start()
    logging.info("Hue v1 API listening on %s:%d", settings.bind_ip, settings.http_port)

    admin_api = AdminApi(cfg, mqtt_client, hue_v1)
    admin_app = web.Application()
    admin_api.register_routes(admin_app)
    admin_runner = web.AppRunner(admin_app)
    await admin_runner.setup()
    admin_site = web.TCPSite(admin_runner, settings.bind_ip, settings.admin_port)
    await admin_site.start()
    logging.info("Admin panel listening on %s:%d", settings.bind_ip, settings.admin_port)

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

    ssdp = SsdpService(settings.host_ip, settings.http_port, settings.mac, settings.bridge_id)
    await ssdp.start()

    try:
        await dtls_server.async_start()
        logging.info("Hue Entertainment (DTLS) listening on %s:%d", settings.bind_ip, settings.entertainment_port)
    except OSError as exc:
        # Missing OpenSSL 3.x runtime (e.g. no `openssl`/`libssl3` package) or the
        # port is taken — the rest of the bridge (pairing, lights, groups, scenes)
        # keeps working; only Hue Entertainment streaming is unavailable.
        logging.error("Hue Entertainment (DTLS) failed to start — streaming will not work: %s", exc)

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
        await engine.stop_session()
        await dtls_server.async_stop()
        await mqtt_client.stop()
        await ssdp.stop()
        await mdns.stop()
        await v1_runner.cleanup()
        await v2_runner.cleanup()
        await admin_runner.cleanup()
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
