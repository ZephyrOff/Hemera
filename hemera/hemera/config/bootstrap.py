"""First-run bootstrap: settings from environment, host identity, and the
self-signed HTTPS certificate the CLIP v2 API is served over.

Cert generation deliberately does NOT shell out to the ``openssl`` CLI (as
diyHue's ``genCert.sh`` does) — generated in pure Python with the
``cryptography`` package instead, so it works identically on the Linux
deployment target and on a Windows dev machine.
"""

from __future__ import annotations

import datetime
import os
import time
import uuid
from dataclasses import dataclass, field

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from hemera.logging_setup import get_logger

logging = get_logger(__name__)


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def apply_timezone(tz: str) -> None:
    """Apply an IANA timezone to this process's own idea of local time.

    Shared by main.py (on every boot, for whatever's already persisted) and
    the v1 PUT /api/{user}/config and admin-panel handlers (whenever a
    client sets a new one) — matches diyHue's flaskUI/restful.py /
    configManager/configHandler.py exactly, ``time.tzset()`` re-reads
    ``os.environ['TZ']`` into the C library's local-time state so
    ``datetime.now()`` reflects it immediately, without a restart.
    ``tzset`` doesn't exist on Windows (dev-only; the deployment target is
    Linux), so it's a deliberate no-op there.
    """
    os.environ["TZ"] = tz
    if hasattr(time, "tzset"):
        time.tzset()


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


@dataclass
class Settings:
    config_dir: str
    bind_ip: str
    host_ip: str
    http_port: int
    https_port: int
    entertainment_port: int
    entertainment_fps: int
    admin_port: int
    mac: str
    bridge_id: str
    timezone: str
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str
    mqtt_base_topic: str
    ha_url: str
    ha_token: str
    log_level: str = field(default="INFO")


def get_host_ip() -> str:
    """Best-effort LAN IP to advertise to Hue clients (mDNS/description.xml/config)."""
    import socket

    explicit = _env("HEMERA_HOST_IP")
    if explicit:
        return explicit
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def get_mac() -> str:
    """Colon-separated MAC, cross-platform (``uuid.getnode()`` works on Windows and Linux
    alike — unlike diyHue's approach of shelling out to ``/sys/class/net/*/address``)."""
    explicit = _env("HEMERA_MAC")
    if explicit:
        return explicit.replace("-", ":").lower()
    node = uuid.getnode()
    return ":".join(f"{(node >> shift) & 0xFF:02x}" for shift in range(40, -8, -8))


def load_settings() -> Settings:
    from hemera.config.handler import make_bridge_id

    mac = get_mac()
    config_dir = _env("HEMERA_CONFIG_DIR", "./config")
    host_ip = get_host_ip()
    return Settings(
        config_dir=config_dir,
        bind_ip=_env("HEMERA_BIND_IP", "0.0.0.0"),
        host_ip=host_ip,
        http_port=_env_int("HEMERA_HTTP_PORT", 80),
        https_port=_env_int("HEMERA_HTTPS_PORT", 443),
        entertainment_port=_env_int("HEMERA_ENTERTAINMENT_PORT", 2100),
        entertainment_fps=_env_int("HEMERA_ENTERTAINMENT_FPS", 15),
        admin_port=_env_int("HEMERA_ADMIN_PORT", 8099),
        mac=mac,
        bridge_id=_env("HEMERA_BRIDGE_ID") or make_bridge_id(mac),
        timezone=_env("HEMERA_TIMEZONE", ""),
        mqtt_host=_env("HEMERA_MQTT_HOST", "127.0.0.1"),
        mqtt_port=_env_int("HEMERA_MQTT_PORT", 1883),
        mqtt_user=_env("HEMERA_MQTT_USER", ""),
        mqtt_password=_env("HEMERA_MQTT_PASSWORD", ""),
        mqtt_base_topic=_env("HEMERA_MQTT_BASE_TOPIC", "zigbee2mqtt"),
        # Home Assistant's own Supervisor proxies Core's REST API at this
        # fixed internal address for any add-on with `homeassistant_api:
        # true` in config.yaml, authenticated with that same add-on's own
        # SUPERVISOR_TOKEN (auto-injected into every add-on's environment) —
        # no separate credentials to configure on a real install. Outside
        # the add-on (local dev), HEMERA_HA_URL/HEMERA_HA_TOKEN (a manually
        # created long-lived access token) stand in for both.
        ha_url=_env("HEMERA_HA_URL", "http://supervisor/core/api"),
        ha_token=_env("HEMERA_HA_TOKEN") or _env("SUPERVISOR_TOKEN", ""),
        log_level=_env("HEMERA_LOG_LEVEL", "INFO"),
    )


