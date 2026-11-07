"""Workbench-wide web search and page-fetch tools.

The public application code goes through this module instead of calling a
search provider directly. The first provider is DeepSeek Search & Fetch;
Tavily, Serper, and DuckDuckGo remain available as compatible fallbacks.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

import config
import database
from game_assistant.secret_store import ProviderSecretStore

ProviderId = Literal["deepseek", "tavily", "serper", "duckduckgo"]
WEB_TOOLS_SETTING_KEY = "web_tools.config"
WEB_TOOLS_LAST_TEST_KEY = "web_tools.last_test"
DEFAULT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "tavily": "https://api.tavily.com",
    "serper": "https://google.serper.dev",
    "duckduckgo": "https://api.duckduckgo.com",
}


def _is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return bool(ip.is_global)


def _resolve_host(hostname: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _validate_fetch_url(url: str) -> str:
    """Reject local, private, link-local, and unresolved destinations."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WebToolsError("URL 必须是有效的 http/https 地址")
    if parsed.username or parsed.password:
        raise WebToolsError("URL 不能包含用户名或密码")
    if len(url) > 8192:
        raise WebToolsError("URL 超过 8192 字符")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise WebToolsError("URL 指向本机地址，已拒绝")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise WebToolsError("URL 端口不合法") from exc
    try:
        ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        try:
            addresses = _resolve_host(hostname, port)
        except (OSError, UnicodeError) as exc:
            raise WebToolsError("URL 域名无法解析") from exc
        if not addresses:
            raise WebToolsError("URL 域名无法解析")
    else:
        addresses = [hostname.strip("[]")]
    if any(not _is_public_ip(address) for address in addresses):
        raise WebToolsError("URL 指向本机或内网地址，已拒绝")
    return url


class WebToolsError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class WebToolsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    provider: ProviderId = "deepseek"
    base_url: str = DEFAULT_BASE_URLS["deepseek"]
    default_count: int = Field(default=5, ge=1, le=50)
    default_need_content: bool = False
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    cache_ttl_seconds: int = Field(default=86_400, ge=0, le=604_800)
    max_results: int = Field(default=20, ge=1, le=50)
    max_fetch_per_query: int = Field(default=2, ge=0, le=10)
    max_qps: float = Field(default=5.0, gt=0, le=5.0)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Base URL 必须是有效的 http/https 地址")
        if parsed.username or parsed.password:
            raise ValueError("Base URL 不能包含用户名或密码")
        return value


