# ---------------------------------------------------------------------------
# Label PIN: mixed into the seal key, never sent over BLE
# ---------------------------------------------------------------------------

"""
_PROVISION = {
    \"controller_id\": \"ctrl\",
    \"controller_urls\": [\"http://192.0.2.10:6969\"],
    \"node_key\": \"ab\" * 32,
    \"wifi\": [],
}


def _paired_with_pin(board_pin: str):
    \"\"\"Real handshake up to and including the reveal; returns (responder, initiator).\"\"\"
    rsp = proto.PairResponder(\"UNIT\", proto.x25519_keypair()[0], label_pin=board_pin)
    ini = proto.PairInitiator(\"ctrl\", proto.x25519_keypair()[0])
    nonce = ini.on_hello_commit(\"UNIT\", rsp.handle_message(ini.start_hello()))
    ini.on_reveal(rsp.handle_message(nonce))
    return rsp, ini


def test_both_sides_same_label_pin_provision_succeeds():
    rsp, ini = _paired_with_pin(\"123456\")
    ini.bind_label_pin(\"123456\")
    reply = rsp.handle_message(ini.seal_provision(_PROVISION))
    assert ini.unseal_reply(reply) == {\"t\": \"ok\"}
    assert rsp.paired is True


def test_wrong_label_pin_provision_fails_authentication():
    from cryptography.exceptions import InvalidTag

    rsp, ini = _paired_with_pin(\"123456\")
    ini.bind_label_pin(\"654321\")
    reply = rsp.handle_message(ini.seal_provision(_PROVISION))
    # The board cannot decrypt, so it answers with a SEALED error frame, not a plaintext one.
    assert json.loads(reply)[\"t\"] == \"sealed\"
    with pytest.raises(InvalidTag):
        ini.unseal_reply(reply)
    assert rsp.paired is False


def test_initiator_without_pin_against_pin_bound_board_fails():
    from cryptography.exceptions import InvalidTag

    rsp, ini = _paired_with_pin(\"123456\")
    reply = rsp.handle_message(ini.seal_provision(_PROVISION))
    assert json.loads(reply)[\"t\"] == \"sealed\"
    with pytest.raises(InvalidTag):
        ini.unseal_reply(reply)
    assert rsp.paired is False


def test_bind_label_pin_twice_raises():
    _rsp, ini = _paired_with_pin(\"123456\")
    ini.bind_label_pin(\"123456\")
    with pytest.raises(ValueError, match=\"already bound\"):
        ini.bind_label_pin(\"123456\")


def test_bind_label_pin_before_handshake_raises():
    ini = proto.PairInitiator(\"ctrl\", proto.x25519_keypair()[0])
    with pytest.raises(ValueError, match=\"no session\"):
        ini.bind_label_pin(\"123456\")


def test_bind_label_pin_rejects_empty_pin():
    _rsp, ini = _paired_with_pin(\"123456\")
    with pytest.raises(ValueError):
        ini.bind_label_pin(\"\")


def test_pairing_code_unchanged_by_pin():
    rsp, ini = _paired_with_pin(\"123456\")
    ini.bind_label_pin(\"123456\")
    assert rsp.current_code() == ini.current_code()
    assert rsp.current_code() is not None


def test_fake_board_never_leaks_label_pin():
    board = FakeBoard(label_pin=\"123456\")
    info = board.info_bytes()
    assert b\"123456\" not in info
    assert \"pin-bound\" in json.loads(info)[\"caps\"]
    assert \"pin-bound\" not in json.loads(FakeBoard().info_bytes())[\"caps\"]
"""