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
from hemera.config.bootstrap import apply_timezone, ensure_certificate, load_settings
from hemera.config.handler import Config, default_config
from hemera.logging_setup import configure_logging, get_logger
from hemera.services.entertainment.dtls_psk.server import DTLSPSKServer
from hemera.services.entertainment.engine import EntertainmentEngine
from hemera.services.ha_client import HaClient
from hemera.services.mdns import MdnsAdvertiser
from hemera.services.mqtt_client import MqttClient
from hemera.services.ssdp import SsdpService
from hemera.services.update_check import check_for_update

logging = get_logger(__name__)

_CONFIG_SAVE_INTERVAL_S = 5.0
_UPDATE_CHECK_INTERVAL_S = 24 * 60 * 60.0


async def _periodic_config_save(cfg: Config, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=_CONFIG_SAVE_INTERVAL_S)
        except TimeoutError:
            pass
        cfg.save_dirty_if_needed()


async def _periodic_update_check(cfg: Config, stop: asyncio.Event) -> None:
    # Matches diyHue's own cadence (services/scheduler.py rechecks daily) —
    # see hemera.services.update_check for why this needs to happen at all.
    while not stop.is_set():
        await check_for_update(cfg)
        try:
            await asyncio.wait_for(stop.wait(), timeout=_UPDATE_CHECK_INTERVAL_S)
        except TimeoutError:
            pass


