"""VetLink AI — 衛教段落檢索的切題性與物種邊界。

這兩件事單看回答內容不容易發現，因為出問題時輸出仍然「有來源、通得過主張驗證」，
只是不切題或根本是別的物種的內容：

  1. 情境過度召回：原本以關鍵字計分檢索，沒有最低分數門檻，
     問「貓軟便」會一併撈到呼吸道段落（命中「食慾」）與泌尿段落（命中「飲水」）。
  2. 跨物種洩漏：政策／毒理／急症段落原本一律納入候選且**未套用物種過濾**，
     狗的案例會拿到貓專屬的尿道阻塞衛教（EDU-EMG-001）。
"""
from __future__ import annotations

from app.api.service import ConsultService
from app.engine.knowledge import get_kb
from app.models import ConsultRequest, GateState, Role, Species


def _req(text: str, species: Species) -> ConsultRequest:
    """帶齊必填欄位的飼主提問 —— 缺任一項會停在黃色，測不到檢索行為。"""
    return ConsultRequest(
        text=text,
        role=Role.OWNER,
        species=species,
        body_weight_kg=4.5,
        duration_hours=48.0,
        severity="輕微",
        current_medications=[],
    )


def _cited_passages(resp) -> list[str]:
    return [p.passage_id for b in resp.passport.claim_bindings for p in b.passages]


# --------------------------------------------------------------------------
# 1. 情境切題性
# --------------------------------------------------------------------------
def test_scenario_scope_is_declared_on_every_education_passage():
    """每一段衛教都必須標註情境，否則永遠不會被檢索到。"""
    kb = get_kb()
    for pid, p in kb.passages.items():
        if pid.startswith("EDU-"):
            assert p.scenario_scope, f"{pid} 缺少 scenario_scope 標註"


def test_gi_question_does_not_retrieve_respiratory_or_urinary_passages():
    resp = ConsultService().consult(
        _req("我家貓咪最近有點軟便，該注意什麼？", Species.CAT)
    )
    assert resp.state == GateState.GREEN
    cited = _cited_passages(resp)
    assert any(p.startswith("EDU-GI-") for p in cited), "腸胃問題卻沒有引用腸胃段落"
    assert not any(p.startswith("EDU-RES-") for p in cited), f"呼吸段落不該出現: {cited}"
    assert not any(p.startswith("EDU-URI-") for p in cited), f"泌尿段落不該出現: {cited}"


def test_dermatology_question_retrieves_only_its_own_scenario():
    resp = ConsultService().consult(
        _req("狗狗耳朵平常要怎麼清潔比較好", Species.DOG)
    )
    cited = _cited_passages(resp)
    assert any(p.startswith("EDU-DERM-") for p in cited)
    assert not any(p.startswith("EDU-GI-") for p in cited), f"腸胃段落不該出現: {cited}"


def test_education_passages_filters_by_scenario_tag():
    kb = get_kb()
    got = {p.passage_id for p in kb.education_passages("腸胃")}
    assert got == {"EDU-GI-001", "EDU-GI-002", "EDU-GI-003", "EDU-GI-004"}


def test_same_scenario_ranking_uses_question_to_surface_online_source():
    """文件擴充後不能永遠只取 ID 排序最前面的四段。"""
    kb = get_kb()
    got = kb.education_passages(
        "跨情境",
        species="cat",
        query="貓咪誤食普拿疼人用止痛藥怎麼辦",
    )
    ids = [p.passage_id for p in got]
    assert "EDU-TOX-006" in ids
    assert ids.index("EDU-TOX-006") < 2


# --------------------------------------------------------------------------
# 2. 跨物種邊界
# --------------------------------------------------------------------------
def test_cat_only_emergency_passage_never_reaches_dog_case():
    """EDU-EMG-001 是貓專屬尿道阻塞衛教，狗的案例不得取得。"""
    service = ConsultService()
    dog = service._candidate_passages({"species": "dog", "scenarios": ["泌尿"]})
    assert "EDU-EMG-001" not in [p.passage_id for p in dog]

    cat = service._candidate_passages({"species": "cat", "scenarios": ["泌尿"]})
    assert "EDU-EMG-001" in [p.passage_id for p in cat]