# Matches Bifrost's server/certificate.rs exactly (proven to pair with the
# real Hue app) — its own doc comment: "Great care has been taken to match
# real certificates... Only known differences: EKU critical flag set (real
# certs don't), and real certs are signed by a root-bridge CA cert (this is
# self-signed) — both noted as benign." Real bridges pin these exact bounds
# rather than a relative validity window.
_NOT_BEFORE = datetime.datetime(2017, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
_NOT_AFTER = datetime.datetime(2038, 1, 19, 3, 14, 7, tzinfo=datetime.timezone.utc)


def _bridge_id_raw(mac: str) -> bytes:
    """8-byte EUI64-style expansion of a 6-byte MAC (0xFFFE inserted at the
    midpoint) — the raw form of make_bridge_id(), used as the cert's serial
    number to match Bifrost's SerialNumber::new(&hue::bridge_id_raw(mac))."""
    mac_bytes = bytes.fromhex(mac.replace(":", ""))
    return mac_bytes[:3] + b"\xff\xfe" + mac_bytes[3:]


def _cert_is_up_to_date(cert_path: str, bridge_id: str) -> bool:
    """True if the existing cert.pem already has CN=bridge_id and an
    AuthorityKeyIdentifier extension — used to auto-regenerate certs
    generated by older versions of this add-on (which used CN=mac and a SAN
    extension, neither of which real Hue bridge certs — nor Bifrost's,
    proven to work — actually have) without requiring the user to manually
    delete /data/cert.pem."""
    try:
        with open(cert_path, "rb") as fp:
            cert = x509.load_pem_x509_certificate(fp.read())
        cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if not cn_attrs or cn_attrs[0].value != bridge_id:
            return False
        cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
        return True
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False


def ensure_certificate(config_dir: str, mac: str, host_ip: str) -> str:
    """Return the path to config_dir/cert.pem, generating a self-signed EC
    P-256 cert (key+cert concatenated, as aiohttp's ssl_context expects) on
    first run.

    Subject/extensions rewritten to match Bifrost's server/certificate.rs
    (proven to pair with the real Hue app) instead of diyHue's genCert.sh:
    CN is the bridge_id (not the mac — real bridges use bridge_id here),
    there is deliberately NO Subject Alternative Name (real bridge certs
    don't carry one either — the official app apparently doesn't require
    hostname/IP verification for local bridge connections, and adding one in
    an earlier version of this add-on did not fix pairing), and the validity
    window is the fixed 2017-01-01..2038-01-19T03:14:07 range real bridges
    use rather than a relative one.
    """
    from hemera.config.handler import make_bridge_id

    bridge_id = make_bridge_id(mac)
    cert_path = os.path.join(config_dir, "cert.pem")
    if os.path.isfile(cert_path):
        if _cert_is_up_to_date(cert_path, bridge_id):
            return cert_path
        logging.info("Existing certificate is outdated for bridge_id=%s — regenerating", bridge_id)
    else:
        logging.info("No certificate found — generating a self-signed one at %s", cert_path)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, bridge_id),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Philips Hue"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "NL"),
    ])
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(int.from_bytes(_bridge_id_raw(mac), "big"))
        .not_valid_before(_NOT_BEFORE)
        .not_valid_after(_NOT_AFTER)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=False, content_commitment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(ski, critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ski),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    with open(cert_path, "wb") as fp:
        fp.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        fp.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path
