"""安全正規化器與 fail-closed 的回歸測試。

這些測試鎖住的是**安全承諾**，不是實作細節：留出集量到的每一類分診失效，
在這裡都有一個對應的最小案例。任何讓其中一項退回去的修改都應該讓 CI 失敗。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.service import ConsultService  # noqa: E402
from app.engine.normalizer import Assertion, normalize  # noqa: E402
from app.engine.structurer import structure_case  # noqa: E402
from app.models import ConsultRequest, GateState, Role, Species  # noqa: E402


def _consult(text: str, **fields):
    species = fields.pop("species", None)
    req = ConsultRequest(
        text=text,
        role=Role.OWNER,
        species=Species(species) if species else None,
        **fields,
    )
    return ConsultService().consult(req, vet_verified=False, owner_authorized=False)


# --------------------------------------------------------------------------
# 斷言標記：症狀出現 ≠ 症狀現在成立
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("牠沒有尿不出來，只是最近水喝得比較少", Assertion.NEGATED),
        ("上個月我家公貓因為尿不出來住院導尿，出院後排尿都正常了", Assertion.HISTORICAL),
        ("我想先知道貓咪如果尿不出來會有什麼徵兆", Assertion.HYPOTHETICAL),
        ("我朋友的狗誤食巧克力送急診", Assertion.THIRD_PARTY),
    ],
)
def test_non_present_contexts_are_labelled(text, expected):
    norm = normalize(text)
    assert any(c.assertion is expected for c in norm.clauses), (
        f"「{text}」應被標為 {expected.value}，實際: "
        f"{[(c.text, c.assertion.value) for c in norm.clauses]}"
    )


@pytest.mark.parametrize(
    "text",
    [
        "牠沒有尿不出來，只是最近水喝得比較少",
        "上個月我家公貓因為尿不出來住院導尿，出院後排尿都正常了",
        "我想先知道貓咪如果尿不出來會有什麼徵兆，這樣我才知道什麼時候該送醫",
        "我朋友的狗誤食巧克力送急診，我想知道家裡還有哪些食物要收好",
        "我家貓從來沒有嘔吐過，但我想先知道嘔吐的時候該注意什麼",
    ],
)
def test_non_present_symptoms_do_not_trigger_red(text):
    """否定／過去／假設／第三方的症狀不得被當成當下急症。"""
    assert _consult(text).state is not GateState.RED


def test_negated_symptom_is_excluded_from_facts():
    facts = structure_case(ConsultRequest(text="牠沒有尿不出來，只是最近水喝得比較少"))
    assert "尿不出來" not in facts["symptoms"]
    # 但仍要留在稽核軌跡裡，說明「為什麼沒觸發」
    assert "尿不出來" in facts["symptoms_by_assertion"].get("negated", [])


def test_single_char_negation_does_not_swallow_emergencies():
    """「無糖口香糖」= 木糖醇中毒，不是「無」某症狀。

    單字「無」曾被當成否定線索，導致這個真急症被靜默漏判。
    """
    facts = structure_case(ConsultRequest(text="狗狗把整條無糖口香糖吃掉了"))
    assert "誤食木糖醇" in facts["symptoms"]
    assert facts["toxin_exposure"] is True


def test_history_then_present_stays_present():
    """先講病史再講現況時，現況不得被過去語境吃掉。"""
    facts = structure_case(
        ConsultRequest(text="上個月住院導尿過，現在又一直蹲貓砂盆尿不出來")
    )
    assert "尿不出來" in facts["symptoms"]


# --------------------------------------------------------------------------
# 表面正規化：同一個急症換個寫法仍須判 RED
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,fields",
    [
        # 簡體
        ("公猫一直蹲在猫砂盆里出不来，什么都排不出来，肚子鼓鼓的",
         {"species": "cat", "duration_hours": 12, "severity": "severe",
          "current_medications": []}),
        # 英文
        ("My male cat has been straining in the litter box with no urine",
         {"species": "cat", "duration_hours": 12, "severity": "severe",
          "current_medications": []}),
        # 錯字／口語
        ("貓咪尿布出來 一直蹲貓砂盆 怎麼半",
         {"species": "cat", "duration_hours": 12, "severity": "severe",
          "current_medications": []}),
    ],
)
def test_emergency_survives_paraphrase(text, fields):
    assert _consult(text, **fields).state is GateState.RED


# --------------------------------------------------------------------------
# fail-closed：看不懂 ≠ 沒有危險
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,fields",
    [
        ("牠怪怪的", {}),
        ("我家寶貝生病了", {}),
        ("貓咪不舒服，體重我沒量過",
         {"species": "cat", "duration_hours": 48, "severity": "mild",
          "current_medications": []}),
    ],
)
def test_unparseable_complaint_never_reaches_green(text, fields):
    """抽不出臨床訊號卻明顯在求助時，一律追問，不得直接給衛教。"""
    resp = _consult(text, **fields)
    assert resp.state is not GateState.GREEN
    assert resp.required_questions, "fail-closed 必須實際提出追問"


def test_pure_education_question_still_gets_green():
    """fail-closed 不得誤傷正常的衛教提問 —— 那類問題本來就該給綠色。"""
    resp = _consult(
        "我想知道狗狗中暑的前兆有哪些，夏天要怎麼預防",
        species="dog", body_weight_kg=12.0, duration_hours=1, severity="mild",
        current_medications=[],
    )
    assert resp.state is GateState.GREEN
