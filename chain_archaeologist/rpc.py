from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class RpcError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


@dataclass
class RpcSettings:
    host: str = "127.0.0.1"
    port: int = 8332
    user: str = ""
    password: str = ""
    cookie_file: str = ""
    timeout: int = 30
    use_https: bool = False


class RpcClient:
    def __init__(self, settings: RpcSettings) -> None:
        self.settings = settings
        scheme = "https" if settings.use_https else "http"
        self.url = f"{scheme}://{settings.host}:{settings.port}/"
        self._request_id = 0

    def _credentials(self) -> tuple[str, str]:
        if self.settings.user or self.settings.password:
            return self.settings.user, self.settings.password
        if self.settings.cookie_file:
            cookie = Path(self.settings.cookie_file)
            if cookie.exists():
                raw = cookie.read_text(encoding="utf-8").strip()
                if ":" in raw:
                    return tuple(raw.split(":", 1))  # type: ignore[return-value]
        return "", ""

    def _post(self, payload: bytes) -> Any:
        headers = {"Content-Type": "application/json", "User-Agent": "Blockchain-Archaeologist/0.1"}
        user, password = self._credentials()
        if user or password:
            token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        req = urllib.request.Request(self.url, data=payload, headers=headers, method="POST")
        context = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=self.settings.timeout, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body)
                err = parsed.get("error") or {}
                raise RpcError(err.get("message", body), err.get("code"), err.get("data")) from exc
            except json.JSONDecodeError:
                raise RpcError(f"HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RpcError(f"RPC connection failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RpcError("RPC request timed out") from exc

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        self._request_id += 1
        body = {"jsonrpc": "1.0", "id": self._request_id, "method": method, "params": params or []}
        result = self._post(json.dumps(body).encode("utf-8"))
        if result.get("error"):
            err = result["error"]
            raise RpcError(err.get("message", "Unknown RPC error"), err.get("code"), err.get("data"))
        return result.get("result")

    def batch(self, calls: Iterable[tuple[str, list[Any]]]) -> list[Any]:
        payload: list[dict[str, Any]] = []
        ids: list[int] = []
        for method, params in calls:
            self._request_id += 1
            ids.append(self._request_id)
            payload.append({"jsonrpc": "1.0", "id": self._request_id, "method": method, "params": params})
        if not payload:
            return []
        response = self._post(json.dumps(payload).encode("utf-8"))
        by_id = {item.get("id"): item for item in response}
        results: list[Any] = []
        for request_id in ids:
            item = by_id.get(request_id)
            if item is None:
                raise RpcError(f"Missing RPC batch response for id {request_id}")
            if item.get("error"):
                err = item["error"]
                raise RpcError(err.get("message", "Unknown RPC error"), err.get("code"), err.get("data"))
            results.append(item.get("result"))
        return results
