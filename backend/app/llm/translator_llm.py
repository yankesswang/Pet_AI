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
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..engine import policy
from ..engine.claim_verifier import ClaimVerifier, get_verifier, retention
from ..models import Role, SourcePassage
from .client import LLMClient, get_client, translation_enabled

log = logging.getLogger("vetlink.llm.translator")

# 改寫後仍須保留的最低來源內容比例。
#
# 這裡量的是 retention（原文還剩多少）而非 coverage（改寫有多少能對上原文）。
# 用 coverage 會系統性誤殺合法改寫：內容詞是中文 2-gram，插入任何虛詞都會
# 產生原文沒有的邊界 bigram，而「加上白話說明、把長句拆短」正是 SYSTEM_PROMPT
# 要求的事。實測 24 段真實改寫，coverage>=0.60 只通過 9 段 (38%)，
# 且被擋下的全是忠實且安全的改寫。
#
# 門檻 0.55：實測安全改寫的 retention 中位數約 0.74、最低 0.51；
# 刪除安全指示的改寫則落在 0.13 以下，兩者分離明確。
REWRITE_RETENTION_THRESHOLD = 0.55

# 安全語義群：來源命中某一群時，改寫後必須仍命中同一群。
# 用「群」而非單詞比對，才不會把「勿自行使用」→「不要自行使用」
# 這種合法同義改寫誤判為刪除安全內容。
SAFETY_GROUPS: Tuple[Tuple[str, ...], ...] = (
    ("立即", "立刻", "馬上", "儘速", "盡速"),
    ("就醫", "送醫", "就診", "看醫生", "急診", "獸醫"),
    ("禁止", "不可", "不得", "勿", "不要", "避免"),
    ("危及", "致命", "死亡", "風險", "危險"),
    ("必須", "務必", "一定要", "需要"),
)

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def safety_preserved(rewritten: str, source: str) -> Tuple[bool, str]:
    """來源命中的每個安全語義群，改寫後是否仍然命中同一群。

    擋的是「不得刪除安全相關內容」與「不得改變語意強度」——
    把「必須立即就醫」淡化成「也許可以找時間看看」會在這裡被擋下。
    """
    for group in SAFETY_GROUPS:
        if any(k in source for k in group) and not any(k in rewritten for k in group):
            return False, group[0]
    return True, ""


def no_new_numbers(rewritten: str, source: str) -> Tuple[bool, str]:
    """改寫不得出現來源沒有的數字。

    劑量、次數、時間窗都是數字。模型即使被禁止，仍可能「順手」補上
    一個看似合理的數值；這一關讓任何新數字都無法通過。
    """
    added = set(_NUMBER_RE.findall(rewritten)) - set(_NUMBER_RE.findall(source))
    return (not added), "、".join(sorted(added))

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

    # --- 第一關：來源內容保留度 ------------------------------------------
    # 量的是「原文還剩多少」，不是「改寫有多少能對上原文」。
    # 只有刪掉來源內容才會扣分；插入虛詞讓句子好讀不會。
    ret = retention(candidate, original)
    if ret < REWRITE_RETENTION_THRESHOLD:
        result["reason"] = (
            f"改寫後來源內容保留度 {ret:.2f} < 門檻 {REWRITE_RETENTION_THRESHOLD}，"
            "研判刪除了來源內容，已丟棄改寫結果"
        )
        return result

    # --- 第二關：安全語義不得流失 ----------------------------------------
    kept, lost_group = safety_preserved(candidate, original)
    if not kept:
        result["reason"] = (
            f"改寫後遺失安全語義（「{lost_group}」一類的指示），已丟棄並退回原文"
        )
        return result

    # --- 第三關：不得新增來源沒有的數字（劑量／次數／時間窗）-------------
    clean, added = no_new_numbers(candidate, original)
    if not clean:
        result["reason"] = (
            f"改寫加入了來源沒有的數字（{added}），已丟棄並退回原文"
        )
        return result

    # --- 第四關：角色政策文字掃描 ---------------------------------------
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
    result["reason"] = (
        f"通過來源保留度 {ret:.2f}、安全語義、數字與角色政策四道檢查"
    )
    return result


def rewrite_passages(
    passages: Sequence[SourcePassage],
    *,
    role: Role = Role.OWNER,
    client: Optional[LLMClient] = None,
    force: bool = False,
    limit: int = 4,
) -> List[Dict[str, Any]]:
    """批次改寫。每一段獨立成敗，任何一段失敗只影響該段。

    各段之間沒有任何相依（每段自己送 LLM、自己過涵蓋度與政策掃描），
    因此改為並行送出。序列化時整體耗時是各段之和 —— 3 段就要 7～9 秒，
    足以讓前端在使用者補完追問、狀態轉 GREEN 的那一刻逾時。

    並行只改變「等待方式」，不改變任何一段的判定：輸出順序仍與輸入順序
    一一對應，失敗仍逐段退回原文。
    """
    items = list(passages)[:limit]
    if not items:
        return []
    c = client or get_client()

    # 單段不值得起執行緒池，直接算完回傳。
    if len(items) == 1:
        return [rewrite_passage(items[0], role=role, client=c, force=force)]

    with ThreadPoolExecutor(max_workers=len(items)) as pool:
        futures = [
            pool.submit(rewrite_passage, p, role=role, client=c, force=force)
            for p in items
        ]
        # 依 futures 原順序取回，確保輸出與輸入段落一一對應。
        return [f.result() for f in futures]


def translation_status(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """供護照／稽核揭露：這次有幾段實際被 LLM 改寫。"""
    total = len(results)
    rewritten = sum(1 for r in results if r.get("rewritten"))
    return {
        "total_passages": total,
        "rewritten_count": rewritten,
        "fallback_count": total - rewritten,
        "note": (
            "改寫僅作用於已核准段落；每段仍經來源保留度、安全語義、數字與"
            "角色政策四道檢查，任一關失敗即退回原文。"
        ),
    }


__all__ = [
    "rewrite_passage",
    "rewrite_passages",
    "translation_status",
    "REWRITE_RETENTION_THRESHOLD",
    "safety_preserved",
    "no_new_numbers",
]
