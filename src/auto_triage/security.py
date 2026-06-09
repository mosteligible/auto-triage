import re
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
