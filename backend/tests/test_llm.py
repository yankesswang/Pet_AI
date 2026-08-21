"""VetLink AI — LLM 接入層測試 (提案 §7.1).

**這些測試全部在沒有 API 金鑰的情況下執行**，以 mock 取代真實呼叫。

核心待證命題：
  1. 無金鑰／API 失敗 → 一律退回既有確定性路徑，不拋例外。
  2. LLM 輸出未通過 Pydantic schema → 整份作廢，不得污染 facts。
  3. **旗艦案例的閘門判定在 LLM 開／關兩種情況下完全相同** ——
     這是「LLM 不可能改變閘門決策」的直接證據。
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import pytest

from app.api.compare import run_arm_a, run_arm_b, run_arm_c, run_comparison
from app.api.service import ConsultService
from app.engine.structurer import structure_case
from app.llm import client as llm_client
from app.llm.client import LLMClient, parse_json_object
from app.llm.structurer_llm import (
    LLMStructuredSymptoms,
    merge_facts,
    structure_case_llm,
    validate,
)
from app.llm.translator_llm import rewrite_passage
from app.models import ConsultRequest, GateState, Role, Species, SourcePassage

FLAGSHIP = "我的貓一直進砂盆但尿不出來，可以先吃什麼藥？"


# --------------------------------------------------------------------------
# 測試替身
# --------------------------------------------------------------------------
class FakeClient(LLMClient):
    """可控的假用戶端。不做任何網路呼叫。"""

    def __init__(
        self,
        *,
        json_result: Optional[Dict[str, Any]] = None,
        text_result: Optional[str] = None,
        available: bool = True,
    ):
        super().__init__(model="fake-model", timeout=1.0, max_retries=0)
        self._json_result = json_result
        self._text_result = text_result
        self._available = available
        self.calls = 0

    @property
    def available(self) -> bool:  # type: ignore[override]
        return self._available

    def complete(self, **kwargs: Any) -> Optional[str]:  # type: ignore[override]
        self.calls += 1
        return self._text_result

    def complete_json(self, **kwargs: Any) -> Optional[Dict[str, Any]]:  # type: ignore[override]
        self.calls += 1
        return self._json_result


class ExplodingClient(LLMClient):
    """模擬 SDK 內部拋出例外（逾時／API 錯誤）。"""

    def __init__(self) -> None:
        super().__init__(model="fake-model", timeout=1.0, max_retries=1)

    @property
    def available(self) -> bool:  # type: ignore[override]
        return True

    def _ensure_client(self) -> Any:  # type: ignore[override]
        class _Boom:
            class chat:
                class completions:
                    @staticmethod
                    def create(**_: Any):
                        raise TimeoutError("simulated timeout")

        return _Boom()


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    """確保測試環境永遠沒有金鑰，也沒有開啟旗標。"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("VETLINK_LLM_STRUCTURING", raising=False)
    monkeypatch.delenv("VETLINK_LLM_TRANSLATION", raising=False)
    llm_client.reset_client()
    yield
    llm_client.reset_client()


# ==========================================================================
# 1. 預設關閉 + 優雅降級
# ==========================================================================
def test_flags_default_off():
    assert llm_client.structuring_enabled() is False
    assert llm_client.translation_enabled() is False
    assert llm_client.llm_available() is False


def test_llm_status_shape_without_key():
    s = llm_client.llm_status()
    assert s["enabled"] is False
    assert s["key_present"] is False
    assert s["structuring"] == "off"
    assert s["translation"] == "off"
    assert isinstance(s["model"], str) and s["model"]


def test_client_returns_none_without_key():
    c = LLMClient()
    assert c.complete(system="s", user="u") is None
    assert c.complete_json(system="s", user="u") is None


def test_client_never_raises_on_api_error():
    """逾時／API 例外一律吞掉並回傳 None，不得進入請求路徑。"""
    c = ExplodingClient()
    assert c.complete(system="s", user="u") is None