def test_education_passages_respects_species_scope():
    kb = get_kb()
    assert "EDU-EMG-001" in {
        p.passage_id for p in kb.education_passages("泌尿", species="cat")
    }
    assert "EDU-EMG-001" not in {
        p.passage_id for p in kb.education_passages("泌尿", species="dog")
    }


def test_dog_answer_contains_no_cat_specific_content():
    resp = ConsultService().consult(
        _req("狗狗平常怎麼觀察排尿正不正常", Species.DOG)
    )
    body = " ".join(resp.messages + resp.danger_signs)
    assert "公貓" not in body, f"狗的回答出現貓專屬內容: {body}"


# --------------------------------------------------------------------------
# 3. 檢索範圍不影響引用完整性
# --------------------------------------------------------------------------
def test_every_cited_passage_is_valid_and_approved():
    resp = ConsultService().consult(
        _req("我家貓咪最近有點軟便，該注意什麼？", Species.CAT)
    )
    for b in resp.passport.claim_bindings:
        if not b.supported:
            continue
        for p in b.passages:
            assert not p.is_expired
            assert p.review_status == "approved"


# --------------------------------------------------------------------------
# 4. 檢索軌跡（前端「這次檢索到哪些」的資料來源）
# --------------------------------------------------------------------------
def test_retrieval_trace_reports_full_funnel():
    """文件庫 → 候選 → 主張 → 實際輸出，四層數字都要對得起來。"""
    resp = ConsultService().consult(
        _req("我家貓咪最近有點軟便，該注意什麼？", Species.CAT)
    )
    t = resp.retrieval
    assert t is not None
    c = t["counts"]
    assert c["library"] == 47
    assert c["candidates"] + c["excluded"] == c["library"]
    assert c["claims"] <= t["claim_limit"]
    assert c["displayed"] <= c["verified"] <= c["claims"]


def test_retrieval_trace_labels_every_candidate_stage():
    resp = ConsultService().consult(
        _req("我家貓咪最近有點軟便，該注意什麼？", Species.CAT)
    )
    t = resp.retrieval
    stages = {c["stage"] for c in t["candidates"]}
    assert stages <= {"displayed", "verified", "unsupported", "candidate"}
    for c in t["candidates"]:
        assert c["stage_zh"], f"{c['passage_id']} 缺少中文說明"
        # 成為主張的必須指得出 claim_id，反之亦然
        assert bool(c["claim_id"]) == (c["stage"] != "candidate")


def test_retrieval_trace_explains_why_passages_were_excluded():
    resp = ConsultService().consult(
        _req("我家貓咪最近有點軟便，該注意什麼？", Species.CAT)
    )
    excluded = {e["passage_id"]: e["reason_zh"] for e in resp.retrieval["excluded"]}
    assert "EDU-RES-001" in excluded
    assert "情境不符" in excluded["EDU-RES-001"]


def test_retrieval_trace_explains_species_exclusion():
    resp = ConsultService().consult(
        _req("狗狗平常怎麼觀察排尿正不正常", Species.DOG)
    )
    excluded = {e["passage_id"]: e["reason_zh"] for e in resp.retrieval["excluded"]}
    assert "EDU-EMG-001" in excluded
    assert "適用物種" in excluded["EDU-EMG-001"]


def test_retrieval_trace_present_even_when_refused():
    """紅色拒答時仍要看得到檢索軌跡 —— 拒答更需要能被檢查。"""
    resp = ConsultService().consult(
        ConsultRequest(
            text="我的貓一直進砂盆但尿不出來，可以先吃什麼藥？",
            role=Role.OWNER,
            species=Species.CAT,
            can_urinate=False,
        )
    )
    assert resp.state == GateState.RED
    assert resp.retrieval is not None
    assert resp.retrieval["counts"]["candidates"] > 0
