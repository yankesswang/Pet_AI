"""VetLink AI — 關鍵回歸測試：只靠日期換算才抓得到的過期文件。

**為什麼這組測試最重要**

農業部開放資料母體 13,738 筆中，有 1,503 筆許可證「已逾有效期間，但來源本身
沒有標註 (已失效)」。若系統信任來源的失效標記欄位，這 1,503 筆過期文件會直接
洩漏進回答；唯一能攔下它們的方式是把民國日期換算成西元後與 as-of 日期比較。

真實案例：動物藥入字第07363號「一錠除犬用滴劑（巨型犬）」
    有效期間原文 = "至115年06月30日止"   （沒有任何失效標記）
    民國 115/06/30 → 西元 2026-06-30
    基準日 2026-08-19 → 已過期 50 天

這組測試證明：證據資格檢查會擋下這類文件，也就是說 Evidence Gate 抓得到
**連上游資料源自己都標錯的**過期文件。
"""
from __future__ import annotations

from datetime import date

import pytest

from app.engine.claim_verifier import ClaimVerifier, make_claim
from app.engine.knowledge import KnowledgeBase, compute_expiry, get_kb
from app.engine.state import EvidenceGate, GateContext
from app.models import CheckId, RefusalReason, Role, SourcePassage

# 提案 Demo 的效期基準日
AS_OF = date(2026, 8, 19)

# 真實案例：來源原文完全沒有 "(已失效)" 標記
CASE_07363 = {
    "licence_no": "動物藥入字第07363號",
    "name_zh": "一錠除犬用滴劑（巨型犬）",
    "expiry_date_raw": "至115年06月30日止",  # 注意：無 (已失效) 標記
    "expiry_date_iso": "2026-06-30",
    "expired_by_marker": False,  # 來源說「沒過期」
}


# --------------------------------------------------------------------------
# 1. 日期換算層
# --------------------------------------------------------------------------


def test_roc_date_converts_and_is_expired():
    """民國 115/06/30 = 2026-06-30，早於基準日 2026-08-19 → 過期。"""
    is_expired, unknown = compute_expiry(CASE_07363["expiry_date_iso"], AS_OF)
    assert is_expired is True, "115年06月30日 應判定為已逾效期"
    assert unknown is False


def test_expiry_gate_ignores_source_marker():
    """來源標記說『未失效』，系統仍必須依日期判定為過期。"""
    assert CASE_07363["expired_by_marker"] is False  # 上游資料的說法
    is_expired, _ = compute_expiry(CASE_07363["expiry_date_iso"], AS_OF)
    assert is_expired is True, "系統不得採信來源的失效標記"


def test_missing_expiry_date_is_unknown_not_expired():
    """無有效期間欄位 → 標示待確認，而非誤判為過期。"""
    is_expired, unknown = compute_expiry(None, AS_OF)
    assert is_expired is False
    assert unknown is True


# --------------------------------------------------------------------------
# 2. 證據資格檢查必須擋下這類文件
# --------------------------------------------------------------------------


def _passage_from_case(case: dict) -> SourcePassage:
    """把 07363 案例組成一段可被引用的來源段落。"""
    is_expired, _ = compute_expiry(case["expiry_date_iso"], AS_OF)
    return SourcePassage(
        passage_id=f"PROD-{case['licence_no']}",
        doc_id=f"DOC-{case['licence_no']}",
        version="1.0",
        text=f"許可證字號：{case['licence_no']}；品名：{case['name_zh']}；"
        f"核准適應症：犬用體外寄生蟲防治。",
        expiry_date_iso=case["expiry_date_iso"],
        is_expired=is_expired,
        review_status="approved",
        species_scope=["dog"],
        licence_no=case["licence_no"],
    )


