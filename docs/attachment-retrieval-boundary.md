# Attachment Retrieval Boundary

Status: **source-level safety boundary implemented; production network safety not fully verified**

## Current implementation

`src/recruit_match/attachments.py` provides:

- HTTPS-only URLs, exact non-empty host allowlisting, credential and nonstandard-port rejection.
- DNS preflight that rejects empty resolution and non-public/reserved/local addresses.
- Manual redirect policy checks through a custom urllib redirect handler.
- Explicit request timeout and bounded `robots.txt` and attachment reads.
- Content-Length and streaming byte-limit enforcement, PDF/ZIP magic checks, MIME consistency and SHA-256 receipts.
- A caller-controlled policy gate; no authentication, CAPTCHA, anti-bot, or access-control bypass.

Synthetic unit tests cover HTTPS, empty allowlists, private DNS, URL credentials, bounded reads, MIME/signature mismatches, policy-before-network behavior, and robots timeout behavior. These tests have been authored but not executed in this session.

## Important remaining security gap

The current urllib implementation validates DNS answers before making requests, but urllib subsequently resolves the hostname for its own connection. The validated IP address is **not pinned to the socket connection**. A DNS change/rebinding between preflight and connection therefore remains a risk; the current implementation must not be described as fully SSRF-resistant.

Before production use, replace or wrap the network boundary with a transport that connects only to a validated public IP while preserving TLS hostname verification and SNI. Test redirect hops, DNS changes, IPv4/IPv6 edge cases, malformed URLs, and proxy behavior. Do not enable arbitrary hosts by default.

## Other limits

- The current signature check identifies PDF and ZIP-like containers; it is not malware scanning, archive validation, parser isolation, or proof that an OOXML document is safe.
- ZIP decompression limits, archive path traversal defense, parser process isolation, and extraction timeouts remain separate requirements.
- The real robots retrieval is bounded by request timeout and response bytes, but no live third-party network tests have been run.
- This module is not connected to the end-to-end recruitment pipeline.
