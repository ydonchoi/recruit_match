# Attachment Retrieval Boundary

Status: **DNS-pinned transport implemented in source; production network safety remains unverified**

## Current implementation

`src/recruit_match/attachments.py` provides:

- HTTPS-only URLs, exact non-empty host allowlisting, credential and nonstandard-port rejection.
- DNS resolution that rejects empty, malformed, private, loopback, link-local, multicast, reserved and otherwise non-public addresses.
- A custom HTTPS connection that resolves and validates addresses at connect time, opens a socket directly to a validated numeric IP, and wraps it in TLS using the original hostname for SNI and certificate hostname verification.
- Disabled environment proxy discovery for the default opener, so a proxy cannot independently resolve the destination and bypass the pinned connection.
- Manual redirect policy checks for each hop, including allowlist and public-address checks.
- Explicit request timeout and bounded `robots.txt` and attachment reads.
- Content-Length and streaming byte-limit enforcement, PDF/ZIP magic checks, MIME consistency and SHA-256 receipts.
- A caller-controlled policy gate; no authentication, CAPTCHA, anti-bot, or access-control bypass.

Synthetic unit tests now cover the pinned numeric socket target, preservation of the original TLS hostname, re-resolution before connect, rejection of a private answer at connection time, and disabled default proxy configuration. These tests are **authored but not executed** in an environment that returned usable output.

## Remaining security and verification limits

- The source now pins the default transport's socket to an IP validated immediately before connection. This closes the previously identified preflight-to-connection DNS rebinding gap at the implementation level; it is **not yet independently verified by a successful test run**.
- An explicitly injected custom `opener` bypasses the default pinned transport and must be treated as a trusted test/adapter seam. Production callers must not inject an unreviewed opener.
- No live adversarial network tests have been run. Redirect chains, DNS changes, IPv4/IPv6 edge cases, TLS hostname mismatch, proxy environment behavior and connection failures need executed tests.
- The current signature check identifies PDF and ZIP-like containers; it is not malware scanning, archive validation, parser isolation, or proof that an OOXML document is safe.
- ZIP decompression limits, archive path traversal defense, parser process isolation, and extraction timeouts remain separate requirements.
- This module is not connected to a real source acquisition handler in the end-to-end recruitment pipeline.

## Production gate

Do not enable live fetching until the tests run with usable output, the default transport and redirect path are independently exercised, parser isolation and archive limits are decided, and the caller's allowlist and policy approval are explicit.
