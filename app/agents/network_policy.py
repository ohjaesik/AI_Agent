"""Network target validation shared by policy-aware external clients."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def assert_network_target_allowed(url: str, policy: str) -> None:
    """Reject unsupported schemes and private/link-local targets before fetching."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only HTTP(S) URLs with a hostname are allowed.")
    if policy == "none":
        raise PermissionError("This Agent is not allowed to make network requests.")
    if policy not in {"official_sources_only", "delegated_only", "restricted", "any"}:
        raise PermissionError(f"Unsupported network policy: {policy}")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed.")
    if policy == "official_sources_only" and parsed.scheme != "https":
        raise PermissionError("Official source requests require HTTPS.")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as exc:
        raise ValueError(f"Unable to resolve network target: {parsed.hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise PermissionError(f"Private or non-public network target is not allowed: {parsed.hostname}")
