"""飼主授權憑證的回歸測試。

鎖住的性質：預設拒絕、綁定個案、範圍分離、有時效、一次性、可撤回、可稽核。
這些是「授權真的發生過」的可驗證條件，取代原本由呼叫端自我宣告的布林值。
"""
from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.authz import (  # noqa: E402
    SCOPE_CASE_READ,
    SCOPE_PRODUCT_SEARCH,
    GrantStore,
)


@pytest.fixture()
def store():
    return GrantStore()


def test_absent_token_is_unauthorized(store):
    """預設未授權 —— 沒有憑證就是沒有授權。"""
    r = store.verify(None, case_audit_id="VL-1", required_scope=SCOPE_CASE_READ)
    assert r.authorized is False


def test_valid_grant_authorizes(store):
    tok = store.issue(
        case_audit_id="VL-1", owner_ref="o", vet_ref="v", scopes=[SCOPE_CASE_READ]
    )
    assert store.verify(
        tok, case_audit_id="VL-1", required_scope=SCOPE_CASE_READ
    ).authorized


def test_grant_is_bound_to_one_case(store):
    """換個個案就無效 —— 授權不是通行證。"""
    tok = store.issue(
        case_audit_id="VL-1", owner_ref="o", vet_ref="v", scopes=[SCOPE_CASE_READ]
    )
    assert not store.verify(
        tok, case_audit_id="VL-OTHER", required_scope=SCOPE_CASE_READ
    ).authorized


def test_scopes_are_separated(store):
    """個案存取與產品檢索須分別授權。"""
    tok = store.issue(
        case_audit_id="VL-1", owner_ref="o", vet_ref="v", scopes=[SCOPE_CASE_READ]
    )
    assert not store.verify(
        tok, case_audit_id="VL-1", required_scope=SCOPE_PRODUCT_SEARCH
    ).authorized


def test_grant_is_single_use(store):
    tok = store.issue(
        case_audit_id="VL-1", owner_ref="o", vet_ref="v", scopes=[SCOPE_CASE_READ]
    )
    assert store.verify(tok, case_audit_id="VL-1", required_scope=SCOPE_CASE_READ).authorized
    assert not store.verify(
        tok, case_audit_id="VL-1", required_scope=SCOPE_CASE_READ
    ).authorized


def test_grant_expires(store):
    tok = store.issue(
        case_audit_id="VL-1", owner_ref="o", vet_ref="v",
        scopes=[SCOPE_CASE_READ], ttl_seconds=1,
    )
    time.sleep(1.2)
    r = store.verify(tok, case_audit_id="VL-1", required_scope=SCOPE_CASE_READ)
    assert r.authorized is False
    assert "逾有效期" in r.reason_zh


def test_grant_can_be_revoked(store):
    tok = store.issue(
        case_audit_id="VL-1", owner_ref="o", vet_ref="v", scopes=[SCOPE_CASE_READ]
    )
    probe = store.verify(
        tok, case_audit_id="VL-1", required_scope=SCOPE_CASE_READ, consume=False
    )
    assert store.revoke(probe.grant_id) is True
    assert not store.verify(
        tok, case_audit_id="VL-1", required_scope=SCOPE_CASE_READ
    ).authorized


def test_tampered_grant_is_rejected(store):
    """簽章保護內容 —— 改個案編號騙不過驗證。"""
    tok = store.issue(
        case_audit_id="VL-1", owner_ref="o", vet_ref="v", scopes=[SCOPE_CASE_READ]
    )
    body, sig = tok.split(".", 1)
    forged = store.issue(
        case_audit_id="VL-EVIL", owner_ref="o", vet_ref="v", scopes=[SCOPE_CASE_READ]
    ).split(".", 1)[0]
    r = store.verify(
        f"{forged}.{sig}", case_audit_id="VL-EVIL", required_scope=SCOPE_CASE_READ
    )
    assert r.authorized is False
    assert "簽章無效" in r.reason_zh


def test_usage_is_logged_for_audit(store):
    tok = store.issue(
        case_audit_id="VL-1", owner_ref="o", vet_ref="v", scopes=[SCOPE_CASE_READ]
    )
    store.verify(tok, case_audit_id="VL-1", required_scope=SCOPE_CASE_READ)
    log = store.usage_log("VL-1")
    assert len(log) == 1
    assert log[0]["scope"] == SCOPE_CASE_READ