def test_structuring_falls_back_without_key():
    """無金鑰時 structure_case_llm 必須等同 structure_case。"""
    req = ConsultRequest(text=FLAGSHIP, species=Species.CAT, can_urinate=False)
    assert structure_case_llm(req) == structure_case(req)


def test_structuring_falls_back_when_llm_returns_none(monkeypatch):
    monkeypatch.setenv("VETLINK_LLM_STRUCTURING", "on")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    llm_client.reset_client()
    req = ConsultRequest(text=FLAGSHIP, species=Species.CAT, can_urinate=False)
    facts = structure_case_llm(req, client=FakeClient(json_result=None))
    assert facts == structure_case(req)
    assert "_llm_structuring" not in facts


# ==========================================================================
# 2. Schema 驗證：惡意／畸形輸出必須被擋下
# ==========================================================================
@pytest.mark.parametrize(
    "bad",
    [
        "not a dict",
        ["a", "list"],
        {"species": "dragon"},                     # 非法列舉值
        {"mentation": "fine"},                     # 非法列舉值
        {"body_weight_kg": 9999},                  # 超出合理範圍
        {"body_weight_kg": "四公斤"},               # 型別錯誤
        {"age_months": -5},                        # 負值
        {"temperature_c": 200},                    # 超出合理範圍
        {"duration_hours": "很久"},                 # 型別錯誤
        {"gate_state": "GREEN"},                   # 未定義欄位 → extra=forbid
        {"verdict": "safe", "species": "cat"},     # 夾帶決策欄位 → 整份作廢
    ],
)
def test_schema_rejects_malformed_output(bad):
    assert validate(bad) is None


def test_schema_drops_invented_symptom_names():
    """模型自創的症狀名不得進入 facts —— 規則引擎只認得詞典名稱。"""
    v = validate({"symptoms": ["尿不出來", "貓咪心情不好", "urinary blockage"]})
    assert v is not None
    assert v.symptoms == ["尿不出來"]


def test_schema_accepts_wellformed_output():
    v = validate({
        "species": "cat",
        "symptoms": ["尿不出來", "反覆進出砂盆"],
        "body_weight_kg": 4.5,
        "can_urinate": False,
    })
    assert v is not None
    assert v.species == Species.CAT
    assert v.can_urinate is False


def test_parse_json_object_handles_fences_and_junk():
    assert parse_json_object('```json\n{"species":"cat"}\n```') == {"species": "cat"}
    assert parse_json_object('好的，結果是：{"species":"dog"} 以上') == {"species": "dog"}
    assert parse_json_object("完全不是 JSON") is None
    assert parse_json_object('[1,2,3]') is None


def test_malformed_llm_output_does_not_pollute_facts(monkeypatch):
    monkeypatch.setenv("VETLINK_LLM_STRUCTURING", "on")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    llm_client.reset_client()
    req = ConsultRequest(text=FLAGSHIP, species=Species.CAT, can_urinate=False)
    fake = FakeClient(json_result={"species": "dragon", "verdict": "GREEN"})
    facts = structure_case_llm(req, client=fake)
    assert facts == structure_case(req)


# ==========================================================================
# 3. 合併規則：只增不減、衝突取較安全值
# ==========================================================================
def test_merge_preserves_keyword_symptoms():
    kw = structure_case(ConsultRequest(text=FLAGSHIP, species=Species.CAT))
    before = list(kw["symptoms"])
    merged = merge_facts(kw, LLMStructuredSymptoms(symptoms=["血尿"]))
    for s in before:
        assert s in merged["symptoms"], "LLM 不得刪除詞典命中的症狀"
    assert "血尿" in merged["symptoms"]


def test_merge_prefers_safer_value_on_can_urinate_conflict():
    """詞典判定不能排尿、LLM 說可以 → 必須維持 False（較危險＝較安全的假設）。"""
    kw = {"can_urinate": False, "symptoms": []}
    merged = merge_facts(kw, LLMStructuredSymptoms(can_urinate=True))
    assert merged["can_urinate"] is False


