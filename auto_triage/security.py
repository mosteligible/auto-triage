import re
import secrets
from hashlib import pbkdf2_hmac, sha256
from hmac import compare_digest

from pydantic import SecretStr

_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|token|secret|password|passwd)\b"
    r"(\s*[:=]\s*)([^\s,;\"']+)"
)


def secret_value(secret: SecretStr | None) -> str | None:
    if secret is None:
        return None
    value = secret.get_secret_value()
    return value or None


def constant_time_equal(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    return compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def redact_for_issue_body(value: str) -> str:
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", value)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    iterations = 210_000
    salt = secrets.token_hex(16)
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_raw, salt, expected = encoded.split("$", 3)
        iterations = int(iterations_raw)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return compare_digest(digest.hex(), expected)