def test_evidence_check_blocks_date_only_expired_document():
    """核心斷言：證據資格檢查擋下無失效標記、僅日期已過期的文件。"""
    passage = _passage_from_case(CASE_07363)
    assert passage.is_expired is True, "段落應已由日期換算標為過期"

    claim = make_claim(
        "C01",
        f"{CASE_07363['name_zh']}核准用於犬隻體外寄生蟲防治。",
        claim_type="product",
    )

    gate = EvidenceGate()
    ctx = GateContext(
        facts={"species": "dog", "role": "vet", "scenarios": ["皮膚耳部"], "symptoms": []},
        role=Role.VET,
        vet_verified=True,
        claims=[claim],
        candidate_passages=[passage],
    )
    evidence = gate.check_evidence(ctx)

    # 唯一來源已過期 → 證據資格不通過
    assert evidence.passed is False
    assert evidence.refusal_reason == RefusalReason.INSUFFICIENT_EVIDENCE
    assert any("效期閘門排除" in n for n in evidence.notes)


def test_claim_verifier_refuses_when_only_source_is_date_only_expired():
    """主張驗證器：唯一來源過期 → 該主張無法被支持。"""
    passage = _passage_from_case(CASE_07363)
    claim = make_claim("C01", CASE_07363["name_zh"] + "核准用於犬隻。", claim_type="product")

    supported, passages, note = ClaimVerifier().verify_claim(claim, [passage])
    assert supported is False
    assert passages == []
    assert "效期" in note


def test_full_gate_refuses_with_only_expired_evidence():
    """端到端：只有過期來源時，閘門必須拒答而非降級輸出。"""
    passage = _passage_from_case(CASE_07363)
    claim = make_claim("C01", CASE_07363["name_zh"] + "核准用於犬隻。", claim_type="product")

    gate = EvidenceGate()
    decision = gate.decide(
        GateContext(
            facts={"species": "dog", "role": "vet", "scenarios": ["皮膚耳部"], "symptoms": []},
            role=Role.VET,
            vet_verified=True,
            claims=[claim],
            candidate_passages=[passage],
        )
    )
    assert decision.refusal_reason == RefusalReason.INSUFFICIENT_EVIDENCE
    assert decision.product_retrieval_halted is True
    ev = decision.check(CheckId.EVIDENCE)
    assert ev is not None and ev.passed is False


# --------------------------------------------------------------------------
# 3. 真實資料集中的同類案例
# --------------------------------------------------------------------------


def test_real_dataset_contains_date_only_expired_records():
    """demo_products.json 中確實存在此類文件，且全數被系統標為過期。"""
    kb = get_kb()
    disagreements = kb.marker_disagreements
    assert disagreements, "資料集應含『來源無標記但日期已過期』的案例"

    for rec in disagreements:
        # 上游來源的原文沒有失效標記
        raw = rec.get("expiry_date_raw") or ""
        assert "已失效" not in raw, f"{rec['licence_no']} 原文不應有失效標記"
        # 但系統仍判定為過期
        is_expired, _ = compute_expiry(rec["expiry_date_iso"], AS_OF)
        assert is_expired is True


def test_date_only_expired_passages_never_reach_valid_pool():
    """這類文件的段落絕不可出現在通過效期閘門的候選池中。"""
    kb = get_kb()
    valid_ids = {p.passage_id for p in kb.valid_passages()}
    for rec in kb.marker_disagreements:
        pid = f"PROD-{rec['licence_no']}"
        assert pid not in valid_ids, f"{pid} 已過期卻進入有效來源池"


def test_date_only_expired_products_excluded_from_vet_search(client, vet_headers):
    """API 層：獸醫檢索不得回傳這類產品。"""
    kb = get_kb()
    expired_licences = {rec["licence_no"] for rec in kb.marker_disagreements}
    assert expired_licences

    r = client.post(
        "/api/vet/search",
        json={"query": "犬", "species": "dog", "limit": 100},
        headers=vet_headers,
    )
    assert r.status_code == 200
    returned = {p["licence_no"] for p in r.json()["results"]}
    leaked = returned & expired_licences
    assert not leaked, f"效期閘門洩漏了僅靠日期才能辨識的過期品項: {leaked}"


def test_as_of_shift_changes_verdict():
    """時間平移驗證：把基準日移到到期前，同一文件即不算過期。

    證明判定確實來自日期比較，而不是任何靜態欄位。
    """
    before = date(2026, 6, 1)  # 07363 到期 (2026-06-30) 之前
    after = date(2026, 8, 19)
    assert compute_expiry(CASE_07363["expiry_date_iso"], before)[0] is False
    assert compute_expiry(CASE_07363["expiry_date_iso"], after)[0] is True
