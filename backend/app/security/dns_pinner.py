"""
Smart BI Agent — DNS Pinner
Architecture v3.1 | Security Layer 8 | Threat: T51

DNS Rebinding TOCTOU Attack:
    1. Attacker sets DNS for evil.com → 8.8.8.8 (passes SSRF check)
    2. DNS TTL expires
    3. Attacker changes evil.com → 169.254.169.254 (cloud metadata)
    4. Application connects using hostname → resolves to metadata service

MITIGATION (DNS Pinning):
    Resolve hostname ONCE → validate the resolved IP → use the resolved IP
    for ALL subsequent connections. The hostname is never resolved again.
    This eliminates the TOCTOU window entirely.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Optional


class DNSResolutionError(Exception):
    """Raised when DNS resolution fails."""
    pass


class DNSPinningError(Exception):
    """Raised when a resolved IP falls in a blocked range."""
    pass


# Blocked IP networks — RFC-1918, loopback, link-local, metadata, IPv6 ULA
BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    # IPv4 Private (RFC-1918)
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    # IPv4 Loopback
    ipaddress.ip_network("127.0.0.0/8"),
    # IPv4 Link-Local
    ipaddress.ip_network("169.254.0.0/16"),       # AWS/GCP/Azure metadata
    # IPv4 Special
    ipaddress.ip_network("0.0.0.0/8"),             # "This" network
    ipaddress.ip_network("100.64.0.0/10"),          # Carrier-grade NAT
    ipaddress.ip_network("192.0.0.0/24"),           # IETF Protocol Assignments
    ipaddress.ip_network("198.18.0.0/15"),          # Benchmarking
    # IPv6
    ipaddress.ip_network("::1/128"),                # Loopback
    ipaddress.ip_network("fc00::/7"),               # Unique Local (ULA)
    ipaddress.ip_network("fe80::/10"),              # Link-Local
    ipaddress.ip_network("::ffff:0:0/96"),          # IPv4-mapped IPv6
]

# Cloud metadata endpoints (explicit, in case they're not in ranges above)
BLOCKED_HOSTS: set[str] = {
    "metadata.google.internal",
    "metadata.goog",
    "169.254.169.254",
    "fd00:ec2::254",
}


@dataclass(frozen=True)
class PinnedHost:
    """
    A DNS-pinned host: the original hostname is stored alongside
    the resolved IP. All connections use resolved_ip, never hostname.
    """
    original_host: str
    resolved_ip: str
    port: Optional[int] = None

    @property
    def connection_string(self) -> str:
        """Use resolved IP for connections, never the original hostname."""
        if self.port:
            return f"{self.resolved_ip}:{self.port}"
        return self.resolved_ip


def is_ip_blocked(ip_str: str) -> bool:
    """
    Check if an IP address falls within any blocked network.

    Args:
        ip_str: IP address string (IPv4 or IPv6).

    Returns:
        True if the IP is in a blocked range.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Unparseable IPs are blocked

    for network in BLOCKED_NETWORKS:
        if ip in network:
            return True
    return False


def resolve_and_pin(host: str, port: Optional[int] = None) -> PinnedHost:
    """
    Resolve a hostname to an IP, validate it, and return a pinned result.

    This is the core of DNS pinning:
        1. Resolve hostname → IP address
        2. Check IP against blocked networks
        3. Return PinnedHost with resolved IP
        4. Caller uses resolved IP for ALL connections

    The hostname is NEVER used for connections after this function returns.

    Args:
        host: Hostname or IP address to resolve.
        port: Optional port number to include.

    Returns:
        PinnedHost with the validated, resolved IP.

    Raises:
        DNSResolutionError: If hostname cannot be resolved.
        DNSPinningError: If resolved IP is in a blocked range.
    """
    if not host or not host.strip():
        raise DNSResolutionError("Empty hostname")

    host = host.strip().lower()

    # Check explicitly blocked hostnames
    if host in BLOCKED_HOSTS:
        raise DNSPinningError(f"Hostname '{host}' is explicitly blocked (metadata endpoint)")

    # If it's already an IP address, validate directly
    try:
        ip = ipaddress.ip_address(host)
        if is_ip_blocked(str(ip)):
            raise DNSPinningError(
                f"IP address {ip} is in a blocked network range"
            )
        return PinnedHost(original_host=host, resolved_ip=str(ip), port=port)
    except ValueError:
        pass  # Not an IP, proceed with DNS resolution

    # Resolve hostname to IP
    try:
        # getaddrinfo returns all addresses; we check ALL of them
        results = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
        if not results:
            raise DNSResolutionError(f"No DNS records found for '{host}'")

        # Use the first result, but validate ALL resolved IPs
        resolved_ips: list[str] = []
        for family, _type, _proto, _canonname, sockaddr in results:
            ip_str = sockaddr[0]
            resolved_ips.append(ip_str)
            if is_ip_blocked(ip_str):
                raise DNSPinningError(
                    f"Hostname '{host}' resolves to blocked IP {ip_str}"
                )

        # Pin to the first resolved IP
        pinned_ip = resolved_ips[0]
        return PinnedHost(original_host=host, resolved_ip=pinned_ip, port=port)

    except socket.gaierror as e:
        raise DNSResolutionError(f"Cannot resolve hostname '{host}': {e}") from e
    except DNSPinningError:
        raise
    except Exception as e:
        raise DNSResolutionError(f"DNS resolution failed for '{host}': {e}") from e


def validate_host_not_blocked(host: str, port: Optional[int] = None) -> str:
    """
    Convenience function: resolve, validate, return the safe resolved IP.

    Args:
        host: Hostname or IP to validate.
        port: Optional port.

    Returns:
        The resolved IP address string (safe to connect to).

    Raises:
        DNSResolutionError: If hostname cannot be resolved.
        DNSPinningError: If resolved IP is blocked.
    """
    pinned = resolve_and_pin(host, port)
    return pinned.resolved_ip
