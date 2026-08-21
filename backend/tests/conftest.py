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
def _no_external_calls():
    """測試一律離線執行。

    應用程式啟動時會讀取 .env，因此光是在 shell 清掉環境變數並不夠 ——
    測試可能在開發者本機意外打到真實 LLM，付費、變慢，而且讓結果不可重現。
    這裡在 import app 之前就把金鑰與旗標清乾淨，並攔截 socket 連線，
    讓任何漏網的外部呼叫**直接失敗**而不是靜默送出。
    """
    import socket

    for key in (
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY",
        "VETLINK_LLM_STRUCTURING", "VETLINK_LLM_TRANSLATION",
    ):
        os.environ.pop(key, None)
    os.environ["VETLINK_LLM_STRUCTURING"] = "off"
    os.environ["VETLINK_LLM_TRANSLATION"] = "off"

    real_connect = socket.socket.connect
    allowed = ("127.0.0.1", "::1", "localhost")

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in allowed:
            raise RuntimeError(
                f"測試嘗試連線外部主機 {host} —— 測試必須離線可重現。"
            )
        return real_connect(self, address, *args, **kwargs)

    socket.socket.connect = guarded_connect
    try:
        yield
    finally:
        socket.socket.connect = real_connect


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