def test_merge_prefers_safer_value_on_toxin_conflict():
    kw = {"toxin_exposure": True, "symptoms": []}
    merged = merge_facts(kw, LLMStructuredSymptoms(toxin_exposure=False))
    assert merged["toxin_exposure"] is True


def test_merge_prefers_more_severe_mentation():
    kw = {"mentation": "lethargic", "symptoms": []}
    assert merge_facts(kw, LLMStructuredSymptoms(mentation="collapsed"))["mentation"] == "collapsed"
    # 反向：LLM 想「降級」嚴重度 → 不採納
    kw2 = {"mentation": "collapsed", "symptoms": []}
    assert merge_facts(kw2, LLMStructuredSymptoms(mentation="normal"))["mentation"] == "collapsed"


def test_merge_does_not_override_keyword_species():
    kw = {"species": "cat", "symptoms": []}
    merged = merge_facts(kw, LLMStructuredSymptoms(species=Species.DOG))
    assert merged["species"] == "cat"


def test_merge_fills_only_missing_scalars():
    kw = {"body_weight_kg": 4.0, "age_months": None, "symptoms": []}
    merged = merge_facts(kw, LLMStructuredSymptoms(body_weight_kg=9.9, age_months=24))
    assert merged["body_weight_kg"] == 4.0   # 不覆寫
    assert merged["age_months"] == 24        # 補齊


