"""Safe, policy-gated public attachment acquisition.

This module fetches public HTTPS documents only. It does not authenticate,
bypass access controls, solve challenges, or submit applications. Callers must
supply an explicit non-empty host allowlist and an affirmative policy decision.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import socket
import ssl
import time
import urllib.error
import urllib.robotparser
from dataclasses import dataclass
from email.message import Message
from typing import Callable
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener


class AttachmentFetchError(RuntimeError):
    """Expected, sanitized attachment acquisition failure."""


@dataclass(frozen=True, slots=True)
class AttachmentPolicy:
    allowed_hosts: frozenset[str]
    policy_allows: bool
    robots_required: bool = True
    user_agent: str = "recruit-match-attachment-inspector/1.0"


@dataclass(frozen=True, slots=True)
class AttachmentLimits:
    timeout_seconds: float = 10.0
    max_bytes: int = 20 * 1024 * 1024
    robots_max_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("TIMEOUT_MUST_BE_POSITIVE")
        if self.max_bytes <= 0 or self.robots_max_bytes <= 0:
            raise ValueError("BYTE_LIMIT_MUST_BE_POSITIVE")


@dataclass(frozen=True, slots=True)
class AttachmentReceipt:
    source_url: str
    final_url: str
    retrieved_at_epoch: float
    content_type: str
    byte_size: int
    sha256: str
    media_kind: str
    content: bytes


Resolver = Callable[[str, int], list[tuple]]


def _default_resolver(host: str, port: int) -> list[tuple]:
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return (
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


class PublicURLPolicy:
    def __init__(
        self,
        allowed_hosts: frozenset[str],
        resolver: Resolver = _default_resolver,
    ) -> None:
        self.allowed_hosts = frozenset(host.lower().rstrip(".") for host in allowed_hosts)
        self.resolver = resolver

    def public_addresses(self, host: str, port: int = 443) -> tuple[str, ...]:
        """Resolve and validate addresses that the transport may connect to.

        The returned numeric IPs are passed directly to socket.create_connection;
        the hostname is retained separately for HTTP Host, TLS SNI and certificate
        hostname verification.
        """
        normalized = host.strip("[]").lower().rstrip(".")
        if normalized == "localhost" or normalized.endswith(".localhost") or normalized.endswith(".local"):
            raise AttachmentFetchError("NONPUBLIC_HOST_FORBIDDEN")
        try:
            literal = ipaddress.ip_address(normalized)
        except ValueError:
            literal = None
        if literal is not None:
            if not _is_public_address(str(literal)):
                raise AttachmentFetchError("NONPUBLIC_ADDRESS_FORBIDDEN")
            return (str(literal),)
        try:
            answers = self.resolver(normalized, port)
        except (OSError, socket.gaierror) as exc:
            raise AttachmentFetchError("DNS_RESOLUTION_FAILED") from exc
        addresses = {
            answer[4][0].split("%", 1)[0]
            for answer in answers
            if answer and len(answer) > 4 and isinstance(answer[4][0], str)
        }
        if not addresses:
            raise AttachmentFetchError("DNS_NO_ADDRESSES")
        if any(not _is_public_address(address) for address in addresses):
            raise AttachmentFetchError("NONPUBLIC_DNS_TARGET_FORBIDDEN")
        return tuple(sorted(addresses, key=lambda item: (ipaddress.ip_address(item).version, item)))

    def validate(self, url: str) -> None:
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError as exc:
            raise AttachmentFetchError("MALFORMED_URL") from exc
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise AttachmentFetchError("HTTPS_URL_REQUIRED")
        if parsed.username is not None or parsed.password is not None:
            raise AttachmentFetchError("URL_CREDENTIALS_FORBIDDEN")
        if port not in (None, 443):
            raise AttachmentFetchError("NONSTANDARD_PORT_FORBIDDEN")
        host = parsed.hostname.lower().rstrip(".")
        if not self.allowed_hosts or host not in self.allowed_hosts:
            raise AttachmentFetchError("HOST_NOT_ALLOWLISTED")
        self.public_addresses(host, port or 443)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a validated numeric IP while verifying TLS for the URL host."""

    def __init__(self, host: str, *, policy: PublicURLPolicy, **kwargs) -> None:
        self._public_url_policy = policy
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        if self._tunnel_host:
            raise OSError("HTTPS_PROXY_TUNNEL_DISABLED")
        addresses = self._public_url_policy.public_addresses(self.host, self.port or 443)
        last_error: OSError | None = None
        for address in addresses:
            raw_socket = None
            try:
                raw_socket = socket.create_connection(
                    (address, self.port or 443),
                    self.timeout,
                    self.source_address,
                )
                # Keep self.host as the original DNS name: this preserves TLS SNI
                # and certificate hostname verification despite the pinned socket IP.
                self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
                return
            except ssl.SSLError:
                if raw_socket is not None:
                    raw_socket.close()
                raise
            except OSError as exc:
                last_error = exc
                if raw_socket is not None:
                    raw_socket.close()
        if last_error is not None:
            raise last_error
        raise OSError("NO_VALIDATED_PUBLIC_ADDRESS")


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, policy: PublicURLPolicy) -> None:
        super().__init__(context=ssl.create_default_context())
        self.policy = policy

    def https_open(self, req):
        connection_factory = lambda host, **kwargs: _PinnedHTTPSConnection(
            host, policy=self.policy, **kwargs
        )
        return self.do_open(
            connection_factory,
            req,
            context=self._context,
            check_hostname=self._check_hostname,
        )


