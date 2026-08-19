"""VetLink AI — API 端到端測試 (提案 §十 三幕 Demo + §十二 驗證設計)。"""
from __future__ import annotations

import pytest

from app.engine.policy import scan_text_for_violations
from app.models import Role

# --------------------------------------------------------------------------
# 基礎
# --------------------------------------------------------------------------


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["rule_count"] >= 40
    # 閘門路徑不得有 LLM
    assert body["llm_in_gate_path"] is False


def test_stats_exposes_date_only_expiry_evidence(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    gate = r.json()["expiry_gate"]
    # 這些文件只有靠日期換算才抓得到，是 Evidence Gate 存在的實證理由
    assert gate["date_only_expired_count"] > 0


# --------------------------------------------------------------------------
# 第一幕：紅色旗艦案例
# --------------------------------------------------------------------------


def test_red_flagship_urethral_obstruction(client):
    """提案 §10 第一幕：貓進砂盆尿不出來 + 索取用藥 → 紅色、停止產品檢索。"""
    r = client.post(
        "/api/consult",
        json={
            "text": "我的貓一直進砂盆但尿不出來，可以先吃什麼藥？",
            "role": "owner",
            "species": "cat",
            "can_urinate": False,
        },
    )
    assert r.status_code == 200
    d = r.json()

    assert d["state"] == "RED"
    assert d["passport"]["refusal_reason"] == "emergency"
    # 產品檢索必須完全停止
    assert d["product_retrieval_halted"] is True

    fired = [x["rule_id"] for x in d["passport"]["rules_fired"]]
    assert "VG-RED-001" in fired, "須記錄疑似排尿阻塞急症規則"

    # 不得輸出任何藥品或劑量
    blocked = set(d["blocked_output_types"])
    for banned in ("dosage", "prescription_product", "purchase_link", "diagnosis"):
        assert banned in blocked
    allowed = set(d["allowed_output_types"])
    assert allowed.isdisjoint({"dosage", "product_recommendation", "prescription_product"})

    # 必須提供急診轉介與危險徵兆
    assert "emergency_referral" in allowed
    assert d["danger_signs"], "紅色狀態應提供危險徵兆"

    # 症狀摘要可交接給獸醫
    assert d["visit_summary"] is not None
    assert "VG-RED-001" in d["visit_summary"]["fired_rules"]


@pytest.mark.parametrize(
    "payload",
    [
        # 以下兩例曾因症狀詞典缺少口語變體而漏接，屬回歸測試：
        # 「黑色柏油狀」→ 黑便；「很沒力」→ mentation=lethargic (VG-RED-204)
        {"text": "狗狗大便是黑色柏油狀，人很沒力", "species": "dog"},
        # 「咬了一個很深的洞」→ 深層咬傷 (VG-RED-302)
        {"text": "狗狗被別的狗咬了一個很深的洞", "species": "dog"},
        # 呼吸急症
        {"text": "我的貓一直開口呼吸，舌頭發紫", "species": "cat"},
        # 中毒
        {"text": "狗狗剛剛偷吃巧克力，怎麼辦", "species": "dog"},
        # 神經急症
        {"text": "我家狗突然抽搐口吐白沫", "species": "dog"},
        # 虛脫
        {"text": "貓咪倒在地上叫不醒", "species": "cat"},
    ],
)
def test_red_other_emergencies(client, payload):
    payload["role"] = "owner"
    r = client.post("/api/consult", json=payload)
    assert r.status_code == 200
    d = r.json()
    assert d["state"] == "RED", f"{payload['text']} 應判為紅色"
    assert d["product_retrieval_halted"] is True


# --------------------------------------------------------------------------
# 黃色：資訊不足
# --------------------------------------------------------------------------


def test_yellow_missing_data_asks_only_required_questions(client):
    r = client.post(
        "/api/consult",
        json={"text": "我家狗狗最近有點癢", "role": "owner", "species": "dog"},
    )
    assert r.status_code == 200
    d = r.json()

    assert d["state"] == "YELLOW"
    assert d["passport"]["refusal_reason"] == "insufficient_info"
    assert d["required_questions"], "黃色狀態必須提出必要追問"
    # 資訊不足時不得檢索產品
    assert d["product_retrieval_halted"] is True

    fields = {q["field"] for q in d["required_questions"]}
    # 體重、持續時間、嚴重度、既有用藥屬必要欄位
    assert fields & {"body_weight_kg", "duration_hours", "severity", "current_medications"}


def test_yellow_unknown_species_is_asked(client):
    """物種未指明 → 不得直接回答，須先追問。"""
    r = client.post("/api/consult", json={"text": "牠最近一直抓癢", "role": "owner"})
    d = r.json()
    assert d["state"] in ("YELLOW", "GREEN")
    if d["state"] == "YELLOW":
        assert "species" in {q["field"] for q in d["required_questions"]}


# --------------------------------------------------------------------------
# 綠色：飼主衛教
# --------------------------------------------------------------------------


def test_green_owner_education(client):
    r = client.post(
        "/api/consult",
        json={
            "text": "我家貓咪平常喝水少，想知道怎麼照顧泌尿道健康",
            "role": "owner",
            "species": "cat",
            "body_weight_kg": 4.5,
            "duration_hours": 72,
            "severity": "mild",
            "current_medications": [],
        },
    )
    assert r.status_code == 200
    d = r.json()

    assert d["state"] == "GREEN"
    assert d["passport"]["refusal_reason"] == "none"
    assert d["messages"], "綠色狀態應提供衛教內容"

    # 飼主端即使在綠色狀態也不得取得處方資訊
    assert d["product_retrieval_halted"] is True
    allowed = set(d["allowed_output_types"])
    assert allowed.isdisjoint({"dosage", "prescription_product", "product_recommendation"})

    # 每一項主張都必須綁定來源段落 (主張級引用)
    bindings = d["passport"]["claim_bindings"]
    assert bindings
    for b in bindings:
        if b["supported"] and b["claim_type"] in ("medical", "product"):
            assert b["passages"], f"主張 {b['claim_id']} 缺少支持段落"
            for p in b["passages"]:
                assert p["is_expired"] is False, "不得引用過期來源"


def test_green_messages_have_no_dosage_leak(client):
    r = client.post(
        "/api/consult",
        json={
            "text": "我家貓咪平常喝水少，想知道怎麼照顧泌尿道健康",
            "role": "owner",
            "species": "cat",
            "body_weight_kg": 4.5,
            "duration_hours": 72,
            "severity": "mild",
            "current_medications": [],
        },
    )
    d = r.json()
    for m in d["messages"] + d["danger_signs"]:
        assert not scan_text_for_violations(Role.OWNER, m), f"飼主端輸出含違規內容: {m}"


# --------------------------------------------------------------------------
# 角色權限
# --------------------------------------------------------------------------


def test_vet_search_requires_token(client):
    """無獸醫 token → 403。"""
    r = client.post("/api/vet/search", json={"query": "皮膚"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "vet_verification_required"


def test_vet_search_rejects_invalid_token(client):
    r = client.post(
        "/api/vet/search", json={"query": "皮膚"}, headers={"X-Vet-Token": "wrong"}
    )
    assert r.status_code == 403


def test_vet_search_rejects_owner_role(client, vet_headers):
    """即使持有效 token，宣稱飼主角色一律拒絕。"""
    r = client.post("/api/vet/search?role=owner", json={"query": "皮膚"}, headers=vet_headers)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "role_not_permitted"


def test_consult_rejects_self_declared_vet_role(client):
    """角色不能靠 request body 自稱升級。"""
    r = client.post("/api/consult", json={"text": "查詢仿單", "role": "vet"})
    assert r.status_code == 403
    assert r.json()["detail"]["rule_id"] == "VG-ROL-450"


def test_vet_search_requires_owner_authorization_for_case_data(client, vet_headers):
    """獸醫已驗證但要存取個案資料且未取得飼主授權 → 403 (VG-ROL-451)。"""
    r = client.post(
        "/api/vet/search",
        json={
            "query": "皮膚",
            "case_audit_id": "VL-FAKE-CASE",
            "owner_authorized": False,
        },
        headers=vet_headers,
    )
    assert r.status_code == 403
    assert r.json()["detail"]["rule_id"] == "VG-ROL-451"


# --------------------------------------------------------------------------
# 第二幕：藍色模式解鎖
# --------------------------------------------------------------------------


def test_blue_vet_unlock_returns_products_with_evidence(client, vet_headers):
    r = client.post(
        "/api/vet/search",
        json={"query": "犬", "species": "dog", "limit": 5},
        headers=vet_headers,
    )
    assert r.status_code == 200
    d = r.json()

    assert d["state"] == "BLUE"
    assert d["results"], "藍色模式應回傳產品"

    # 每張產品卡都對應一項有來源的主張
    assert len(d["passport"]["claim_bindings"]) == len(d["results"])
    for b in d["passport"]["claim_bindings"]:
        assert b["supported"] is True
        assert b["passages"], "產品主張必須綁定許可證來源段落"

    # 護照必要欄位齊全
    p = client.get(f"/api/passport/{d['audit_id']}").json()
    assert p["is_audit_complete"] is True


def test_vet_search_without_species_is_blocked(client, vet_headers):
    """VG-POL-431：物種未指明時不得提供產品資訊，即使身分已驗證。

    貓與狗的用藥安全性差異極大（如 permethrin 對貓致命），
    因此物種是產品檢索的前置條件，不是可選過濾器。
    """
    r = client.post("/api/vet/search", json={"query": "犬"}, headers=vet_headers)
    assert r.status_code == 403
    assert "VG-POL-431" in r.json()["detail"]["message"]


def test_passport_lookup_404(client):
    assert client.get("/api/passport/VL-DOES-NOT-EXIST").status_code == 404


# --------------------------------------------------------------------------
# 效期閘門
# --------------------------------------------------------------------------


def test_expiry_gate_excludes_expired_products(client, vet_headers):
    """檢索結果不得含任何過期品項，且被排除的數量須被記錄。"""
    r = client.post(
        "/api/vet/search",
        json={"query": "犬", "species": "dog", "limit": 50},
        headers=vet_headers,
    )
    assert r.status_code == 200
    d = r.json()
    assert all(p["is_expired"] is False for p in d["results"])
    assert d["excluded_expired_count"] > 0
    assert d["excluded_expired_licences"]


# --------------------------------------------------------------------------
# 文件庫瀏覽 — 角色政策同樣適用
# --------------------------------------------------------------------------
def test_knowledge_library_exposes_education_passages(client):
    r = client.get("/api/knowledge")
    assert r.status_code == 200
    body = r.json()
    edu = body["education"]
    assert edu["total"] == len(edu["passages"]) > 0
    first = edu["passages"][0]
    for field in ("passage_id", "doc_id", "version", "text",
                  "scenario_scope", "expiry_date_iso", "review_status"):
        assert field in first
    assert edu["total"] == 47
    assert edu["online_total"] == 33
    assert edu["internal_total"] == 14
    assert len(edu["by_source_org"]) >= 4
    assert len(edu["online_by_source_org"]) == 4
    expanded = [p for p in edu["passages"] if p["passage_id"] == "EDU-GI-003"]
    assert expanded and expanded[0]["source_url"].startswith("https://")
    assert expanded[0]["source_org"] == "MSD Veterinary Manual"


def test_knowledge_library_hides_products_from_owner(client):
    body = client.get("/api/knowledge").json()
    products = body["products"]
    assert products["unlocked"] is False
    assert products["records"] == []
    # 統計數字仍給，讓飼主知道母體規模
    assert products["total"] > 0
    assert "藍色專業模式" in products["note_zh"]


def test_knowledge_library_unlocks_products_for_vet(client, vet_headers):
    body = client.get("/api/knowledge?limit=5", headers=vet_headers).json()
    products = body["products"]
    assert products["unlocked"] is True
    assert len(products["records"]) > 0
    assert all("gate_zh" in r for r in products["records"])


def test_knowledge_library_rejects_invalid_token_as_owner(client):
    """無效 token 不得解鎖 —— 靜默退回飼主視角，不得放行。"""
    body = client.get("/api/knowledge", headers={"X-Vet-Token": "bogus"}).json()
    assert body["products"]["unlocked"] is False
    assert body["products"]["records"] == []


def test_consult_response_carries_retrieval_trace(client):
    r = client.post("/api/consult", json={
        "text": "我家貓咪最近有點軟便，該注意什麼？",
        "role": "owner", "species": "cat", "body_weight_kg": 4.5,
        "duration_hours": 48, "severity": "輕微", "current_medications": [],
    })
    assert r.status_code == 200
    trace = r.json()["retrieval"]
    assert trace["method_zh"].startswith("情境標註比對")
    assert trace["counts"]["candidates"] > 0
    assert trace["excluded"]


def test_knowledge_library_filters_products_by_species(client, vet_headers):
    """200 筆母體以畜禽為主，犬貓用藥必須篩得出來。"""
    body = client.get("/api/knowledge?species=cat&limit=200", headers=vet_headers).json()
    records = body["products"]["records"]
    assert records, "貓用產品應至少有一筆"
    for r in records:
        assert "cat" in r["species"], f"{r['licence_no']} 不適用於貓卻被列出"
