from openticker.core.web import host_allowed, new_secret, origin_allowed, secret_hash


def test_host_allowed_accepts_loopback_names_on_own_port_only() -> None:
    assert host_allowed("127.0.0.1:8750", 8750)
    assert host_allowed("localhost:8750", 8750)
    assert host_allowed("[::1]:8750", 8750)
    assert not host_allowed("127.0.0.1:9999", 8750)
    assert not host_allowed("evil.com:8750", 8750)
    assert not host_allowed("127.0.0.1.evil.com:8750", 8750)
    assert not host_allowed(None, 8750)
    assert not host_allowed("", 8750)


def test_host_allowed_accepts_a_missing_port_only_on_port_80() -> None:
    assert host_allowed("localhost", 80)
    assert not host_allowed("localhost", 8750)


def test_origin_allowed_rejects_foreign_and_null() -> None:
    own = "http://127.0.0.1:8750"
    assert origin_allowed(own, own, None)
    assert not origin_allowed("http://evil.com", own, None)
    assert not origin_allowed("null", own, None)
    assert not origin_allowed(None, own, None)


def test_origin_allowed_accepts_localhost_spelling_of_own_origin() -> None:
    assert origin_allowed("http://localhost:8750", "http://127.0.0.1:8750", None)


def test_dev_origin_only_when_set() -> None:
    own = "http://127.0.0.1:8750"
    assert not origin_allowed("http://localhost:5173", own, None)
    assert origin_allowed("http://localhost:5173", own, "http://localhost:5173")


def test_secrets_are_long_random_and_only_their_hash_is_stable() -> None:
    first, second = new_secret(), new_secret()
    assert first != second
    assert len(first) >= 40
    assert secret_hash(first) == secret_hash(first)
    assert secret_hash(first) != first
    assert len(secret_hash(first)) == 64