class _PolicyRedirectHandler(HTTPRedirectHandler):
    def __init__(self, policy: PublicURLPolicy, max_redirects: int = 5) -> None:
        super().__init__()
        self.policy = policy
        self.max_redirects = max_redirects

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.policy.validate(newurl)
        redirects = getattr(req, "_recruit_match_redirects", 0) + 1
        if redirects > self.max_redirects:
            raise AttachmentFetchError("REDIRECT_LIMIT_EXCEEDED")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected._recruit_match_redirects = redirects
        return redirected


def _read_bounded(response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(64 * 1024, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise AttachmentFetchError("BYTE_LIMIT_EXCEEDED")
        chunks.append(chunk)


def _classify_content(content_type: str, body: bytes) -> str:
    normalized = content_type.lower().split(";", 1)[0].strip()
    if body.startswith(b"%PDF-"):
        if normalized not in ("application/pdf", "application/octet-stream", "binary/octet-stream"):
            raise AttachmentFetchError("CONTENT_TYPE_MAGIC_MISMATCH")
        return "pdf"
    if body.startswith(b"PK\x03\x04"):
        allowed_zip_types = {
            "application/zip",
            "application/octet-stream",
            "binary/octet-stream",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        if normalized not in allowed_zip_types:
            raise AttachmentFetchError("CONTENT_TYPE_MAGIC_MISMATCH")
        return "zip-container"
    raise AttachmentFetchError("UNSUPPORTED_OR_UNVERIFIED_CONTENT")


class SafeAttachmentFetcher:
    def __init__(
        self,
        policy: AttachmentPolicy,
        limits: AttachmentLimits = AttachmentLimits(),
        *,
        resolver: Resolver = _default_resolver,
        opener=None,
    ) -> None:
        self.policy = policy
        self.limits = limits
        self.url_policy = PublicURLPolicy(policy.allowed_hosts, resolver)
        # Disable environment proxies: a proxy would resolve/connect independently
        # and bypass the numeric-IP pinning performed by _PinnedHTTPSConnection.
        self.opener = opener or build_opener(
            ProxyHandler({}),
            _PolicyRedirectHandler(self.url_policy),
            _PinnedHTTPSHandler(self.url_policy),
        )

    def _open(self, url: str, accept: str):
        request = Request(
            url,
            headers={"User-Agent": self.policy.user_agent, "Accept": accept},
            method="GET",
        )
        try:
            return self.opener.open(request, timeout=self.limits.timeout_seconds)
        except AttachmentFetchError:
            raise
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise AttachmentFetchError(f"HTTP_REQUEST_FAILED:{type(exc).__name__}") from exc

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        robots_url = f"https://{parsed.netloc}/robots.txt"
        with self._open(robots_url, "text/plain") as response:
            robots_body = _read_bounded(response, self.limits.robots_max_bytes)
        parser = urllib.robotparser.RobotFileParser()
        try:
            parser.parse(robots_body.decode("utf-8", errors="replace").splitlines())
        except Exception as exc:
            raise AttachmentFetchError("ROBOTS_PARSE_FAILED") from exc
        return parser.can_fetch(self.policy.user_agent, url)

    def fetch(self, url: str) -> AttachmentReceipt:
        if not self.policy.policy_allows:
            raise AttachmentFetchError("POLICY_GATE_DENIED")
        if not self.policy.allowed_hosts:
            raise AttachmentFetchError("EMPTY_ALLOWLIST_DENIED")
        self.url_policy.validate(url)
        if self.policy.robots_required:
            parsed = urlparse(url)
            robots_url = f"https://{parsed.netloc}/robots.txt"
            self.url_policy.validate(robots_url)
            if not self._robots_allowed(url):
                raise AttachmentFetchError("ROBOTS_DENIED")

        with self._open(url, "application/pdf,application/zip,application/octet-stream") as response:
            final_url = response.geturl()
            self.url_policy.validate(final_url)
            content_type = response.headers.get_content_type()
            length = response.headers.get("Content-Length")
            if length is not None:
                try:
                    if int(length) > self.limits.max_bytes:
                        raise AttachmentFetchError("BYTE_LIMIT_EXCEEDED")
                    if int(length) < 0:
                        raise AttachmentFetchError("INVALID_CONTENT_LENGTH")
                except ValueError as exc:
                    raise AttachmentFetchError("INVALID_CONTENT_LENGTH") from exc
            body = _read_bounded(response, self.limits.max_bytes)
            media_kind = _classify_content(content_type, body)

        return AttachmentReceipt(
            source_url=url,
            final_url=final_url,
            retrieved_at_epoch=time.time(),
            content_type=content_type,
            byte_size=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            media_kind=media_kind,
            content=body,
        )
