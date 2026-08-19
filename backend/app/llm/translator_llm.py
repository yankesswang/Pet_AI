"""VetLink AI — 衛教語言轉譯器 (提案 §7.1「規則決定能不能做，AI 只負責安全轉譯」).

這是提案允許 LLM 介入的第二處。它**不決定要說什麼**，只負責把已經通過
Evidence Gate、效期閘門與角色政策的段落，改寫成飼主更好讀的繁體中文。

    已核准段落（白名單） → [LLM 改寫] → 主張驗證器 → 角色政策掃描 → 輸出
                                            ↓ 失敗
                                        退回原文

安全邊界：
  1. **輸入只能是白名單段落原文**。不提供症狀、不提供產品資料、不提供對話歷史。
  2. 改寫後的每一句仍須通過既有 `ClaimVerifier` —— 涵蓋度不足即代表模型
     加入了來源沒有的內容，該句直接丟棄並改用原文。
  3. 再經 `policy.redact` 掃描角色違規（劑量、購買、確診、停換藥、人藥套用）。
  4. 任何一關失敗 → 回傳原始段落文字，系統行為與未啟用 LLM 時相同。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from ..engine import policy
from ..engine.claim_verifier import ClaimVerifier, coverage, get_verifier
from ..models import Role, SourcePassage
from .client import LLMClient, get_client, translation_enabled

log = logging.getLogger("vetlink.llm.translator")

# 改寫後仍須維持的最低詞彙涵蓋度。刻意高於主張驗證器預設門檻 (0.55)，
# 因為「改寫」本來就該保留來源的內容詞，只調整語氣與句構。
REWRITE_COVERAGE_THRESHOLD = 0.60

SYSTEM_PROMPT = """你是動物醫療衛教內容的「語言轉譯者」。你會拿到一段**已經由獸醫審核通過**的繁體中文衛教文字。

你的唯一工作是讓它更好讀，讓一般飼主看得懂。

嚴格禁止：
1. **不得新增任何來源沒有的資訊**：不得加入藥名、劑量、用法、品牌、購買方式、診斷結論或新的醫學主張。
2. **不得刪除安全相關內容**：時間窗、危險徵兆、就醫指示、禁止事項都必須保留。
3. **不得改變語意強度**：「必須立即就醫」不可改成「建議儘快就醫」。
4. 不得加入標題、編號、emoji 或任何開場白。

允許：把長句拆短、把專有名詞加上白話說明、調整語序讓句子更順。

只輸出改寫後的繁體中文段落本身，不要任何說明。
"""


def _rewrite_one(
    text: str, client: LLMClient, *, max_tokens: int = 500
) -> Optional[str]:
    out = client.complete(
        system=SYSTEM_PROMPT,
        user=text,
        max_tokens=max_tokens,
        temperature=0.2,
    )
    if out is None:
        return None
    cleaned = out.strip()
    if not cleaned:
        return None
    # 模型偶爾會加圍欄或引號
    if cleaned.startswith("```"):
        lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    return cleaned or None


def rewrite_passage(
    passage: SourcePassage,
    *,
    role: Role = Role.OWNER,
    client: Optional[LLMClient] = None,
    verifier: Optional[ClaimVerifier] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """改寫單一段落。

    回傳 dict：
        text          最終輸出文字（改寫成功則為改寫版，否則為原文）
        original      原始段落文字
        rewritten     是否實際採用了 LLM 改寫結果
        passage_id    來源段落編號
        reason        未採用時的原因（供稽核）
    """
    original = passage.text
    result: Dict[str, Any] = {
        "text": original,
        "original": original,
        "rewritten": False,
        "passage_id": passage.passage_id,
        "reason": "",
    }

    # 白名單前置條件：只有通過效期與審核閘門的段落才能進入改寫
    if passage.is_expired:
        result["reason"] = "來源段落已過期，不得作為改寫輸入"
        return result
    if passage.review_status != "approved":
        result["reason"] = f"來源段落審核狀態為 {passage.review_status}，不得改寫"
        return result

    if not force and not translation_enabled():
        result["reason"] = "語言轉譯功能未啟用"
        return result

    c = client or get_client()
    if not force and not c.available:
        result["reason"] = "無可用的 LLM 金鑰"
        return result

    candidate = _rewrite_one(original, c)
    if candidate is None:
        result["reason"] = "LLM 無回應或呼叫失敗，退回原文"
        return result

    # --- 第一關：主張驗證器（涵蓋度）------------------------------------
    cov = coverage(candidate, original)
    if cov < REWRITE_COVERAGE_THRESHOLD:
        result["reason"] = (
            f"改寫後詞彙涵蓋度 {cov:.2f} < 門檻 {REWRITE_COVERAGE_THRESHOLD}，"
            "研判加入了來源未支持的內容，已丟棄改寫結果"
        )
        return result

    # --- 第二關：角色政策文字掃描 ---------------------------------------
    redacted, violations = policy.redact(role, candidate)
    if violations:
        result["reason"] = (
            f"改寫結果觸發角色政策違規（{', '.join(violations)}），已丟棄並退回原文"
        )
        return result
    if not redacted.strip():
        result["reason"] = "改寫結果經政策掃描後為空，退回原文"
        return result

    result["text"] = redacted.strip()
    result["rewritten"] = True
    result["reason"] = f"通過主張驗證（涵蓋度 {cov:.2f}）與角色政策掃描"
    return result


def rewrite_passages(
    passages: Sequence[SourcePassage],
    *,
    role: Role = Role.OWNER,
    client: Optional[LLMClient] = None,
    force: bool = False,
    limit: int = 4,
) -> List[Dict[str, Any]]:
    """批次改寫。每一段獨立成敗，任何一段失敗只影響該段。"""
    out: List[Dict[str, Any]] = []
    c = client or get_client()
    for p in list(passages)[:limit]:
        out.append(rewrite_passage(p, role=role, client=c, force=force))
    return out


def translation_status(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """供護照／稽核揭露：這次有幾段實際被 LLM 改寫。"""
    total = len(results)
    rewritten = sum(1 for r in results if r.get("rewritten"))
    return {
        "total_passages": total,
        "rewritten_count": rewritten,
        "fallback_count": total - rewritten,
        "note": "改寫僅作用於已核准段落；每段仍經主張驗證與角色政策掃描，失敗即退回原文。",
    }


__all__ = [
    "rewrite_passage",
    "rewrite_passages",
    "translation_status",
    "REWRITE_COVERAGE_THRESHOLD",
]
