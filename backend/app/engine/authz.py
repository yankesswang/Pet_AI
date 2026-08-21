"""VetLink AI — 飼主授權憑證 (owner authorization grant)。

為什麼需要這個模組：

  `VetSearchRequest.owner_authorized` 原本預設為 True，且由 request body 傳入。
  也就是說「飼主已授權」這件事是**呼叫端自己宣告**的 —— 畫面上的 QR Code 是
  漂亮的流程示意，但後端沒有任何東西可以驗證授權真的發生過。個案資料的存取
  控制若建立在自我宣告上，等於沒有存取控制。

因此授權改成一張**伺服器簽發、伺服器驗證**的憑證：

  * 預設未授權 —— 沒有憑證就是沒有授權，不存在「預設為真」。
  * 有時效     —— 逾期自動失效 (expires_at)。
  * 一次性     —— 用過即記錄，重放會被拒 (jti + 已用集合)。
  * 綁定個案   —— 綁 case_audit_id、飼主、獸醫與允許範圍，換個個案就無效。
  * 可撤回     —— 飼主隨時可撤銷，撤銷後立即失效。
  * 有使用紀錄 —— 每次驗證都留下軌跡，供稽核回查。

簽章採 HMAC-SHA256。正式環境應改為非對稱簽章並由 KMS 保管金鑰；
此處以環境變數 `VETLINK_GRANT_SECRET` 提供，未設定時產生隨機臨時金鑰
（重啟即失效，可避免把預設密鑰當成正式密鑰使用）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# 預設有效期：授權掃碼後 15 分鐘內有效。個案存取是敏感操作，不宜長效。
DEFAULT_TTL_SECONDS = 15 * 60

# 允許的授權範圍代碼。個案存取與一般產品檢索**分開授權**，
# 拿到個案授權不等於可以無限制檢索產品，反之亦然。
SCOPE_CASE_READ = "case:read"        # 讀取該個案的結構化資料與回答護照
SCOPE_PRODUCT_SEARCH = "product:search"  # 以該個案為脈絡進行產品檢索

VALID_SCOPES = {SCOPE_CASE_READ, SCOPE_PRODUCT_SEARCH}


def _secret() -> bytes:
    raw = (os.environ.get("VETLINK_GRANT_SECRET") or "").strip()
    if raw:
        return raw.encode("utf-8")
    # 未設定金鑰時不使用固定預設值 —— 固定預設值等於沒有簽章。
    global _EPHEMERAL_SECRET
    if _EPHEMERAL_SECRET is None:
        _EPHEMERAL_SECRET = secrets.token_bytes(32)
    return _EPHEMERAL_SECRET


_EPHEMERAL_SECRET: Optional[bytes] = None


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


@dataclass
class GrantResult:
    """驗證結果。`authorized` 為 False 時 `reason_zh` 說明原因。"""

    authorized: bool
    reason_zh: str = ""
    grant_id: Optional[str] = None
    case_audit_id: Optional[str] = None
    scopes: List[str] = field(default_factory=list)
    owner_ref: Optional[str] = None
    vet_ref: Optional[str] = None
    expires_at: Optional[float] = None


class GrantStore:
    """簽發、驗證、撤銷授權憑證。

    以行程內狀態記錄「已使用」與「已撤銷」的憑證 —— Demo 規模足夠，
    正式環境應改為共用儲存 (Redis/DB) 以支援多實例部署。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._used: Dict[str, float] = {}       # jti -> 使用時間
        self._revoked: Dict[str, float] = {}    # jti -> 撤銷時間
        self._usage_log: List[Dict[str, Any]] = []

    # -- 簽發 ----------------------------------------------------------
    def issue(
        self,
        *,
        case_audit_id: str,
        owner_ref: str,
        vet_ref: str,
        scopes: Sequence[str],
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> str:
        """簽發一張綁定個案的授權憑證，回傳可放進 QR Code 的字串。"""
        bad = [s for s in scopes if s not in VALID_SCOPES]
        if bad:
            raise ValueError(f"未知的授權範圍: {bad}")
        if not case_audit_id:
            raise ValueError("授權必須綁定 case_audit_id")

        now = time.time()
        payload = {
            "jti": uuid.uuid4().hex,
            "case_audit_id": case_audit_id,
            "owner_ref": owner_ref,
            "vet_ref": vet_ref,
            "scopes": sorted(set(scopes)),
            "issued_at": now,
            "expires_at": now + max(1, int(ttl_seconds)),
        }
        body = _b64e(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        sig = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{sig}"

    # -- 驗證 ----------------------------------------------------------
    def verify(
        self,
        token: Optional[str],
        *,
        case_audit_id: Optional[str],
        required_scope: str,
        vet_ref: Optional[str] = None,
        consume: bool = True,
    ) -> GrantResult:
        """驗證憑證。任何一項不成立都回傳未授權 —— 預設拒絕。"""
        if not token:
            return GrantResult(False, "未提供飼主授權憑證，預設為未授權。")

        try:
            body, sig = token.split(".", 1)
        except ValueError:
            return GrantResult(False, "授權憑證格式錯誤。")

        expected = _b64e(
            hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
        )
        # 常數時間比對，避免簽章比對的時序側通道
        if not hmac.compare_digest(sig, expected):
            return GrantResult(False, "授權憑證簽章無效，可能遭竄改或非本系統簽發。")

        try:
            payload = json.loads(_b64d(body))
        except Exception:  # noqa: BLE001
            return GrantResult(False, "授權憑證內容無法解析。")

        jti = payload.get("jti")
        now = time.time()

        if now > float(payload.get("expires_at") or 0):
            return GrantResult(False, "授權憑證已逾有效期，請重新取得飼主授權。")

        with self._lock:
            if jti in self._revoked:
                return GrantResult(False, "授權已被飼主撤回。")
            if consume and jti in self._used:
                return GrantResult(False, "授權憑證已被使用過，不得重放。")

        # 綁定檢查：換個個案就無效
        if case_audit_id and payload.get("case_audit_id") != case_audit_id:
            return GrantResult(False, "授權憑證綁定的個案與本次請求不符。")

        scopes = list(payload.get("scopes") or [])
        if required_scope not in scopes:
            return GrantResult(
                False,
                f"授權範圍不含「{required_scope}」，個案存取與產品檢索須分別授權。",
            )

        # 綁定獸醫：憑證是簽給特定獸醫的，不得轉用
        if vet_ref and payload.get("vet_ref") and payload["vet_ref"] != vet_ref:
            return GrantResult(False, "授權憑證綁定的獸醫與本次請求不符。")

        with self._lock:
            if consume:
                self._used[jti] = now
            self._usage_log.append(
                {
                    "grant_id": jti,
                    "case_audit_id": payload.get("case_audit_id"),
                    "vet_ref": payload.get("vet_ref"),
                    "scope": required_scope,
                    "used_at": now,
                }
            )

        return GrantResult(
            authorized=True,
            reason_zh="授權憑證驗證通過。",
            grant_id=jti,
            case_audit_id=payload.get("case_audit_id"),
            scopes=scopes,
            owner_ref=payload.get("owner_ref"),
            vet_ref=payload.get("vet_ref"),
            expires_at=payload.get("expires_at"),
        )

    # -- 撤回 ----------------------------------------------------------
    def revoke(self, grant_id: str) -> bool:
        """飼主撤回授權。已撤回的憑證立即失效。"""
        with self._lock:
            if grant_id in self._revoked:
                return False
            self._revoked[grant_id] = time.time()
            return True

    def usage_log(self, case_audit_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """授權使用紀錄，供稽核回查。"""
        with self._lock:
            if case_audit_id is None:
                return list(self._usage_log)
            return [r for r in self._usage_log if r["case_audit_id"] == case_audit_id]


_STORE: Optional[GrantStore] = None


def get_grant_store() -> GrantStore:
    global _STORE
    if _STORE is None:
        _STORE = GrantStore()
    return _STORE
