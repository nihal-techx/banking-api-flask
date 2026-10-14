from app.security import hash_password, verify_password


def test_hash_is_argon2_and_verifies():
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery") is True
    assert verify_password(hashed, "wrong password") is False


def test_same_password_gets_different_hashes():
    assert hash_password("same-password-1") != hash_password("same-password-1")