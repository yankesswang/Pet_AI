"""VetLink AI — FastAPI 應用進入點。

啟動（於 repo 根目錄）：
    cd backend
    ../.venv/bin/python -m uvicorn app.main:app --reload --port 2222
"""
from __future__ import annotations

from fastapi import FastAPI

# 專案根目錄的 .env 於啟動時載入，讓 OPENAI_API_KEY 等設定不必手動 export。
# 已存在的環境變數優先，CI／容器可直接覆寫。
try:
    from dotenv import load_dotenv
    from pathlib import Path

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
except ImportError:  # python-dotenv 未安裝時沿用純環境變數
    pass

from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router

DESCRIPTION = """
**VetLink AI｜Evidence Gate 寵藥安心閘門** — 2026 中化智匯盃／動物用藥知識精準 APP。

系統的核心不是「推薦更多」，而是**在生成之前決定是否有資格回答**：

* 四種狀態：紅（不得推薦）、黃（資訊不足）、綠（飼主可見）、藍（獸醫專業模式）
* 五項資格檢查：安全、資料、角色、證據、一致性
* 回答護照：主張級（非文件級）引用、文件版本、適用範圍、拒絕原因、稽核編號
* Impact Replay：仿單更新後回溯並處理受影響的歷史回答

閘門決策路徑**完全確定性、不呼叫 LLM**，可離線重現。
"""

app = FastAPI(
    title="VetLink AI — Evidence Gate API",
    description=DESCRIPTION,
    version="1.0.0",
)

# Vite 開發伺服器
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict:
    return {
        "service": "VetLink AI — Evidence Gate",
        "docs": "/docs",
        "health": "/api/health",
    }
