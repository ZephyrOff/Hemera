"""First-run bootstrap: settings from environment, host identity, and the
self-signed HTTPS certificate the CLIP v2 API is served over.

Cert generation deliberately does NOT shell out to the ``openssl`` CLI (as
diyHue's ``genCert.sh`` does) — generated in pure Python with the
``cryptography`` package instead, so it works identically on the Linux
deployment target and on a Windows dev machine.
"""

from __future__ import annotations

import datetime
import ipaddress
import os
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
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str
    mqtt_base_topic: str
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
        mqtt_host=_env("HEMERA_MQTT_HOST", "127.0.0.1"),
        mqtt_port=_env_int("HEMERA_MQTT_PORT", 1883),
        mqtt_user=_env("HEMERA_MQTT_USER", ""),
        mqtt_password=_env("HEMERA_MQTT_PASSWORD", ""),
        mqtt_base_topic=_env("HEMERA_MQTT_BASE_TOPIC", "zigbee2mqtt"),
        log_level=_env("HEMERA_LOG_LEVEL", "INFO"),
    )


def _cert_is_up_to_date(cert_path: str, host_ip: str) -> bool:
    """True if the existing cert.pem already carries a SAN matching host_ip
    AND an ExtendedKeyUsage(serverAuth) extension — used to auto-regenerate
    certs from before either fix without requiring the user to manually
    delete /data/cert.pem. Bump what this checks whenever ensure_certificate()
    gains another extension that existing installs need to pick up."""
    try:
        with open(cert_path, "rb") as fp:
            cert = x509.load_pem_x509_certificate(fp.read())
        san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        try:
            target: object = ipaddress.ip_address(host_ip)
            has_san = target in san_ext.get_values_for_type(x509.IPAddress)
        except ValueError:
            has_san = host_ip in san_ext.get_values_for_type(x509.DNSName)
        eku_ext = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        has_eku = x509.oid.ExtendedKeyUsageOID.SERVER_AUTH in eku_ext
        return has_san and has_eku
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False


def ensure_certificate(config_dir: str, mac: str, host_ip: str) -> str:
    """Return the path to config_dir/cert.pem, generating a self-signed EC
    P-256 cert (key+cert concatenated, as aiohttp's ssl_context expects) on
    first run. Mirrors diyHue's genCert.sh subject convention (CN=<mac>).

    Includes a Subject Alternative Name for `host_ip` (modern TLS stacks
    ignore the CN for hostname/IP verification per RFC 6125) and the same
    basicConstraints/keyUsage/extendedKeyUsage(serverAuth) extensions as
    diyHue's genCert.sh/openssl.conf — a cert missing these can fail TLS
    validation silently, before any HTTP request is even sent, which from our
    side looks identical to the client never having tried at all.
    """
    cert_path = os.path.join(config_dir, "cert.pem")
    if os.path.isfile(cert_path):
        if _cert_is_up_to_date(cert_path, host_ip):
            return cert_path
        logging.info("Existing certificate is outdated for %s — regenerating", host_ip)
    else:
        logging.info("No certificate found — generating a self-signed one at %s", cert_path)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "NL"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Philips Hue"),
        x509.NameAttribute(NameOID.COMMON_NAME, mac),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        san = x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host_ip))])
    except ValueError:
        san = x509.SubjectAlternativeName([x509.DNSName(host_ip)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(san, critical=False)
        # Matches diyHue's genCert.sh/openssl.conf [usr_cert] section (proven
        # to pair with the real Hue app) — a cert with no declared purpose
        # can be rejected by strict TLS clients as not valid for server auth,
        # again failing during the handshake before any HTTP request is sent.
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True, content_commitment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
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