async def async_main() -> None:
    configure_logging()
    settings = load_settings()
    logging.info(
        "Starting Hemera: id=%s mac=%s host_ip=%s config_dir=%s",
        settings.bridge_id, settings.mac, settings.host_ip, settings.config_dir,
    )

    cfg = Config(settings.config_dir)
    is_first_run = not os.path.exists(cfg._config_path("config"))
    defaults = default_config(settings.bridge_id, settings.mac, settings.host_ip)
    cfg.load_config(defaults)
    # apiversion/swversion are software identity, not user config — like mac
    # below, they have no admin-panel-owned competing source of truth, so the
    # current build's values always win. An install that paired against an
    # older Hemera version would otherwise keep reporting that old version
    # forever (load_config() only applies `defaults` on a missing config
    # file, never merges it into an existing one) — and the Hue app compares
    # the reported version against the latest real firmware it knows about,
    # nagging "update required" (with no update actually possible) once it
    # looks outdated enough.
    if (
        cfg.yaml_config["config"].get("apiversion") != defaults["apiversion"]
        or cfg.yaml_config["config"].get("swversion") != defaults["swversion"]
    ):
        logging.info(
            "Updating reported apiversion/swversion to %s/%s (was %s/%s)",
            defaults["apiversion"], defaults["swversion"],
            cfg.yaml_config["config"].get("apiversion"), cfg.yaml_config["config"].get("swversion"),
        )
        cfg.yaml_config["config"]["apiversion"] = defaults["apiversion"]
        cfg.yaml_config["config"]["swversion"] = defaults["swversion"]
        cfg.mark_dirty("config")
    if is_first_run:
        # Seed from the add-on options / env vars on first boot only. Once
        # persisted, the admin panel is the source of truth for MQTT settings —
        # otherwise every restart would silently discard a change made there.
        cfg.yaml_config["config"]["mqtt"] = {
            "host": settings.mqtt_host, "port": settings.mqtt_port,
            "user": settings.mqtt_user, "password": settings.mqtt_password,
            "base_topic": settings.mqtt_base_topic,
        }
        # Same reasoning as MQTT above: seed the add-on's `timezone` option
        # (itself defaulted to Home Assistant's own configured timezone by
        # the rootfs run script, unless overridden) once, then let whichever
        # value the Hue app itself PUTs to /api/{user}/config during
        # onboarding take over — re-forcing this every boot would fight with
        # the app's own setting and reintroduce the same "configure your
        # bridge's timezone" nag it was meant to fix.
        if settings.timezone:
            cfg.yaml_config["config"]["timezone"] = settings.timezone
        cfg.mark_dirty("config")
    # Unlike MQTT (owned by the admin panel once set), `mac` has no such
    # competing source of truth — it's an add-on option only, so an
    # explicitly configured value always applies, every boot, correcting a
    # bad first-run auto-detection without requiring the user to wipe /data.
    # A wrong MAC here breaks both the TLS cert and the bridgeid the official
    # Hue app uses to authenticate the bridge (see the `mac` option's docs).
    if os.environ.get("HEMERA_MAC") and cfg.yaml_config["config"].get("mac") != settings.mac:
        logging.info("Applying explicitly configured mac=%s (overrides persisted value)", settings.mac)
        cfg.yaml_config["config"]["mac"] = settings.mac
        cfg.yaml_config["config"]["bridgeid"] = settings.bridge_id
        cfg.mark_dirty("config")
    # Apply whatever timezone ended up in config (seeded above, previously
    # persisted, or set by the Hue app via PUT /api/{user}/config on a prior
    # run) to this process every boot — matches diyHue's configManager
    # (Apache-2.0): the "localtime" field in /api/config, and anything else
    # relying on the system local time, otherwise stays on the container's
    # default TZ regardless of what the config file says.
    configured_tz = cfg.yaml_config["config"].get("timezone")
    if configured_tz:
        apply_timezone(configured_tz)
    mqtt_cfg = cfg.yaml_config["config"]["mqtt"]

    cert_path = ensure_certificate(settings.config_dir, settings.mac, settings.host_ip)

    stop_event = asyncio.Event()

    mqtt_client = MqttClient(
        cfg, mqtt_cfg["host"], mqtt_cfg["port"], mqtt_cfg["user"], mqtt_cfg["password"], mqtt_cfg["base_topic"]
    )
    mqtt_client.start()

    ha_client = HaClient(cfg, settings.ha_url, settings.ha_token)
    ha_client.start()

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

    admin_api = AdminApi(cfg, mqtt_client, ha_client, hue_v1)
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
    # A real Hue Bridge serves both API generations on both ports — the Hue
    # app has been observed (see log analysis) probing HTTPS first, getting a
    # 404 against a v2-only server, then falling back to HTTP for /api/config
    # and never attempting pairing at all. Mounting v1 here too, on the same
    # `hue_v1` instance so link-button/user state stays shared, matches real
    # bridge behaviour and lets pairing succeed regardless of which port the
    # client tries.
    hue_v1.register_routes(v2_app)
    hue_v2.register_routes(v2_app)
    v2_app.router.add_get("/eventstream/clip/v2", stream_v2_events)
    v2_runner = web.AppRunner(v2_app)
    await v2_runner.setup()
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(cert_path)  # key + cert concatenated by ensure_certificate()
    # Matches Bifrost's server/http.rs (proven to pair with the real Hue app):
    # it explicitly builds an OpenSSL `mozilla_intermediate_v5`-equivalent
    # profile rather than the newer `mozilla_modern_v5` default, with the
    # comment "That protocol version [TLS 1.3-only] is too new for some
    # important clients, like Hue Sync for PC" — i.e. the fix is BROADER
    # compatibility, not the narrower single-cipher/TLS-1.2-only restriction
    # this add-on used previously (copied from diyHue, and confirmed by the
    # user not to fix pairing). Python's own default TLS 1.2 cipher list
    # already matches Mozilla "intermediate" closely enough; only the
    # minimum version and ALPN need to be set explicitly.
    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
    # Bifrost's ALPN callback offers "h2" and "http/1.1" — but unlike its Rust
    # hyper-based server, aiohttp only ever speaks HTTP/1.1 on the wire, so
    # advertising "h2" here would let a client negotiate a protocol we can't
    # actually serve. Offering only http/1.1 still satisfies clients that
    # refuse to complete the handshake without ALPN participation at all.
    ssl_context.set_alpn_protocols(["http/1.1"])
    v2_site = web.TCPSite(v2_runner, settings.bind_ip, settings.https_port, ssl_context=ssl_context)
    await v2_site.start()
    logging.info("Hue v2/CLIP API listening on %s:%d (https)", settings.bind_ip, settings.https_port)

    eventstream_trim_task = asyncio.create_task(trim_eventstream_forever(stop_event), name="eventstream-trim")

    # Port 443, not 80: matches Bifrost's server/mdns.rs (proven to work with
    # the real Hue app) — mDNS specifically advertises the HTTPS port, unlike
    # SSDP/UPnP which stays on 80 (see SsdpService below and Bifrost's own
    # server/ssdp.rs, which hardcodes port 80 there).
    mdns = MdnsAdvertiser(settings.bridge_id, settings.host_ip, settings.https_port)
    await mdns.start()

    ssdp = SsdpService(
        settings.host_ip, settings.http_port, settings.mac, settings.bridge_id,
        cfg.yaml_config["config"]["apiversion"],
    )
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
    update_check_task = asyncio.create_task(_periodic_update_check(cfg, stop_event), name="update-check")

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
        update_check_task.cancel()
        eventstream_trim_task.cancel()
        await engine.stop_session()
        await dtls_server.async_stop()
        await mqtt_client.stop()
        await ha_client.stop()
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
