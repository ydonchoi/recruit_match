import io
import unittest
from email.message import Message

from recruit_match.attachments import (
    AttachmentFetchError,
    AttachmentLimits,
    AttachmentPolicy,
    PublicURLPolicy,
    SafeAttachmentFetcher,
    _classify_content,
    _read_bounded,
)


def resolver_public(host, port):
    return [(None, None, None, None, ("93.184.216.34", port))]


def resolver_private(host, port):
    return [(None, None, None, None, ("127.0.0.1", port))]


class FakeResponse:
    def __init__(self, body, url="https://jobs.example.test/a.pdf", content_type="application/pdf", length=None):
        self.body = io.BytesIO(body)
        self.url = url
        self.status = 200
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def read(self, size=-1):
        return self.body.read(size)

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.body.close()


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class AttachmentSafetyTests(unittest.TestCase):
    def test_requires_https(self):
        policy = PublicURLPolicy(frozenset({"jobs.example.test"}), resolver_public)
        with self.assertRaisesRegex(AttachmentFetchError, "HTTPS_URL_REQUIRED"):
            policy.validate("http://jobs.example.test/a.pdf")

    def test_empty_allowlist_denies_all_hosts(self):
        policy = PublicURLPolicy(frozenset(), resolver_public)
        with self.assertRaisesRegex(AttachmentFetchError, "HOST_NOT_ALLOWLISTED"):
            policy.validate("https://jobs.example.test/a.pdf")

    def test_private_dns_answer_is_rejected(self):
        policy = PublicURLPolicy(frozenset({"jobs.example.test"}), resolver_private)
        with self.assertRaisesRegex(AttachmentFetchError, "NONPUBLIC_DNS_TARGET_FORBIDDEN"):
            policy.validate("https://jobs.example.test/a.pdf")

    def test_malformed_port_is_rejected_with_sanitized_error(self):
        policy = PublicURLPolicy(frozenset({"jobs.example.test"}), resolver_public)
        with self.assertRaisesRegex(AttachmentFetchError, "MALFORMED_URL"):
            policy.validate("https://jobs.example.test:invalid/a.pdf")

    def test_empty_dns_answers_are_rejected(self):
        policy = PublicURLPolicy(frozenset({"jobs.example.test"}), lambda host, port: [])
        with self.assertRaisesRegex(AttachmentFetchError, "DNS_NO_ADDRESSES"):
            policy.validate("https://jobs.example.test/a.pdf")

    def test_credentials_in_url_are_rejected(self):
        policy = PublicURLPolicy(frozenset({"jobs.example.test"}), resolver_public)
        with self.assertRaisesRegex(AttachmentFetchError, "URL_CREDENTIALS_FORBIDDEN"):
            policy.validate("https://user:pass@jobs.example.test/a.pdf")

    def test_size_limit_detects_overflow_instead_of_returning_truncation(self):
        response = io.BytesIO(b"123456")
        with self.assertRaisesRegex(AttachmentFetchError, "BYTE_LIMIT_EXCEEDED"):
            _read_bounded(response, 5)

    def test_pdf_magic_and_mime_must_agree(self):
        self.assertEqual(_classify_content("application/pdf", b"%PDF-1.7\n"), "pdf")
        with self.assertRaisesRegex(AttachmentFetchError, "CONTENT_TYPE_MAGIC_MISMATCH"):
            _classify_content("text/html", b"%PDF-1.7\n")

    def test_unknown_magic_is_rejected(self):
        with self.assertRaisesRegex(AttachmentFetchError, "UNSUPPORTED_OR_UNVERIFIED_CONTENT"):
            _classify_content("application/octet-stream", b"not a known file")

    def test_policy_gate_precedes_any_network_request(self):
        opener = FakeOpener([])
        fetcher = SafeAttachmentFetcher(
            AttachmentPolicy(frozenset({"jobs.example.test"}), policy_allows=False),
            resolver=resolver_public,
            opener=opener,
        )
        with self.assertRaisesRegex(AttachmentFetchError, "POLICY_GATE_DENIED"):
            fetcher.fetch("https://jobs.example.test/a.pdf")
        self.assertEqual(opener.calls, [])

    def test_robots_fetch_uses_explicit_timeout_and_bounded_read(self):
        robots = FakeResponse(b"User-agent: *\nDisallow: /private\n", "https://jobs.example.test/robots.txt", "text/plain")
        opener = FakeOpener([robots])
        fetcher = SafeAttachmentFetcher(
            AttachmentPolicy(frozenset({"jobs.example.test"}), policy_allows=True),
            AttachmentLimits(timeout_seconds=2, robots_max_bytes=100),
            resolver=resolver_public,
            opener=opener,
        )
        self.assertFalse(fetcher._robots_allowed("https://jobs.example.test/private/a.pdf"))
        self.assertEqual(opener.calls[0][1], 2)


if __name__ == "__main__":
    unittest.main()
