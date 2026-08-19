"""VetLink AI — OpenAI 用戶端包裝 (提案 §7.1).

**安全邊界**：本模組只提供「呼叫模型並取回文字」的能力，不做任何閘門判定。
Evidence Gate 的四狀態、規則評估、主張驗證與效期判定完全不經過這裡。

設計原則：
  1. **永不向請求路徑拋出例外**。任何失敗（無金鑰、逾時、API 錯誤、
     輸出非預期）一律回傳 None，由呼叫端退回既有確定性路徑。
  2. **短逾時 + 一次重試**，避免 Demo 因網路而卡住。
  3. **功能旗標預設 off**，未設定環境變數時系統行為與接入前完全相同。

環境變數：
    OPENAI_API_KEY                 OpenAI 金鑰；未設定則整個 LLM 層停用
    OPENAI_MODEL                   模型名稱，預設 gpt-4o-mini
    OPENAI_BASE_URL                （選用）自架或代理端點
    VETLINK_LLM_STRUCTURING        on|off，症狀結構化器是否啟用 LLM，預設 off
    VETLINK_LLM_TRANSLATION        on|off，衛教語言轉譯是否啟用 LLM，預設 off
    VETLINK_LLM_TIMEOUT            單次呼叫逾時秒數，預設 10
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

log = logging.getLogger("vetlink.llm")

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_RETRIES = 1


# --------------------------------------------------------------------------
# 功能旗標
# --------------------------------------------------------------------------
def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("on", "1", "true", "yes", "enabled")


def api_key() -> Optional[str]:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    return key or None


def model_name() -> str:
    return (os.environ.get("OPENAI_MODEL") or "").strip() or DEFAULT_MODEL


def timeout_seconds() -> float:
    try:
        return float(os.environ.get("VETLINK_LLM_TIMEOUT") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def structuring_enabled() -> bool:
    """症狀結構化器是否使用 LLM 輔助（提案 §7.1：部分；需 Schema 驗證）。"""
    return _flag("VETLINK_LLM_STRUCTURING", False)


def translation_enabled() -> bool:
    """衛教語言轉譯是否使用 LLM（提案 §7.1：限白名單資料）。"""
    return _flag("VETLINK_LLM_TRANSLATION", False)


def llm_available() -> bool:
    """是否具備實際呼叫模型的條件。"""
    return api_key() is not None


def llm_status() -> Dict[str, Any]:
    """供 /api/health 揭露的 LLM 狀態。

    注意：不論此區塊內容為何，`llm_in_gate_path` 永遠為 False —
    LLM 只在症狀結構化與語言轉譯兩處出現，兩者的輸出都必須先通過
    Schema 驗證／主張驗證，才可能進入閘門或回傳給使用者。
    """
    key_present = api_key() is not None
    structuring = structuring_enabled()
    translation = translation_enabled()
    return {
        "enabled": key_present and (structuring or translation),
        "model": model_name(),
        "structuring": "on" if structuring else "off",
        "translation": "on" if translation else "off",
        "key_present": key_present,
    }


# --------------------------------------------------------------------------
# 用戶端
# --------------------------------------------------------------------------
class LLMClient:
    """OpenAI Chat Completions 的最小包裝。

    所有公開方法失敗時回傳 None，不拋出例外。
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.model = model or model_name()
        self.timeout = timeout if timeout is not None else timeout_seconds()
        self.max_retries = max_retries
        self._client: Any = None
        self._init_failed = False

    # -- 內部：延遲建立 SDK 用戶端，讓沒有金鑰時也能安全 import ------------
    def _ensure_client(self) -> Any:
        if self._client is not None or self._init_failed:
            return self._client
        key = api_key()
        if key is None:
            self._init_failed = True
            return None
        try:
            from openai import OpenAI  # 延遲載入，避免無金鑰環境的匯入成本

            kwargs: Dict[str, Any] = {
                "api_key": key,
                "timeout": self.timeout,
                # 重試交由 SDK 處理；再加上我們自己的一輪，最多兩次嘗試
                "max_retries": 0,
            }
            base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip()
            if base_url:
                kwargs["base_url"] = base_url
            self._client = OpenAI(**kwargs)
        except Exception as exc:  # pragma: no cover - 需真實 SDK 失敗才會走到
            log.warning("[llm] OpenAI 用戶端建立失敗，已停用 LLM 路徑: %s", exc)
            self._init_failed = True
            self._client = None
        return self._client

    @property
    def available(self) -> bool:
        return api_key() is not None

    # -- 公開：純文字補全 -------------------------------------------------
    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 700,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> Optional[str]:
        """回傳模型輸出文字；任何失敗一律回傳 None。"""
        client = self._ensure_client()
        if client is None:
            return None

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                resp = client.chat.completions.create(**kwargs)
                choices = getattr(resp, "choices", None) or []
                if not choices:
                    return None
                content = getattr(choices[0].message, "content", None)
                if not content or not str(content).strip():
                    return None
                return str(content)
            except Exception as exc:
                log.warning(
                    "[llm] 呼叫失敗 (%d/%d)，將退回確定性路徑: %s",
                    attempt + 1,
                    attempts,
                    exc,
                )
                if attempt + 1 >= attempts:
                    return None
        return None

    # -- 公開：JSON 補全 --------------------------------------------------
    def complete_json(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 700,
    ) -> Optional[Dict[str, Any]]:
        """要求模型輸出 JSON 物件並解析；解析失敗回傳 None。

        **這裡不做任何語意信任**：解析成功只代表格式合法，內容仍須由
        呼叫端以 Pydantic schema 驗證後才可使用。
        """
        raw = self.complete(
            system=system, user=user, max_tokens=max_tokens, json_mode=True
        )
        if raw is None:
            return None
        return parse_json_object(raw)


def parse_json_object(raw: str) -> Optional[Dict[str, Any]]:
    """從模型輸出中取出 JSON 物件。容忍 ```json 圍欄與前後贅字。"""
    if not raw:
        return None
    text = raw.strip()

    # 去掉 markdown 圍欄
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        pass

    # 退而求其次：抓第一個平衡的大括號區塊
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start: i + 1])
                    return obj if isinstance(obj, dict) else None
                except (ValueError, TypeError):
                    return None
    return None


# --------------------------------------------------------------------------
# 單例
# --------------------------------------------------------------------------
_CLIENT: Optional[LLMClient] = None


def get_client(reload: bool = False) -> LLMClient:
    global _CLIENT
    if _CLIENT is None or reload:
        _CLIENT = LLMClient()
    return _CLIENT


def reset_client() -> None:
    """測試用：清除單例，讓環境變數變更生效。"""
    global _CLIENT
    _CLIENT = None


__all__ = [
    "LLMClient",
    "get_client",
    "reset_client",
    "llm_status",
    "llm_available",
    "structuring_enabled",
    "translation_enabled",
    "model_name",
    "api_key",
    "parse_json_object",
]
