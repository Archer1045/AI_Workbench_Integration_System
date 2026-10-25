"""Provider configuration and connection testing for the Game Assistant."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, ConfigDict, Field

import config

from .domain import ProviderStatus
from .secret_store import ProviderSecretStore

ProviderId = Literal["deepseek", "openai_compatible", "ollama"]


class ProviderSettingsError(ValueError):
    pass


class ProviderSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, max_length=1000)
    clear_api_key: bool = False


class ProviderSettingsView(BaseModel):
    provider_id: ProviderId
    label: str
    base_url: str
    model: str
    api_key_configured: bool
    api_key_source: Literal["saved", "environment", "none"]
    available: bool
    last_test_at: str | None = None
    last_test_ok: bool | None = None
    last_test_message: str = ""


class ProviderTestResult(BaseModel):
    provider_id: ProviderId
    ok: bool
    message: str
    tested_at: str


_LABELS: dict[str, str] = {
    "deepseek": "DeepSeek API",
    "openai_compatible": "OpenAI 兼容接口",
    "ollama": "Ollama 本地模型",
}

_GUIDE_PROVIDER_MAP = {
    "local": "ollama",
    "deepseek": "deepseek",
    "openai_compatible": "openai_compatible",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderSettingsError("Base URL 必须是有效的 http/https 地址")
    return value


class ProviderSettingsService:
    def __init__(
        self,
        settings_path: Path | str | None = None,
        secret_store: ProviderSecretStore | None = None,
    ) -> None:
        self.settings_path = Path(settings_path or config.GAME_ASSISTANT_CONFIG_DIR / "providers.json")
        self.secrets = secret_store or ProviderSecretStore()

    def _read(self) -> dict[str, dict[str, object]]:
        if not self.settings_path.exists():
            return {}
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderSettingsError(f"读取模型配置失败: {exc}") from exc
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            raise ProviderSettingsError("模型配置文件格式无效")
        return {
            str(provider_id): value
            for provider_id, value in providers.items()
            if isinstance(value, dict)
        }

    def _write(self, providers: dict[str, dict[str, object]]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": 1, "providers": providers}
        temp = self.settings_path.with_name(f".{self.settings_path.name}.{os.getpid()}.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.settings_path)

    def _defaults(self, provider_id: str) -> dict[str, str]:
        if provider_id == "deepseek":
            return {
                "base_url": config.DEEPSEEK_BASE_URL,
                "model": config.DEEPSEEK_MODEL,
                "env_key": config.DEEPSEEK_API_KEY,
            }
        if provider_id == "openai_compatible":
            return {
                "base_url": os.environ.get("GAME_ASSISTANT_OPENAI_BASE_URL", "").strip(),
                "model": os.environ.get("GAME_ASSISTANT_OPENAI_MODEL", "").strip(),
                "env_key": os.environ.get("GAME_ASSISTANT_OPENAI_API_KEY", "").strip(),
            }
        if provider_id == "ollama":
            return {
                "base_url": config.OLLAMA_BASE,
                "model": config.GAME_ASSISTANT_LOCAL_MODEL,
                "env_key": "",
            }
        raise ProviderSettingsError(f"不支持的 Provider: {provider_id}")

    def _record(self, provider_id: str) -> tuple[dict[str, object], dict[str, str]]:
        defaults = self._defaults(provider_id)
        saved = self._read().get(provider_id, {})
        base_url = str(saved.get("base_url") or defaults["base_url"]).strip().rstrip("/")
        model = str(saved.get("model") or defaults["model"]).strip()
        return {
            **saved,
            "base_url": base_url,
            "model": model,
            "last_test_at": saved.get("last_test_at"),
            "last_test_ok": saved.get("last_test_ok"),
            "last_test_message": str(saved.get("last_test_message") or ""),
        }, defaults

    def _secret(self, provider_id: str, defaults: dict[str, str]) -> tuple[str, str]:
        saved_key = self.secrets.get_secret(provider_id)
        if saved_key:
            return saved_key, "saved"
        env_key = defaults.get("env_key", "")
        if env_key:
            return env_key, "environment"
        return "", "none"

    def _available(self, provider_id: str, base_url: str, model: str, key: str, record: dict[str, object]) -> bool:
        if bool(record.get("last_test_ok")) is True:
            return True
        if provider_id in {"deepseek", "openai_compatible"}:
            return bool(base_url and model and (key or provider_id == "openai_compatible"))
        if provider_id == "ollama" and base_url.rstrip("/") == config.OLLAMA_BASE.rstrip("/"):
            try:
                import llm

                return bool(llm.is_available())
            except Exception:
                return False
        return bool(base_url and model)

    def list_settings(self) -> list[ProviderSettingsView]:
        result: list[ProviderSettingsView] = []
        for provider_id in _LABELS:
            record, defaults = self._record(provider_id)
            key, source = self._secret(provider_id, defaults)
            base_url = str(record.get("base_url") or "")
            model = str(record.get("model") or "")
            result.append(
                ProviderSettingsView(
                    provider_id=provider_id,  # type: ignore[arg-type]
                    label=_LABELS[provider_id],
                    base_url=base_url,
                    model=model,
                    api_key_configured=bool(key),
                    api_key_source=source,  # type: ignore[arg-type]
                    available=self._available(provider_id, base_url, model, key, record),
                    last_test_at=record.get("last_test_at") if record.get("last_test_at") else None,  # type: ignore[arg-type]
                    last_test_ok=record.get("last_test_ok") if record.get("last_test_ok") is not None else None,  # type: ignore[arg-type]
                    last_test_message=str(record.get("last_test_message") or ""),
                )
            )
        return result

    def get(self, provider_id: str) -> ProviderSettingsView:
        for item in self.list_settings():
            if item.provider_id == provider_id:
                return item
        raise ProviderSettingsError(f"不支持的 Provider: {provider_id}")

    def update(self, provider_id: str, payload: ProviderSettingsUpdate) -> ProviderSettingsView:
        if provider_id not in _LABELS:
            raise ProviderSettingsError(f"不支持的 Provider: {provider_id}")
        record, _ = self._record(provider_id)
        connection_changed = False
        if payload.base_url is not None:
            base_url = _normalize_base_url(payload.base_url)
            connection_changed = connection_changed or base_url != record.get("base_url")
            record["base_url"] = base_url
        if payload.model is not None:
            model = payload.model.strip()
            connection_changed = connection_changed or model != record.get("model")
            record["model"] = model
        if payload.clear_api_key:
            self.secrets.delete_secret(provider_id)
            connection_changed = True
        elif payload.api_key is not None and payload.api_key.strip():
            self.secrets.set_secret(provider_id, payload.api_key)
            connection_changed = True
        if connection_changed:
            record.update({"last_test_at": None, "last_test_ok": None, "last_test_message": ""})
        providers = self._read()
        providers[provider_id] = record
        self._write(providers)
        return self.get(provider_id)

    def delete(self, provider_id: str) -> ProviderSettingsView:
        if provider_id not in _LABELS:
            raise ProviderSettingsError(f"不支持的 Provider: {provider_id}")
        self.secrets.delete_secret(provider_id)
        providers = self._read()
        providers.pop(provider_id, None)
        self._write(providers)
        return self.get(provider_id)

    def test(self, provider_id: str) -> ProviderTestResult:
        record, defaults = self._record(provider_id)
        key, _ = self._secret(provider_id, defaults)
        base_url = str(record.get("base_url") or "").rstrip("/")
        model = str(record.get("model") or "")
        if not base_url or not model:
            raise ProviderSettingsError("请先填写 Base URL 和模型名称")
        try:
            if provider_id == "ollama":
                response = requests.get(base_url + "/api/tags", timeout=min(config.GAME_ASSISTANT_LLM_TIMEOUT, 15))
            else:
                headers = {"Authorization": f"Bearer {key}"} if key else {}
                response = requests.get(base_url + "/models", headers=headers, timeout=min(config.GAME_ASSISTANT_LLM_TIMEOUT, 15))
            response.raise_for_status()
            models: list[str] = []
            payload = response.json()
            if isinstance(payload, dict):
                raw_models = payload.get("data") or payload.get("models") or []
                if isinstance(raw_models, list):
                    for item in raw_models:
                        if isinstance(item, dict):
                            name = item.get("id") or item.get("name") or item.get("model")
                            if name:
                                models.append(str(name))
            model_known = not models or model in models
            message = "连接成功" + ("" if model_known else f"；接口可用，但模型列表中未看到 {model}")
            ok = True
            record.update({"last_test_at": _now(), "last_test_ok": True, "last_test_message": message})
        except Exception as exc:
            ok = False
            message = f"连接失败: {type(exc).__name__}: {exc}"
            record.update({"last_test_at": _now(), "last_test_ok": False, "last_test_message": message})
        providers = self._read()
        providers[provider_id] = record
        self._write(providers)
        return ProviderTestResult(provider_id=provider_id, ok=ok, message=message, tested_at=str(record["last_test_at"]))  # type: ignore[arg-type]

    def runtime_config(self, guide_provider: str) -> dict[str, object]:
        if guide_provider == "template":
            return {"available": True, "base_url": "", "model": "deterministic-template", "api_key": ""}
        provider_id = _GUIDE_PROVIDER_MAP.get(guide_provider)
        if provider_id is None:
            raise ProviderSettingsError(f"不支持的 Provider: {guide_provider}")
        record, defaults = self._record(provider_id)
        key, _ = self._secret(provider_id, defaults)
        base_url = str(record.get("base_url") or "")
        model = str(record.get("model") or "")
        return {
            "available": self._available(provider_id, base_url, model, key, record),
            "base_url": base_url,
            "model": model,
            "api_key": key,
        }

    def guide_statuses(self) -> list[ProviderStatus]:
        statuses = [ProviderStatus(provider="template", available=True, model="deterministic-template", detail="无需外部模型，用于回退和结构验证。")]
        mapping = {"deepseek": "deepseek", "openai_compatible": "openai_compatible", "ollama": "local"}
        for item in self.list_settings():
            statuses.append(
                ProviderStatus(
                    provider=mapping[item.provider_id],  # type: ignore[arg-type]
                    available=item.available,
                    model=item.model,
                    detail=item.last_test_message or f"{item.label}: {item.base_url}",
                )
            )
        return statuses


_SERVICE: ProviderSettingsService | None = None


def get_provider_settings_service() -> ProviderSettingsService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ProviderSettingsService()
    return _SERVICE


def reset_provider_settings_service() -> None:
    global _SERVICE
    _SERVICE = None
