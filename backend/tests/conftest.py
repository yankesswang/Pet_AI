"""pytest 共用 fixtures。

每個測試 session 使用獨立的暫存稽核 DB，避免污染 app/data/audit.db。
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

# 讓 `pytest` 從 backend/ 目錄執行時能 import app 套件
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import audit as audit_module  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _isolated_store():
    """把全域 AuditStore 指向暫存檔案，測試結束後刪除。"""
    tmpdir = tempfile.mkdtemp(prefix="vetlink-test-")
    db_path = os.path.join(tmpdir, "audit.db")
    store = audit_module.get_store(db_path)
    yield store
    try:
        os.remove(db_path)
        os.rmdir(tmpdir)
    except OSError:
        pass


@pytest.fixture(scope="session")
def client(_isolated_store):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def vet_headers():
    return {"X-Vet-Token": "demo-vet-token"}


@pytest.fixture(scope="session")
def admin_headers():
    return {"X-Vet-Token": "demo-admin-token"}
