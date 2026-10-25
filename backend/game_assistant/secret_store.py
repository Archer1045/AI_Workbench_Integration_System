"""Local secret storage for Game Assistant provider keys.

Windows uses DPAPI so the JSON file contains only user-scoped encrypted blobs.
Non-Windows falls back to a restricted local file for development/tests.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import threading
from ctypes import wintypes
from pathlib import Path

import config


class SecretStoreError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _protect(value: str) -> str:
    data = value.encode("utf-8")
    if os.name != "nt":
        return "plain:" + base64.b64encode(data).decode("ascii")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_buffer = ctypes.create_string_buffer(data)
    in_blob = _DataBlob(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "AI Workbench Game Assistant",
        None,
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
    return "dpapi:" + base64.b64encode(encrypted).decode("ascii")


def _unprotect(value: str) -> str:
    scheme, _, encoded = value.partition(":")
    if scheme == "plain":
        return base64.b64decode(encoded).decode("utf-8")
    if scheme != "dpapi":
        raise SecretStoreError("unsupported secret encoding")
    if os.name != "nt":
        raise SecretStoreError("DPAPI secret cannot be read on this platform")
    encrypted = base64.b64decode(encoded)
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_buffer = ctypes.create_string_buffer(encrypted)
    in_blob = _DataBlob(len(encrypted), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError()
    try:
        decrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
    return decrypted.decode("utf-8")


class ProviderSecretStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or config.GAME_ASSISTANT_SECRETS_PATH)
        self._lock = threading.RLock()

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SecretStoreError(f"unable to read secret store: {exc}") from exc
        secrets = payload.get("secrets")
        if not isinstance(secrets, dict):
            raise SecretStoreError("secret store has an invalid format")
        return {str(key): str(value) for key, value in secrets.items()}

    def _write(self, secrets: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": 1, "secrets": secrets}
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(self.path)

    def get_secret(self, provider_id: str) -> str:
        with self._lock:
            encoded = self._read().get(provider_id)
            if not encoded:
                return ""
            try:
                return _unprotect(encoded)
            except Exception as exc:
                raise SecretStoreError(f"unable to decrypt stored API key: {exc}") from exc

    def has_secret(self, provider_id: str) -> bool:
        return bool(self.get_secret(provider_id))

    def set_secret(self, provider_id: str, value: str) -> None:
        value = value.strip()
        if not value:
            self.delete_secret(provider_id)
            return
        with self._lock:
            secrets = self._read()
            secrets[provider_id] = _protect(value)
            self._write(secrets)

    def delete_secret(self, provider_id: str) -> None:
        with self._lock:
            secrets = self._read()
            if provider_id in secrets:
                secrets.pop(provider_id, None)
                self._write(secrets)
