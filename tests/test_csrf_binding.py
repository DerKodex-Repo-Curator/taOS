"""Session-bound CSRF tokens (tsk-rll7hq, CSRF binding 1/3).

A bare random ``csrf_token`` is not tied to ``taos_session``, so a sibling
``{user}.taos.my`` subdomain can plant a ``Domain=.taos.my`` cookie and satisfy
the double-submit check with a header it chose.  A bound token is
``<nonce>.<hmac_sha256(secret, session_id + nonce)>``: only the server can mint
one for a given session, and a token minted for session A does not verify for
session B.
"""

from tinyagentos.middleware import csrf

SECRET = b"s" * 32
OTHER_SECRET = b"o" * 32
SESSION_A = "session-token-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SESSION_B = "session-token-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def test_valid_token_accepted():
    token = csrf.mint_csrf_token(SECRET, SESSION_A)
    assert csrf.verify_bound(SECRET, token, SESSION_A) is True


def test_token_shape_is_nonce_dot_mac():
    token = csrf.mint_csrf_token(SECRET, SESSION_A)
    nonce, mac = token.split(".")
    int(nonce, 16)
    int(mac, 16)
    assert len(mac) == 64  # hex sha256


def test_each_mint_uses_a_fresh_nonce():
    assert csrf.mint_csrf_token(SECRET, SESSION_A) != csrf.mint_csrf_token(SECRET, SESSION_A)


def test_token_for_session_a_rejected_for_session_b():
    token = csrf.mint_csrf_token(SECRET, SESSION_A)
    assert csrf.verify_bound(SECRET, token, SESSION_B) is False


def test_token_rejected_under_a_different_secret():
    token = csrf.mint_csrf_token(SECRET, SESSION_A)
    assert csrf.verify_bound(OTHER_SECRET, token, SESSION_A) is False


def test_tampered_nonce_rejected():
    token = csrf.mint_csrf_token(SECRET, SESSION_A)
    nonce, mac = token.split(".")
    flipped = ("0" if nonce[0] != "0" else "1") + nonce[1:]
    assert csrf.verify_bound(SECRET, f"{flipped}.{mac}", SESSION_A) is False


def test_tampered_mac_rejected():
    token = csrf.mint_csrf_token(SECRET, SESSION_A)
    nonce, mac = token.split(".")
    flipped = mac[:-1] + ("0" if mac[-1] != "0" else "1")
    assert csrf.verify_bound(SECRET, f"{nonce}.{flipped}", SESSION_A) is False


def test_legacy_unbound_token_rejected():
    # What CSRFMiddleware mints today: 64 hex chars, no MAC.
    assert csrf.verify_bound(SECRET, "ab" * 32, SESSION_A) is False


def test_malformed_inputs_rejected_without_raising():
    good = csrf.mint_csrf_token(SECRET, SESSION_A)
    nonce, mac = good.split(".")
    for token in (
        "",
        ".",
        "..",
        f"{nonce}.",
        f".{mac}",
        f"{nonce}.{mac}.extra",
        f"{nonce}{mac}",
        f"zz{nonce[2:]}.{mac}",
        f"{nonce}.{mac}é",
        None,
        123,
        b"bytes",
    ):
        assert csrf.verify_bound(SECRET, token, SESSION_A) is False, token
    for session in ("", None, 5):
        assert csrf.verify_bound(SECRET, good, session) is False, session
    for secret in (b"", None, "not-bytes"):
        assert csrf.verify_bound(secret, good, SESSION_A) is False, secret