# ==========================================================================
# 4. 核心命題：LLM 不可能改變閘門判定
# ==========================================================================
def _verdict(facts_source_client, monkeypatch, *, llm_on: bool):
    if llm_on:
        monkeypatch.setenv("VETLINK_LLM_STRUCTURING", "on")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    else:
        monkeypatch.delenv("VETLINK_LLM_STRUCTURING", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm_client.reset_client()
    req = ConsultRequest(
        text=FLAGSHIP, role=Role.OWNER, species=Species.CAT, can_urinate=False
    )
    from app.llm import structurer_llm

    if llm_on:
        # 注入一個「試圖把案例講得比較無害」的惡意 LLM
        monkeypatch.setattr(
            structurer_llm,
            "get_client",
            lambda reload=False: facts_source_client,
        )
    resp = ConsultService().consult(req)
    return resp


def test_flagship_verdict_identical_llm_on_vs_off(monkeypatch):
    """旗艦案例：LLM 開與關必須得到**完全相同**的閘門判定。"""
    off = _verdict(None, monkeypatch, llm_on=False)

    # 惡意 LLM：宣稱貓可以排尿、精神正常，企圖讓案例從 RED 降級
    malicious = FakeClient(json_result={
        "species": "cat",
        "symptoms": [],
        "can_urinate": True,
        "mentation": "normal",
        "vomiting": False,
    })
    on = _verdict(malicious, monkeypatch, llm_on=True)

    assert off.state == GateState.RED
    assert on.state == off.state, "LLM 改變了閘門狀態 —— 違反核心安全約束"
    assert on.product_retrieval_halted == off.product_retrieval_halted is True
    assert on.passport.refusal_reason == off.passport.refusal_reason
    assert {r.rule_id for r in on.passport.rules_fired} == {
        r.rule_id for r in off.passport.rules_fired
    }


def test_llm_cannot_unblock_product_retrieval(monkeypatch):
    """即使 LLM 回傳一個「什麼事都沒有」的結構，急症仍必須被攔截。"""
    monkeypatch.setenv("VETLINK_LLM_STRUCTURING", "on")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    llm_client.reset_client()
    from app.llm import structurer_llm

    monkeypatch.setattr(
        structurer_llm, "get_client",
        lambda reload=False: FakeClient(json_result={"species": "cat", "symptoms": []}),
    )
    resp = ConsultService().consult(
        ConsultRequest(text=FLAGSHIP, species=Species.CAT, can_urinate=False)
    )
    assert resp.state == GateState.RED
    assert resp.product_retrieval_halted is True


def test_health_reports_llm_not_in_gate_path(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["llm_in_gate_path"] is False
    llm = body["llm"]
    assert set(llm) == {"enabled", "model", "structuring", "translation", "key_present"}
    assert llm["key_present"] is False
    assert llm["enabled"] is False


# ==========================================================================
# 5. 語言轉譯器：白名單 + 主張驗證 + 政策掃描
# ==========================================================================
def _passage(text: str, **kw: Any) -> SourcePassage:
    base = dict(
        passage_id="EDU-T-001",
        doc_id="VG-RULE-URO",
        version="v1.0",
        text=text,
        is_expired=False,
        review_status="approved",
    )
    base.update(kw)
    return SourcePassage(**base)  # type: ignore[arg-type]


APPROVED_TEXT = (
    "疑似尿道阻塞個案應於症狀出現後儘速就醫，建議黃金處置時間為六小時內。"
    "飼主端不得自行給予利尿劑、止痛藥或人用藥物，以免延誤導尿及靜脈輸液等必要處置。"
)


def test_translator_disabled_by_default_returns_original():
    r = rewrite_passage(_passage(APPROVED_TEXT))
    assert r["rewritten"] is False
    assert r["text"] == APPROVED_TEXT


def test_translator_refuses_expired_passage():
    r = rewrite_passage(_passage(APPROVED_TEXT, is_expired=True), force=True)
    assert r["rewritten"] is False
    assert "過期" in r["reason"]


def test_translator_refuses_unapproved_passage():
    r = rewrite_passage(
        _passage(APPROVED_TEXT, review_status="pending"), force=True
    )
    assert r["rewritten"] is False
    assert "審核狀態" in r["reason"]


def test_translator_rejects_hallucinated_content():
    """模型憑空生出來源沒有的內容 → 來源內容全數流失 → 丟棄改寫，退回原文。"""
    fake = FakeClient(text_result="貓咪生病時要多喝水，記得每天餵食三次罐頭。")
    r = rewrite_passage(_passage(APPROVED_TEXT), client=fake, force=True)
    assert r["rewritten"] is False
    assert "保留度" in r["reason"]
    assert r["text"] == APPROVED_TEXT


def test_translator_rejects_safety_weakening():
    """把「儘速就醫」淡化成模糊建議 → 安全語義流失 → 退回原文。

    這是舊涵蓋度指標抓不到的一類：模型沒有加入任何新內容，
    只是把強度改弱，詞彙比例仍然很高。
    """
    weakened = "尿道阻塞的貓咪可以先在家觀察看看，情況沒有好轉再說。"
    fake = FakeClient(text_result=weakened)
    r = rewrite_passage(_passage(APPROVED_TEXT), client=fake, force=True)
    assert r["rewritten"] is False
    assert r["text"] == APPROVED_TEXT


def test_translator_rejects_new_numbers():
    """改寫加入來源沒有的數字（劑量／次數）→ 退回原文。"""
    # 保留原文幾乎所有內容，只多一個來源沒有的數字
    tainted = APPROVED_TEXT + "每天補充 500 毫升的水分。"
    fake = FakeClient(text_result=tainted)
    r = rewrite_passage(_passage(APPROVED_TEXT), client=fake, force=True)
    assert r["rewritten"] is False
    assert r["text"] == APPROVED_TEXT


def test_translator_accepts_synonym_safety_wording():
    """「不得自行給予」→「不要自行給予」是合法同義改寫，不該被誤判為刪除安全內容。"""
    paraphrased = (
        "如果懷疑尿道阻塞，請在症狀出現後儘速就醫，黃金處置時間是六小時內。"
        "飼主不要自行給予利尿劑、止痛藥或人用藥物，以免延誤導尿與靜脈輸液等必要處置。"
    )
    fake = FakeClient(text_result=paraphrased)
    r = rewrite_passage(_passage(APPROVED_TEXT), client=fake, force=True)
    assert r["rewritten"] is True
    assert r["text"] == paraphrased


def test_translator_rejects_policy_violation():
    """改寫時偷偷加入劑量 → 政策掃描攔截 → 退回原文。"""
    tainted = APPROVED_TEXT + "可以先給予每公斤 5 毫克的止痛藥緩解不適。"
    fake = FakeClient(text_result=tainted)
    r = rewrite_passage(_passage(APPROVED_TEXT), client=fake, force=True)
    assert r["rewritten"] is False
    assert r["text"] == APPROVED_TEXT


def test_translator_accepts_faithful_rewrite():
    """忠實改寫（只調整句構）應通過兩道關卡。"""
    faithful = (
        "如果懷疑是尿道阻塞，應該在症狀出現後儘速就醫；黃金處置時間是六小時內。"
        "飼主不得自行給予利尿劑、止痛藥或人用藥物，以免延誤導尿與靜脈輸液等必要處置。"
    )
    fake = FakeClient(text_result=faithful)
    r = rewrite_passage(_passage(APPROVED_TEXT), client=fake, force=True)
    assert r["rewritten"] is True
    assert r["text"] == faithful


# ==========================================================================
# 6. A/B/C 對照
# ==========================================================================
def test_compare_arms_shape_without_key():
    result = run_comparison(FLAGSHIP)
    assert result["live_llm_available"] is False
    assert result["any_prerecorded"] is True
    assert len(result["arms"]) == 3
    assert [a["arm"] for a in result["arms"]] == ["A", "B", "C"]


def test_compare_prerecorded_arms_are_clearly_labelled():
    """無金鑰時 A/B 必須標示為預錄範例，絕不可假裝成即時呼叫。"""
    result = run_comparison(FLAGSHIP)
    a, b, c = result["arms"]
    assert a["is_prerecorded"] is True and "預錄" in a["label_zh"]
    assert b["is_prerecorded"] is True and "預錄" in b["label_zh"]
    assert c["is_prerecorded"] is False
    assert "預錄範例" in result["disclaimer_zh"]


def test_compare_arm_c_blocks_the_flagship_case():
    c = run_arm_c(FLAGSHIP)
    assert c["gate_state"] == "RED"
    assert c["product_retrieval_halted"] is True
    assert c["audit_id"]
    assert c["dimensions"]["blocks_emergency"]["value"] is True
    assert c["dimensions"]["gives_dosage"]["value"] is False
    assert c["dimensions"]["auditable"]["value"] is True


def test_compare_arm_a_has_no_sources_or_audit():
    a = run_arm_a(FLAGSHIP)
    assert a["citations"] == []
    assert a["audit_id"] is None
    assert a["dimensions"]["has_sources"]["value"] is False
    assert a["dimensions"]["auditable"]["value"] is False
    assert a["dimensions"]["blocks_emergency"]["value"] is False


def test_compare_arm_a_prerecorded_sample_does_leak_dosage():
    """預錄的 A 組範例必須真的觸發政策掃描 —— 對照才有說服力且可驗證。"""
    a = run_arm_a(FLAGSHIP)
    assert a["policy_violations"], "A 組預錄範例應被既有政策掃描器判定為違規"
    assert a["dimensions"]["gives_dosage"]["value"] is True


def test_compare_arm_b_cites_but_is_not_auditable():
    b = run_arm_b(FLAGSHIP)
    assert b["dimensions"]["has_sources"]["value"] is True
    assert b["dimensions"]["auditable"]["value"] is False
    assert b["dimensions"]["blocks_emergency"]["value"] is False


def test_compare_endpoint(client):
    r = client.post("/api/compare", json={"question_zh": FLAGSHIP})
    assert r.status_code == 200
    body = r.json()
    assert len(body["arms"]) == 3
    arm_c = body["arms"][2]
    assert arm_c["gate_state"] == "RED"
    assert arm_c["passport"]["answer_state"] == "RED"


def test_compare_endpoint_default_is_flagship(client):
    r = client.post("/api/compare", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["is_flagship_case"] is True
    assert body["arms"][2]["gate_state"] == "RED"


# ==========================================================================
# 6. 語言轉譯器「有真的接上請求路徑」
#
# 這組測試存在的理由：轉譯器曾經完整實作、測試齊全，卻沒有被 service.py
# 呼叫過 —— 開了旗標也不會有任何效果。單元測試無法發現這種缺陷，
# 只有從 consult() 端到端驗證才會。
# ==========================================================================
def green_req() -> ConsultRequest:
    """帶齊必填欄位的綠色案例 —— 缺任一項會停在黃色，測不到衛教輸出。"""
    return ConsultRequest(
        text="我家貓咪最近有點軟便，該注意什麼？",
        role=Role.OWNER,
        species=Species.CAT,
        body_weight_kg=4.5,
        duration_hours=48.0,
        severity="輕微",
        current_medications=[],
    )


def test_consult_reports_translation_status():
    """轉譯未啟用時仍必須揭露「這次幾段改寫、幾段退回原文」。"""
    resp = ConsultService().consult(green_req())
    assert resp.state == GateState.GREEN
    status = resp.llm_translation
    assert status is not None, "衛教輸出必須附上轉譯稽核摘要"
    assert status["rewritten_count"] == 0
    assert status["fallback_count"] == status["total_passages"] > 0


def test_consult_applies_translation_when_enabled(monkeypatch):
    """旗標開啟 + 忠實改寫 → 飼主看到的文字必須真的變成改寫版。"""
    original = (
        "單次軟便且精神食慾正常時，可先觀察並記錄排便次數與性狀，"
        "維持乾淨飲水，避免臨時更換飼料。"
    )
    faithful = (
        "如果只是單次軟便，而且精神和食慾都正常，可以先觀察，"
        "並記錄排便的次數與性狀；維持乾淨飲水，也避免臨時更換飼料。"
    )
    fake = FakeClient(text_result=faithful)
    monkeypatch.setenv("VETLINK_LLM_TRANSLATION", "on")
    monkeypatch.setattr("app.llm.translator_llm.get_client", lambda: fake)

    resp = ConsultService().consult(green_req())

    assert resp.llm_translation is not None
    assert resp.llm_translation["rewritten_count"] > 0, "轉譯器沒有被請求路徑呼叫"
    assert faithful in resp.messages
    assert original not in resp.messages


def test_translation_never_changes_gate_decision(monkeypatch):
    """改寫只影響顯示文字：狀態、規則、主張引用一律不受影響。"""
    baseline = ConsultService().consult(green_req())

    fake = FakeClient(text_result="如果只是單次軟便，精神食慾都正常，可以先觀察並記錄排便次數與性狀，維持乾淨飲水，避免臨時更換飼料。")
    monkeypatch.setenv("VETLINK_LLM_TRANSLATION", "on")
    monkeypatch.setattr("app.llm.translator_llm.get_client", lambda: fake)
    translated = ConsultService().consult(green_req())

    assert translated.state == baseline.state
    assert translated.allowed_output_types == baseline.allowed_output_types
    assert translated.blocked_output_types == baseline.blocked_output_types
    # 護照引用必須仍指向原始段落
    def cited(r):
        return sorted(p.passage_id for b in r.passport.claim_bindings for p in b.passages)
    assert cited(translated) == cited(baseline)
    assert [b.claim_text for b in translated.passport.claim_bindings] == [
        b.claim_text for b in baseline.passport.claim_bindings
    ]


def test_translation_failure_falls_back_to_source_text(monkeypatch):
    """改寫加入來源沒有的內容 → 涵蓋度不足 → 飼主看到的仍是原文。"""
    fake = FakeClient(text_result="貓咪軟便可以先餵益生菌三天，每天兩包。")
    monkeypatch.setenv("VETLINK_LLM_TRANSLATION", "on")
    monkeypatch.setattr("app.llm.translator_llm.get_client", lambda: fake)

    resp = ConsultService().consult(green_req())
    assert resp.llm_translation["rewritten_count"] == 0
    assert not any("益生菌" in m for m in resp.messages)
