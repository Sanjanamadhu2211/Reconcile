from app.auth.passwords import hash_password, verify_password


def test_hash_is_argon2_and_verifies_the_password():
    password_hash = hash_password("correct horse battery")

    assert password_hash.startswith("$argon2id$")
    assert verify_password("correct horse battery", password_hash)


def test_wrong_password_and_missing_hash_fail():
    password_hash = hash_password("correct horse battery")

    assert not verify_password("wrong horse battery", password_hash)
    assert not verify_password("correct horse battery", None)
