from urllib.parse import urlparse, urlunparse
import ipaddress
import socket


class NetworkSecurityError(ValueError):
    pass


def validate_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise NetworkSecurityError("Only HTTP and HTTPS URLs are supported")
    if not parsed.hostname:
        raise NetworkSecurityError("URL must include a hostname")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost"} or hostname.endswith(".localhost"):
        raise NetworkSecurityError("Localhost URLs are not allowed")

    try:
        addresses = socket.getaddrinfo(hostname, parsed.port or _default_port(parsed.scheme))
    except socket.gaierror as exc:
        raise NetworkSecurityError("URL hostname could not be resolved") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if _is_blocked_ip(ip):
            raise NetworkSecurityError("Private, local, and reserved network URLs are not allowed")


def strip_url_credentials(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.username and not parsed.password:
        return url
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def validate_huggingface_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "huggingface.co":
        raise NetworkSecurityError("Only HTTPS Hugging Face downloads are allowed")


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )
