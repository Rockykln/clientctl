"""utils.encoding — base64url roundtrip."""

import pytest

from utils.encoding import b64url_decode, b64url_encode


@pytest.mark.parametrize("data", [
    b"",
    b"\x00",
    b"hello",
    b"\xff" * 32,
    bytes(range(256)),
])
def test_roundtrip(data):
    assert b64url_decode(b64url_encode(data)) == data


def test_no_padding():
    # b64url encoded form must not contain padding
    encoded = b64url_encode(b"foobar")
    assert "=" not in encoded


def test_url_safe_chars():
    # +/ become -_
    encoded = b64url_encode(b"\xff\xfe")
    assert "+" not in encoded
    assert "/" not in encoded


def test_decode_accepts_missing_padding():
    # Must accept input without padding (per spec) AND with padding
    assert b64url_decode("aGVsbG8") == b"hello"
    assert b64url_decode("aGVsbG8=") == b"hello"
