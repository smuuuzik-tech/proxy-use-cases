from proxy_b2b_client.redaction import redact_url


def test_redacts_userinfo_fragment_and_sensitive_query_values():
    redacted = redact_url(
        "https://alice:secret@example.test:8443/path"
        "?page=2&access_token=abc&signature=xyz#private"
    )

    assert redacted == (
        "https://example.test:8443/<redacted-path>?<redacted-query>"
    )
    assert "alice" not in redacted
    assert "secret" not in redacted
    assert "private" not in redacted
