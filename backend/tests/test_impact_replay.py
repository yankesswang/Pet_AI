"""VetLink AI — 第三幕：仿單更新後追回舊回答 (提案 §九)。"""
from __future__ import annotations

from app.engine.knowledge import get_kb
from app.models import SourcePassage


def _consult_for_urinary_education(client):
    """產生一筆會引用泌尿衛教段落的綠色回答。"""
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
    return r.json()


def test_impact_replay_requires_admin(client, vet_headers):
    """獸醫 token 不足以執行 Impact Replay。"""
    r = client.post(
        "/api/admin/impact-replay",
        json={"doc_id": "EDU-URINARY-CARE", "use_kb_as_old": True, "new_passages": []},
        headers=vet_headers,
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "admin_required"


def test_impact_replay_recalls_affected_answers(client, admin_headers):
    """提案 §九：更新仿單 → 找出引用舊段落的回答 → 風險分級 → 失效並通知。"""
    answer = _consult_for_urinary_education(client)
    audit_id = answer["audit_id"]

    cited = [
        p["passage_id"]
        for b in answer["passport"]["claim_bindings"]
        for p in b["passages"]
    ]
    assert cited, "回答必須有引用段落才能被回溯"

    kb = get_kb()
    old_passages = [
        kb.get_passage(pid) for pid in cited if kb.get_passage(pid) is not None
    ]
    doc_id = old_passages[0].doc_id

    # 只改這份文件的段落，且加入高風險關鍵詞（禁忌）
    doc_passages = [p for p in old_passages if p.doc_id == doc_id]
    new_passages = [
        SourcePassage(
            **{
                **p.model_dump(),
                "version": "2.0",
                "text": p.text + " 新增禁忌：腎功能不全動物不得使用本品。",
            }
        )
        for p in doc_passages
    ]

    r = client.post(
        "/api/admin/impact-replay",
        json={
            "doc_id": doc_id,
            "old_version": doc_passages[0].version,
            "new_version": "2.0",
            "old_passages": [p.model_dump(mode="json") for p in doc_passages],
            "new_passages": [p.model_dump(mode="json") for p in new_passages],
            "notify": True,
        },
        headers=admin_headers,
    )
    assert r.status_code == 200
    report = r.json()

    # 1. 差異比對
    assert report["diff_summary"]["material"] > 0
    # 2. 影響查找 —— 必須找回剛才那筆回答
    affected_ids = {a["audit_id"] for a in report["affected"]}
    assert audit_id in affected_ids, "受版本變更影響的回答未被找回"
    # 3. 風險分級：涉及「禁忌」屬高風險
    entry = next(a for a in report["affected"] if a["audit_id"] == audit_id)
    assert entry["risk_tier"] == "high"
    assert entry["action"] == "invalidate_immediately"
    # 5. 通知與稽核
    assert report["notified_count"] > 0
    assert entry["notified"] is True

    # 稽核事件已保存
    events = client.get(
        "/api/admin/impact-events", headers=admin_headers
    ).json()["events"]
    assert any(e["affected_audit_id"] == audit_id for e in events)


def test_impact_replay_removed_passage_is_high_risk(client, admin_headers):
    """段落被刪除 → 主張失去支持 → 高風險立即失效。"""
    answer = _consult_for_urinary_education(client)
    audit_id = answer["audit_id"]
    cited = [
        p["passage_id"]
        for b in answer["passport"]["claim_bindings"]
        for p in b["passages"]
    ]
    kb = get_kb()
    old = [kb.get_passage(pid) for pid in cited if kb.get_passage(pid)]
    doc_id = old[0].doc_id
    doc_passages = [p for p in old if p.doc_id == doc_id]

    r = client.post(
        "/api/admin/impact-replay",
        json={
            "doc_id": doc_id,
            "old_version": doc_passages[0].version,
            "new_version": "3.0",
            "old_passages": [p.model_dump(mode="json") for p in doc_passages],
            "new_passages": [],  # 全數刪除
        },
        headers=admin_headers,
    )
    assert r.status_code == 200
    report = r.json()
    entry = next(
        (a for a in report["affected"] if a["audit_id"] == audit_id), None
    )
    assert entry is not None
    assert entry["risk_tier"] == "high"
    assert entry["revalidated_state"] == "unsupported"


def test_impact_replay_empty_payload_rejected(client, admin_headers):
    r = client.post(
        "/api/admin/impact-replay",
        json={"doc_id": "NOPE", "old_passages": [], "new_passages": []},
        headers=admin_headers,
    )
    assert r.status_code == 422
