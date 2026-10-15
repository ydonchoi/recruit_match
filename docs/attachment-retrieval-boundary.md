# Attachment Retrieval Boundary

Status: **implemented as an injectable policy boundary; no production transport is supplied or verified**

## Required policy inputs

The caller must provide an explicit host allowlist, DNS resolver, robots-policy decision function, and transport. An empty allowlist fails closed. URL credentials, non-HTTPS URLs, nonstandard ports, fragments and unallowlisted hosts are rejected.

Before each request, all DNS addresses must be public/global. The validated address set is passed to the transport so the eventual network adapter can pin the connection to a validated address while preserving TLS hostname validation. **A transport that ignores this requirement is not safe for production use.** DNS validation followed by an independent, unpinned DNS lookup can be vulnerable to rebinding.

Redirects are handled manually. Every target is revalidated for URL policy, allowlist, DNS and robots permission before another request is made. Automatic redirect following by the transport is rejected by checking that the response URL matches the requested URL.

## Resource and content limits

- Timeout and maximum bytes are explicit positive parameters.
- No automatic retries are performed.
- Response bodies exceeding the configured byte limit are rejected.
- Only PDF and ZIP-signature content is accepted by the initial boundary.
- MIME type must be compatible with the observed signature.
- SHA-256, size, source/final URL, host, retrieval timestamp and signature are returned as a receipt.

Signature validation is a file-type boundary, not a malware scan, sandbox, document parser or proof of semantic validity. ZIP signatures do not prove that an archive is a valid or safe OOXML document. Any extraction stage must separately enforce decompression limits, path traversal defenses, parser isolation and time limits.

## Not implemented / not verified

- A production HTTP transport that enforces IP pinning and TLS hostname validation.
- A real robots.txt retrieval/cache implementation with bounded network timeouts.
- DNS rebinding resistance at the socket/transport boundary.
- Malware scanning or isolated document extraction.
- Live network tests against third-party hosts.

Until these components are implemented and adversarially tested, this module is a contract and test seam, not an enabled network collector.
