"""Small DeepSeek-compatible JSON client for data enrichment scripts.

The project deliberately avoids adding an SDK dependency here. The scripts use
only Python's standard library and talk to DeepSeek's `/chat/completions`
endpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clamp_float(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, f))


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str
    base_url: str
    timeout: int
    retries: int
    response_format: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=(
                os.getenv("DEEPSEEK_API_KEY")
                or os.getenv("LLM_API_KEY", "")
            ),
            model=(
                os.getenv("DEEPSEEK_MODEL")
                or os.getenv("LLM_MODEL")
                or "deepseek-chat"
            ),
            base_url=(
                os.getenv("DEEPSEEK_BASE_URL")
                or os.getenv("LLM_BASE_URL")
                or "https://api.deepseek.com"
            ).rstrip("/"),
            timeout=int(os.getenv("LLM_TIMEOUT", "90")),
            retries=int(os.getenv("LLM_RETRIES", "4")),
            response_format=os.getenv("LLM_RESPONSE_FORMAT", "json_object"),
        )


class JsonlCache:
    """Append-only JSONL cache keyed by a stable request hash."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = row.get("key")
                if key:
                    self.rows[key] = row

    def get(self, key: str) -> dict | None:
        row = self.rows.get(key)
        return row.get("value") if row else None

    def set(self, key: str, value: dict, meta: dict | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "key": key,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "meta": meta or {},
            "value": value,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.rows[key] = row


class DeepSeekJsonClient:
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        if not self.config.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY or LLM_API_KEY is required for DeepSeek inference.")

    def chat_json(self, *, system: str, user: str, schema_name: str, schema: dict) -> dict:
        if self.config.response_format == "json_object":
            user = (
                user
                + "\n\n必须只输出一个 JSON Object，不要输出 Markdown。"
                + " 注意：本请求使用 DeepSeek JSON Output 模式，回复内容必须是合法 JSON。"
                + " JSON Object 必须符合下面的字段结构：\n"
                + json.dumps(schema, ensure_ascii=False)
            )
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        if self.config.response_format == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                },
            }
        elif self.config.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        data = self._post("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"Unexpected LLM response shape: {data!r}") from e
        return parse_json_object(content)

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.config.base_url}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")
                last_error = RuntimeError(f"HTTP {e.code}: {detail}")
                if e.code not in (408, 409, 429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError) as e:
                last_error = e

            if attempt < self.config.retries:
                time.sleep(min(2 ** attempt, 12))

        raise RuntimeError(f"LLM request failed after retries: {last_error}")


CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def strip_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_json_object(content: str) -> dict:
    """Parse a JSON object, tolerating common provider wrapping/controls."""
    content = strip_code_fence(CONTROL_CHARS.sub("", content))
    try:
        parsed = json.loads(content, strict=False)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(CONTROL_CHARS.sub("", content[start:end + 1]), strict=False)
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
    return parsed
