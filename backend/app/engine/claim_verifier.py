"""VetLink AI — 主張驗證器 (提案 §7.1 / §八).

檢查每一項醫療或產品主張是否被檢索到的來源段落直接支持。
未被支持 → 刪除該主張，或整體拒答。**不呼叫 LLM。**

驗證邏輯：主張的內容詞必須有足夠比例出現在候選來源段落中 (詞彙涵蓋度)，
並且該段落必須通過效期與審核狀態閘門。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..models import Claim, ClaimBinding, SourcePassage

# 主張型別中，必須有來源支持者
CLAIMS_REQUIRING_EVIDENCE = {"medical", "product"}

# 涵蓋度門檻：主張的內容詞有多少比例需出現在來源段落
COVERAGE_THRESHOLD = 0.55

STOPWORDS = {
    "的", "了", "是", "在", "與", "及", "和", "或", "而", "並", "也", "都", "就",
    "請", "可", "會", "有", "為", "以", "於", "其", "此", "該", "等", "之",
    "我", "你", "牠", "它", "您", "們", "個", "這", "那", "很", "更", "最",
    "建議", "可能", "應該", "需要", "如果", "由於", "因此", "屬於",
}


def _content_tokens(text: str) -> List[str]:
    """抽出內容詞：英數詞 + 中文 2-gram，去除停用詞。"""
    tokens: List[str] = []
    for chunk in re.findall(r"[A-Za-z0-9]+|[一-鿿]+", text):
        if chunk[0].isascii():
            tokens.append(chunk.lower())
            continue
        for i in range(len(chunk) - 1):
            bigram = chunk[i: i + 2]
            if bigram in STOPWORDS:
                continue
            if bigram[0] in STOPWORDS and bigram[1] in STOPWORDS:
                continue
            tokens.append(bigram)
    return tokens


def coverage(claim_text: str, passage_text: str) -> float:
    """主張內容詞在來源段落中的涵蓋比例，0.0 ~ 1.0。"""
    claim_tokens = _content_tokens(claim_text)
    if not claim_tokens:
        return 0.0
    unique = list(dict.fromkeys(claim_tokens))
    hit = sum(1 for t in unique if t in passage_text.lower() or t in passage_text)
    return hit / len(unique)


def retention(rewritten_text: str, source_text: str) -> float:
    """來源內容詞在改寫後仍保留的比例，0.0 ~ 1.0。

    與 `coverage` 方向相反，用途也不同：

    * `coverage(主張, 來源)` 問「這個主張有多少比例能在來源找到」——
      用於**主張驗證**，分母是主張，加入來源沒有的內容會扣分。
    * `retention(改寫, 原文)` 問「原文的內容有多少比例還在」——
      用於**改寫檢查**，分母是原文，只有刪掉原文內容才會扣分。

    為什麼改寫不能用 coverage：內容詞以中文 2-gram 表示，插入一個虛詞
    （「是」→「都是」）就會產生「都是」這種原文不存在的邊界 bigram。
    改寫本來就被要求「把長句拆短、加上白話說明」，必然插入虛詞，
    於是 coverage 會系統性地懲罰它自己要求的行為 —— 實測 24 段真實改寫
    有 15 段因此被丟棄，等於這個功能永遠付出 LLM 成本卻拿不到結果。

    「加入了來源沒有的內容」這件事改由 `safety_preserved`（不得刪除安全
    指示）、`no_new_numbers`（不得新增數字）與 `policy.redact`（劑量、
    確診、購買等違規）三道確定性檢查負責，比詞彙比例更直接。
    """
    source_tokens = _content_tokens(source_text)
    if not source_tokens:
        return 0.0
    unique = list(dict.fromkeys(source_tokens))
    kept = sum(1 for t in unique if t in rewritten_text.lower() or t in rewritten_text)
    return kept / len(unique)


@dataclass
class VerificationResult:
    bindings: List[ClaimBinding] = field(default_factory=list)
    verified_claims: List[Claim] = field(default_factory=list)
    deleted_claims: List[Claim] = field(default_factory=list)
    should_refuse: bool = False
    refusal_detail: str = ""

    @property
    def all_supported(self) -> bool:
        return not self.deleted_claims

    @property
    def citation_accuracy(self) -> float:
        """主張—段落綁定完整率：主張中確實綁定到有效來源的比例。

        **不是臨床正確率。** 主張直接取自已審核段落原文，因此這個比率
        在建構上幾乎必然接近 100%。它量的是「輸出不會出現沒有來源的內容」，
        不是獸醫認定的語意正確。臨床有效性須由獸醫盲審取得。
        """
        total = len(self.verified_claims) + len(self.deleted_claims)
        if total == 0:
            return 1.0
        return len(self.verified_claims) / total


class ClaimVerifier:
    """主張驗證器。"""

    def __init__(self, coverage_threshold: float = COVERAGE_THRESHOLD):
        self.coverage_threshold = coverage_threshold

    def verify_claim(
        self, claim: Claim, candidates: Sequence[SourcePassage]
    ) -> Tuple[bool, List[SourcePassage], str]:
        """回傳 (是否被支持, 支持段落, 說明)。"""
        # 效期與審核閘門
        usable: List[SourcePassage] = []
        expired_hits: List[str] = []
        for p in candidates:
            if p.is_expired:
                expired_hits.append(p.passage_id)
                continue
            if p.review_status != "approved":
                continue
            usable.append(p)

        if not usable:
            note = "無通過效期／審核閘門的來源段落"
            if expired_hits:
                note += f"（已排除過期段落: {', '.join(expired_hits)}）"
            return False, [], note

        # 若主張已明示 supporting_passage_ids，僅在該範圍內驗證
        if claim.supporting_passage_ids:
            usable = [p for p in usable if p.passage_id in claim.supporting_passage_ids]
            if not usable:
                return False, [], "指定的支持段落不存在或未通過效期閘門"

        supporting: List[SourcePassage] = []
        best = 0.0
        for p in usable:
            c = coverage(claim.text, p.text)
            best = max(best, c)
            if c >= self.coverage_threshold:
                supporting.append(p)

        if supporting:
            return True, supporting, f"詞彙涵蓋度 {best:.2f} ≥ 門檻 {self.coverage_threshold}"
        return False, [], f"最佳涵蓋度 {best:.2f} < 門檻 {self.coverage_threshold}，無段落直接支持"

    def verify(
        self,
        claims: Sequence[Claim],
        candidates: Sequence[SourcePassage],
        refuse_if_any_unsupported: bool = False,
    ) -> VerificationResult:
        """驗證整組主張。

        refuse_if_any_unsupported=True 時，任一主張無來源即整體拒答；
        否則僅刪除該主張 (提案：『刪除該主張、標示資料不足，或拒絕回答』)。
        """
        result = VerificationResult()

        for claim in claims:
            if claim.claim_type not in CLAIMS_REQUIRING_EVIDENCE:
                # 程序性／政策性陳述不需醫學來源，但仍列入護照
                claim.verified = True
                claim.verification_note = "非醫療／產品主張，不需來源驗證"
                result.verified_claims.append(claim)
                result.bindings.append(
                    ClaimBinding(
                        claim_id=claim.claim_id,
                        claim_text=claim.text,
                        claim_type=claim.claim_type,
                        supported=True,
                        passages=[],
                        note=claim.verification_note,
                    )
                )
                continue

            supported, passages, note = self.verify_claim(claim, candidates)
            claim.verified = supported
            claim.verification_note = note

            result.bindings.append(
                ClaimBinding(
                    claim_id=claim.claim_id,
                    claim_text=claim.text,
                    claim_type=claim.claim_type,
                    supported=supported,
                    passages=list(passages),
                    note=note,
                )
            )
            if supported:
                claim.supporting_passage_ids = [p.passage_id for p in passages]
                result.verified_claims.append(claim)
            else:
                result.deleted_claims.append(claim)

        if result.deleted_claims:
            ids = ", ".join(c.claim_id for c in result.deleted_claims)
            if refuse_if_any_unsupported:
                result.should_refuse = True
                result.refusal_detail = f"下列主張無有效來源支持，依證據資格規則拒答: {ids}"
            else:
                result.refusal_detail = f"下列主張因無有效來源支持已被刪除: {ids}"
                # 醫療/產品主張全數落空 → 沒有可輸出的內容，必須拒答
                medical = [c for c in claims if c.claim_type in CLAIMS_REQUIRING_EVIDENCE]
                if medical and all(not c.verified for c in medical):
                    result.should_refuse = True
                    result.refusal_detail = "所有醫療／產品主張皆無有效來源支持，拒絕回答並交回獸醫。"

        return result

    def strip_unsupported(self, result: VerificationResult, texts: List[str]) -> List[str]:
        """從輸出文字中移除被刪除主張對應的句子。"""
        if not result.deleted_claims:
            return texts
        deleted_texts = {c.text.strip() for c in result.deleted_claims}
        kept: List[str] = []
        for t in texts:
            if t.strip() in deleted_texts:
                continue
            kept.append(t)
        return kept


_VERIFIER: Optional[ClaimVerifier] = None


def get_verifier() -> ClaimVerifier:
    global _VERIFIER
    if _VERIFIER is None:
        _VERIFIER = ClaimVerifier()
    return _VERIFIER


def make_claim(claim_id: str, text: str, claim_type: str = "medical",
               passage_ids: Optional[List[str]] = None) -> Claim:
    return Claim(
        claim_id=claim_id,
        text=text,
        claim_type=claim_type,
        supporting_passage_ids=list(passage_ids or []),
    )
