from __future__ import annotations

import base64
from pathlib import Path
from time import monotonic
from typing import Any

import httpx

from auto_triage.config import Settings


class OpenBaoError(RuntimeError):
    pass


def is_openbao_ciphertext(value: str | None) -> bool:
    return bool(value and value.startswith("vault:v"))


class OpenBaoClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client_token: str | None = None
        self._token_expires_at = 0.0

    async def encrypt(self, organization_id: str, plaintext: str) -> str:
        payload = {
            "plaintext": _encode(plaintext),
            "context": _encode(organization_id),
        }
        data = await self._request(
            "POST",
            f"/v1/{self.settings.openbao_transit_mount}/encrypt/"
            f"{self.settings.openbao_transit_key}",
            payload,
        )
        ciphertext = data.get("ciphertext")
        if not isinstance(ciphertext, str) or not is_openbao_ciphertext(ciphertext):
            raise OpenBaoError("OpenBao returned an invalid ciphertext")
        return ciphertext

    async def decrypt(self, organization_id: str, ciphertext: str) -> str:
        if not is_openbao_ciphertext(ciphertext):
            return ciphertext
        payload = {
            "ciphertext": ciphertext,
            "context": _encode(organization_id),
        }
        data = await self._request(
            "POST",
            f"/v1/{self.settings.openbao_transit_mount}/decrypt/"
            f"{self.settings.openbao_transit_key}",
            payload,
        )
        plaintext = data.get("plaintext")
        if not isinstance(plaintext, str):
            raise OpenBaoError("OpenBao returned an invalid plaintext")
        try:
            return base64.b64decode(plaintext).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise OpenBaoError("OpenBao returned malformed plaintext") from exc

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.settings.openbao_enabled:
            raise OpenBaoError("OpenBao encryption is not enabled")

        token = await self._login()
        async with httpx.AsyncClient(
            base_url=self.settings.openbao_addr,
            timeout=self.settings.openbao_timeout_seconds,
        ) as client:
            response = await client.request(
                method,
                path,
                json=payload,
                headers={"X-Vault-Token": token},
            )
        if response.is_error:
            raise OpenBaoError(f"OpenBao request failed with HTTP {response.status_code}")
        result = response.json()
        data = result.get("data")
        if not isinstance(data, dict):
            raise OpenBaoError("OpenBao response did not contain data")
        return data

    async def _login(self) -> str:
        if self._client_token and monotonic() < self._token_expires_at:
            return self._client_token

        role_id = _read_secret_file(self.settings.openbao_role_id_file, "role ID")
        secret_id = _read_secret_file(self.settings.openbao_secret_id_file, "secret ID")
        async with httpx.AsyncClient(
            base_url=self.settings.openbao_addr,
            timeout=self.settings.openbao_timeout_seconds,
        ) as client:
            response = await client.post(
                f"/v1/auth/{self.settings.openbao_auth_mount}/login",
                json={"role_id": role_id, "secret_id": secret_id},
            )
        if response.is_error:
            raise OpenBaoError(f"OpenBao AppRole login failed with HTTP {response.status_code}")
        auth = response.json().get("auth")
        token = auth.get("client_token") if isinstance(auth, dict) else None
        if not isinstance(token, str) or not token:
            raise OpenBaoError("OpenBao AppRole login returned no client token")
        lease_duration = auth.get("lease_duration") if isinstance(auth, dict) else 0
        ttl = lease_duration if isinstance(lease_duration, int) else 0
        self._client_token = token
        self._token_expires_at = monotonic() + max(0, ttl - 30)
        return token


def _encode(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _read_secret_file(path: Path, label: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise OpenBaoError(f"OpenBao {label} file is unavailable") from exc
    if not value:
        raise OpenBaoError(f"OpenBao {label} file is empty")
    return value