class SearchResult(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""
    summary: str = ""
    content: str = ""
    site_name: str | None = None
    site_icon: str | None = None
    date: str | None = None
    authority: int | None = None
    rerank_score: float | None = None


class SearchResponse(BaseModel):
    provider: ProviderId
    results: list[SearchResult]
    cached: bool = False
    took_ms: int = 0


class FetchResponse(BaseModel):
    url: str
    title: str = ""
    content: str
    cached: bool = False


class WebToolsView(BaseModel):
    settings: WebToolsSettings
    api_key_configured: bool
    api_key_source: Literal["saved", "environment", "none"]
    last_test_at: str | None = None
    last_test_ok: bool | None = None
    last_test_message: str = ""


class _Limiter:
    """Small process-local limiter for a single-account QPS policy."""

    def __init__(self, qps: float) -> None:
        self._lock = threading.Lock()
        self._events: deque[float] = deque()
        self.qps = max(0.1, float(qps))

    def wait(self) -> None:
        while True:
            now = time.monotonic()
            with self._lock:
                while self._events and now - self._events[0] >= 1.0:
                    self._events.popleft()
                if len(self._events) < self.qps:
                    self._events.append(now)
                    return
                delay = max(0.01, 1.0 - (now - self._events[0]))
            time.sleep(min(delay, 0.25))


class _FileCache:
    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self.directory / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"

    def get(self, key: str, ttl_seconds: int) -> dict[str, Any] | None:
        if ttl_seconds <= 0:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > ttl_seconds:
            try:
                path.unlink()
            except OSError:
                pass
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def set(self, key: str, payload: dict[str, Any]) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self._path(key)
            temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temp.replace(path)
        except OSError:
            # A cache write failure must not fail an otherwise valid request.
            pass

    def clear(self) -> int:
        if not self.directory.exists():
            return 0
        count = 0
        for path in self.directory.glob("*.json"):
            try:
                path.unlink()
                count += 1
            except OSError:
                continue
        return count


class WebToolsService:
    def __init__(self) -> None:
        self.secrets = _WebToolsSecrets()
        self.cache = _FileCache(config.WEB_TOOLS_CACHE_DIR)
        self._limiter_lock = threading.Lock()
        self._limiter: _Limiter | None = None
        self._limiter_qps = 0.0

    def load_settings(self) -> WebToolsSettings:
        raw = database.get_setting(WEB_TOOLS_SETTING_KEY, "")
        if not raw:
            return WebToolsSettings()
        try:
            return WebToolsSettings.model_validate_json(raw)
        except Exception:
            return WebToolsSettings()

    def save_settings(self, settings: WebToolsSettings) -> WebToolsSettings:
        database.set_setting(WEB_TOOLS_SETTING_KEY, settings.model_dump_json())
        self._reset_limiter(settings.max_qps)
        return settings

    def _secret(self, provider: ProviderId, settings: WebToolsSettings) -> tuple[str, str]:
        return self.secrets.get(provider, settings)

    def view(self) -> WebToolsView:
        settings = self.load_settings()
        key, source = self._secret(settings.provider, settings)
        last_test = self._load_last_test()
        return WebToolsView(
            settings=settings,
            api_key_configured=bool(key),
            api_key_source=source,  # type: ignore[arg-type]
            last_test_at=last_test.get("at"),
            last_test_ok=last_test.get("ok"),
            last_test_message=str(last_test.get("message") or ""),
        )

    def set_api_key(self, provider: ProviderId, api_key: str = "", clear: bool = False) -> WebToolsView:
        if clear:
            self.secrets.clear(provider)
        elif api_key.strip():
            self.secrets.set(provider, api_key)
        return self.view()

    def _load_last_test(self) -> dict[str, Any]:
        try:
            payload = json.loads(database.get_setting(WEB_TOOLS_LAST_TEST_KEY, "{}"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_last_test(self, *, ok: bool, message: str) -> None:
        database.set_setting(
            WEB_TOOLS_LAST_TEST_KEY,
            json.dumps(
                {
                    "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "ok": ok,
                    "message": message,
                },
                ensure_ascii=False,
            ),
        )

    def _reset_limiter(self, qps: float) -> None:
        with self._limiter_lock:
            self._limiter_qps = qps
            self._limiter = _Limiter(qps)

    def _wait(self, settings: WebToolsSettings) -> None:
        with self._limiter_lock:
            if self._limiter is None or self._limiter_qps != settings.max_qps:
                self._limiter_qps = settings.max_qps
                self._limiter = _Limiter(settings.max_qps)
            limiter = self._limiter
        limiter.wait()

    def search(
        self,
        query: str,
        *,
        count: int | None = None,
        need_content: bool | None = None,
        ori_question: str | None = None,
        localization: str | None = None,
        app: str = "unknown",
    ) -> SearchResponse:
        settings = self.load_settings()
        if not settings.enabled:
            raise WebToolsError("联网搜索已关闭")
        query = str(query or "").strip()
        if not query or len(query) > 128:
            raise WebToolsError("query 必须为 1–128 个字符")
        requested_count = settings.default_count if count is None else int(count)
        if requested_count < 1 or requested_count > 50:
            raise WebToolsError("count 必须为 1–50")
        count = min(requested_count, settings.max_results)
        need_content = settings.default_need_content if need_content is None else bool(need_content)
        payload = {
            "query": query,
            "count": count,
            "need_content": need_content,
        }
        if ori_question:
            payload["ori_question"] = str(ori_question)[:128]
        if localization:
            payload["localization"] = localization
        cache_key = json.dumps(
            {"provider": settings.provider, "base_url": settings.base_url, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
        )
        cached = self.cache.get(cache_key, settings.cache_ttl_seconds)
        if cached is not None:
            results = [SearchResult.model_validate(item) for item in cached.get("results") or []]
            self._log_event(app, "search", query, len(results), 0, ok=True, cached=True)
            return SearchResponse(
                provider=settings.provider,
                results=results,
                cached=True,
            )
        started = time.monotonic()
        try:
            self._wait(settings)
            results = self._search_provider(settings, payload)
        except WebToolsError as exc:
            self._log_event(
                app,
                "search",
                query,
                0,
                int((time.monotonic() - started) * 1000),
                ok=False,
                status_code=exc.status_code,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            self._log_event(
                app,
                "search",
                query,
                0,
                int((time.monotonic() - started) * 1000),
                ok=False,
            )
            raise WebToolsError(f"搜索失败：{type(exc).__name__}") from exc
        elapsed = int((time.monotonic() - started) * 1000)
        response = SearchResponse(
            provider=settings.provider,
            results=results,
            cached=False,
            took_ms=elapsed,
        )
        self.cache.set(cache_key, {"results": [item.model_dump() for item in results]})
        self._log_event(app, "search", query, len(results), elapsed, ok=True)
        return response

    def fetch(self, url: str, *, app: str = "unknown") -> FetchResponse:
        settings = self.load_settings()
        if not settings.enabled:
            raise WebToolsError("联网搜索已关闭")
        url = str(url or "").strip()
        _validate_fetch_url(url)
        if settings.provider != "deepseek":
            raise WebToolsError("Fetch 当前只支持 DeepSeek Provider")
        cache_key = json.dumps(
            {"provider": "deepseek", "base_url": settings.base_url, "fetch": url},
            sort_keys=True,
        )
        cached = self.cache.get(cache_key, settings.cache_ttl_seconds)
        if cached is not None:
            self._log_event(app, "fetch", url, 1, 0, ok=True, cached=True)
            return FetchResponse(url=url, title=str(cached.get("title") or ""), content=str(cached.get("content") or ""), cached=True)
        started = time.monotonic()
        try:
            self._wait(settings)
            data = self._post_deepseek(settings, "/v1/tools/fetch", {"url": url})
        except WebToolsError as exc:
            self._log_event(
                app,
                "fetch",
                url,
                0,
                int((time.monotonic() - started) * 1000),
                ok=False,
                status_code=exc.status_code,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            self._log_event(app, "fetch", url, 0, int((time.monotonic() - started) * 1000), ok=False)
            raise WebToolsError(f"抓取失败：{type(exc).__name__}") from exc
        title = str(data.get("title") or "")
        content = str(data.get("content") or "")
        if not content:
            raise WebToolsError("Fetch 没有返回可用正文", status_code=404)
        self.cache.set(cache_key, {"title": title, "content": content})
        self._log_event(app, "fetch", url, 1, int((time.monotonic() - started) * 1000), ok=True)
        return FetchResponse(url=url, title=title, content=content)

    def fetch_many(
        self,
        urls: list[str],
        *,
        app: str = "unknown",
        limit: int | None = None,
    ) -> list[FetchResponse]:
        """Fetch at most max_fetch_per_query distinct URLs, skipping failures."""
        settings = self.load_settings()
        cap = settings.max_fetch_per_query
        if limit is not None:
            cap = min(cap, max(0, int(limit)))
        responses: list[FetchResponse] = []
        seen: set[str] = set()
        for url in urls:
            value = str(url or "").strip()
            if not value or value in seen:
                continue
            if len(responses) >= cap:
                break
            seen.add(value)
            try:
                responses.append(self.fetch(value, app=app))
            except WebToolsError:
                continue
        return responses

    def test_connection(self) -> dict[str, Any]:
        try:
            response = self.search(
                "DeepSeek Search API",
                count=1,
                need_content=False,
                app="settings-test",
            )
            message = f"连接成功：返回 {len(response.results)} 条结果"
            if response.cached:
                message += "（命中缓存）"
            self._save_last_test(ok=True, message=message)
            return {"ok": True, "message": message}
        except Exception as exc:
            message = f"连接失败：{type(exc).__name__}: {exc}"
            self._save_last_test(ok=False, message=message)
            return {"ok": False, "message": message}

    def clear_cache(self) -> int:
        return self.cache.clear()

    @staticmethod
    def _send(call) -> requests.Response:
        try:
            return call()
        except requests.Timeout as exc:
            raise WebToolsError("搜索服务请求超时", retryable=True) from exc
        except requests.RequestException as exc:
            raise WebToolsError(
                f"搜索服务连接失败：{type(exc).__name__}",
                retryable=True,
            ) from exc

    def _search_provider(self, settings: WebToolsSettings, payload: dict[str, Any]) -> list[SearchResult]:
        if settings.provider == "deepseek":
            data = self._post_deepseek(settings, "/v1/tools/search", payload)
            return [self._deepseek_result(item) for item in data.get("results") or [] if isinstance(item, dict)]
        if settings.provider == "tavily":
            key, _ = self._secret("tavily", settings)
            if not key:
                raise WebToolsError("Tavily 未配置 API Key", status_code=401)
            response = self._send(
                lambda: requests.post(
                    settings.base_url.rstrip("/") + "/search",
                    json={"api_key": key, "query": payload["query"], "max_results": payload["count"], "search_depth": "basic"},
                    timeout=settings.timeout_seconds,
                )
            )
            return [self._tavily_result(item) for item in self._json_response(response).get("results") or [] if isinstance(item, dict)]
        if settings.provider == "serper":
            key, _ = self._secret("serper", settings)
            if not key:
                raise WebToolsError("Serper 未配置 API Key", status_code=401)
            response = self._send(
                lambda: requests.post(
                    settings.base_url.rstrip("/") + "/search",
                    json={"q": payload["query"], "num": payload["count"]},
                    headers={"X-API-KEY": key},
                    timeout=settings.timeout_seconds,
                )
            )
            return [self._serper_result(item) for item in self._json_response(response).get("organic") or [] if isinstance(item, dict)]
        response = self._send(
            lambda: requests.get(
                settings.base_url.rstrip("/") + "/",
                params={"q": payload["query"], "format": "json", "no_html": 1, "skip_disambig": 1},
                timeout=settings.timeout_seconds,
            )
        )
        data = self._json_response(response)
        results: list[SearchResult] = []
        if data.get("AbstractText") and data.get("AbstractURL"):
            results.append(SearchResult(
                title=str(data.get("Heading") or payload["query"]),
                url=str(data["AbstractURL"]),
                snippet=str(data["AbstractText"]),
                summary=str(data["AbstractText"]),
            ))
        for topic in data.get("RelatedTopics") or []:
            if isinstance(topic, dict) and topic.get("Text") and topic.get("FirstURL"):
                text = str(topic["Text"])
                results.append(SearchResult(title=text[:80], url=str(topic["FirstURL"]), snippet=text, summary=text))
            if len(results) >= payload["count"]:
                break
        return results[: payload["count"]]

    def _post_deepseek(self, settings: WebToolsSettings, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        key, _ = self._secret("deepseek", settings)
        if not key:
            raise WebToolsError("DeepSeek 未配置 API Key", status_code=401)
        url = settings.base_url.rstrip("/") + path
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._send(
                    lambda: requests.post(
                        url,
                        headers={"Authorization": f"Bearer {key}"},
                        json=payload,
                        timeout=settings.timeout_seconds,
                    )
                )
                return self._json_response(response)
            except WebToolsError as exc:
                last_error = exc
                if not exc.retryable or attempt >= 2:
                    raise
                time.sleep(0.4 * (attempt + 1))
                self._wait(settings)
        raise WebToolsError(f"DeepSeek 请求失败：{last_error}")

    @staticmethod
    def _json_response(response: requests.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            retryable = response.status_code in {408, 429} or response.status_code >= 500
            try:
                detail = response.json().get("error", {}).get("message") or response.text[:300]
            except Exception:
                detail = response.text[:300]
            raise WebToolsError(
                f"HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
                retryable=retryable,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise WebToolsError("搜索服务返回了非 JSON 响应") from exc
        if not isinstance(payload, dict):
            raise WebToolsError("搜索服务返回格式不正确")
        return payload

    @staticmethod
    def _deepseek_result(item: dict[str, Any]) -> SearchResult:
        return SearchResult(
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            snippet=str(item.get("snippet") or ""),
            summary=str(item.get("summary") or item.get("snippet") or ""),
            content=str(item.get("content") or ""),
            site_name=item.get("site_name"),
            site_icon=item.get("site_icon"),
            date=item.get("date"),
            authority=item.get("authority"),
            rerank_score=item.get("rerank_score"),
        )

    @staticmethod
    def _tavily_result(item: dict[str, Any]) -> SearchResult:
        content = str(item.get("content") or "")
        return SearchResult(
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            snippet=content,
            summary=content,
            content=content,
        )

    @staticmethod
    def _serper_result(item: dict[str, Any]) -> SearchResult:
        snippet = str(item.get("snippet") or "")
        return SearchResult(
            title=str(item.get("title") or ""),
            url=str(item.get("link") or ""),
            snippet=snippet,
            summary=snippet,
        )

    def _log_event(
        self,
        app: str,
        kind: str,
        value: str,
        result_count: int,
        elapsed_ms: int,
        *,
        ok: bool,
        cached: bool = False,
        status_code: int | None = None,
    ) -> None:
        try:
            config.WEB_TOOLS_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            event = {
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "app": app,
                "kind": kind,
                "value_hash": hashlib.sha256(value.encode("utf-8")).hexdigest()[:16],
                "result_count": result_count,
                "took_ms": elapsed_ms,
                "ok": ok,
                "cached": cached,
            }
            if status_code is not None:
                event["status_code"] = status_code
            with config.WEB_TOOLS_EVENTS_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass


class _WebToolsSecrets:
    def __init__(self) -> None:
        self.store = ProviderSecretStore(config.WEB_TOOLS_SECRETS_PATH)

    def get(self, provider: ProviderId, settings: WebToolsSettings) -> tuple[str, str]:
        saved = self.store.get_secret(f"web_tools.{provider}")
        if saved:
            return saved, "saved"
        if provider == "deepseek":
            legacy = ProviderSecretStore().get_secret("deepseek")
            if legacy:
                self.store.set_secret("web_tools.deepseek", legacy)
                return legacy, "saved"
            env = config.DEEPSEEK_API_KEY
            if env:
                return env, "environment"
        if provider in {"tavily", "serper"}:
            legacy = database.get_companion_setting("search_api_key", "")
            if legacy:
                self.store.set_secret(f"web_tools.{provider}", legacy)
                database.set_companion_setting("search_api_key", "")
                return legacy, "saved"
        env_name = {"tavily": "TAVILY_API_KEY", "serper": "SERPER_API_KEY"}.get(provider)
        env = os.environ.get(env_name or "", "").strip()
        if env:
            return env, "environment"
        return "", "none"

    def set(self, provider: ProviderId, value: str) -> None:
        self.store.set_secret(f"web_tools.{provider}", value)

    def clear(self, provider: ProviderId) -> None:
        self.store.delete_secret(f"web_tools.{provider}")


_SERVICE: WebToolsService | None = None


def get_web_tools_service() -> WebToolsService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = WebToolsService()
    return _SERVICE


def reset_web_tools_service() -> None:
    global _SERVICE
    _SERVICE = None
