from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("no-account-behind-this-hash")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    # Always spend one verify so a missing account takes as long as a wrong password.
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except VerificationError:
        return False
    return password_hash is not None
