# VetLink AI — Backend（Evidence Gate 寵藥安心閘門）

2026 中化智匯盃｜題目：動物用藥知識精準 APP。

系統的核心主張不是「推薦更多藥」，而是**在生成任何內容之前，先決定有沒有資格回答**。
所有閘門決策皆為**確定性、可離線重現、不呼叫 LLM**。

---

## 快速開始

本專案使用專屬虛擬環境（系統 `python3` 沒有 fastapi）：

```bash
VENV=/home/trx50/Project/Pet_AI/.venv/bin/python
cd /home/trx50/Project/Pet_AI/backend

# 啟動 API（預設 2222 埠）
$VENV -m uvicorn app.main:app --reload --port 2222

# 健康檢查
curl http://127.0.0.1:2222/api/health

# 互動式 API 文件
open http://127.0.0.1:2222/docs
```

> 所有指令都必須在 `backend/` 目錄下執行（`sys.path` 需含 `.`）。

### 測試與評測

```bash
cd /home/trx50/Project/Pet_AI/backend

$VENV -m pytest tests/ -q      # 34 項測試
$VENV eval/run_eval.py         # 177 例合成案例安全評測
```

### 相依安裝（如需重建環境）

```bash
$VENV -m pip install -r requirements.txt
```

---

## 架構

```
app/
  main.py              FastAPI 應用、CORS（http://localhost:5173）
  models.py            Pydantic 資料模型（含回答護照）
  api/
    routes.py          HTTP 端點、獸醫身分驗證
    service.py         閘門決策 → 內容組裝 → 護照 → 稽核
  engine/
    structurer.py      症狀結構化（確定性詞典，非 LLM）
    rules.py           規則引擎（規則是 YAML 資料，不是硬編碼 if）
    state.py           Evidence Gate 四狀態機＋五項資格檢查
    knowledge.py       受控知識庫＋文件效期閘門
    claim_verifier.py  主張級引用驗證
    policy.py          角色輸出白名單＋文字層違規掃描
    passport.py        回答護照組裝
    impact_replay.py   版本變更影響回溯
  rules/*.yaml         47 條獸醫安全規則（泌尿／腸胃／皮膚耳部／呼吸／跨情境）
  data/                農業部開放資料 200 筆許可證 + demo 統計
tests/                 pytest 測試
eval/                  合成案例庫與安全指標評測
```

### 四種狀態（提案 §四）

| 狀態 | 意義 | 行為 |
| --- | --- | --- |
| RED | 不得推薦 | 急症紅旗 → 完全停止產品檢索，急診轉介 |
| YELLOW | 資訊不足 | 只問固定必要問題，不直接回答 |
| GREEN | 飼主可見 | 經獸醫審核的衛教內容 |
| BLUE | 獸醫專業模式 | 身分驗證＋飼主授權後解鎖仿單與產品資訊 |

### 五項資格檢查

安全資格 → 角色資格 → 資料資格 → 證據資格 → 一致性資格（順序即優先序）。

---

## API 端點

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| GET | `/api/health` | 健康檢查、規則包版本 |
| GET | `/api/stats` | 知識庫／規則／稽核統計（含效期閘門證據） |
| POST | `/api/consult` | 飼主端諮詢（第一幕） |
| POST | `/api/vet/search` | 獸醫端產品檢索（第二幕，需 token） |
| GET | `/api/passport/{audit_id}` | 回答護照回查 |
| GET | `/api/answers` | 稽核紀錄列表 |
| POST | `/api/admin/impact-replay` | 版本變更影響回溯（第三幕，需 admin token） |
| GET | `/api/admin/impact-events` | 影響事件紀錄 |

### 身分驗證

Demo 使用靜態 token（正式版接獸醫師執照 API）：

```bash
X-Vet-Token: demo-vet-token      # 獸醫
X-Vet-Token: demo-admin-token    # 中化管理者
```

亦接受 `Authorization: Bearer <token>`。可用環境變數
`VETLINK_VET_TOKEN` / `VETLINK_ADMIN_TOKEN` 覆寫。

**角色不能由 request body 自稱**：以 `role: vet` 送出但未附有效 token 一律 403。

---

## 三幕 Demo（提案 §十）

### 第一幕｜系統拒絕看似合理的用藥要求

```bash
curl -X POST http://127.0.0.1:2222/api/consult \
  -H 'Content-Type: application/json' \
  -d '{"text":"我的貓一直進砂盆但尿不出來，可以先吃什麼藥？",
       "role":"owner","species":"cat","can_urinate":false}'
```

→ `state: RED`、`product_retrieval_halted: true`、觸發 `VG-RED-001`，
不輸出任何藥品或劑量，提供急診轉介與就診摘要。

### 第二幕｜同一案例，不同角色看到不同內容

```bash
# 無 token → 403
curl -X POST http://127.0.0.1:2222/api/vet/search \
  -H 'Content-Type: application/json' -d '{"query":"犬","species":"dog"}'

# 獸醫 token → BLUE，回傳產品並排除過期品項
curl -X POST http://127.0.0.1:2222/api/vet/search \
  -H 'Content-Type: application/json' -H 'X-Vet-Token: demo-vet-token' \
  -d '{"query":"犬","species":"dog","limit":5}'
```

### 第三幕｜仿單更新後追回舊回答

```bash
curl -X POST http://127.0.0.1:2222/api/admin/impact-replay \
  -H 'Content-Type: application/json' -H 'X-Vet-Token: demo-admin-token' \
  -d '{"doc_id":"EDU-URINARY-CARE","use_kb_as_old":true,
       "old_version":"1.1","new_version":"2.0",
       "new_passages":[{"passage_id":"EDU-URI-001","doc_id":"EDU-URINARY-CARE",
        "version":"2.0","text":"新增禁忌：腎功能不全動物不得使用本品。","review_status":"approved"}]}'
```

→ 差異比對 → 找出引用舊段落的回答 → 風險分級 → 高風險立即失效並通知。

---

## 文件效期閘門：本系統最關鍵的設計決定

農業部開放資料母體 13,738 筆許可證中，**有 1,503 筆已逾有效期間，但來源本身沒有
標註「(已失效)」**。若系統採信來源的失效標記欄位，這些過期文件會直接洩漏進回答。

因此 `knowledge.compute_expiry()` **只看日期、不看標記**：把民國日期換算為西元後，
與基準日（Demo 為 2026-08-19）比較。

真實案例：

```
動物藥入字第07363號「一錠除犬用滴劑（巨型犬）」
  有效期間原文 = "至115年06月30日止"   ← 沒有任何失效標記
  民國 115/06/30 → 西元 2026-06-30
  基準日 2026-08-19 → 已過期
```

`tests/test_expiry_gate.py` 針對這一點做完整回歸測試，證明證據資格檢查會擋下
**連上游資料源自己都標錯的**過期文件。demo 資料集中共有 20 筆同類案例
（`GET /api/stats` 的 `expiry_gate.date_only_expired_count`）。

---

## 實測結果（提案 §12.1）

執行 `$VENV eval/run_eval.py`。案例庫 177 例（提案目標 150～200），
其中安全陷阱 87 例（提案目標 ≥50）。

| 評估項目 | 目標值 | **實測值** | 樣本 |
| --- | ---: | ---: | ---: |
| 急症紅旗召回率 | ≥95% | **100.0%** | 40/40 |
| 飼主端處方劑量洩漏率 | 0% | **0.0%** | 0/127 |
| 主張引用正確率 | ≥95% | **100.0%** | 762/762 |
| 無證據正確拒答率 | ≥90% | **100.0%** | 50/50 |
| 角色權限違反率 | 0% | **0.0%** | 0/127 |
| 受版本變更影響回答找回率 | ≥95% | **100.0%** | 20/20 |
| 回答具完整稽核紀錄 | 100% | **100.0%** | 127/127 |
| 與獸醫風險分級一致率 | ≥85% | **NOT_MEASURED** | — |

### 誠實標示（提案投稿原則：目標值與實測值必須分開標示）

- 案例為依公開臨床指南（Merck Veterinary Manual / AAHA / WSAVA）撰寫的
  **合成案例，非真實病歷**，亦未經合作獸醫簽核。
- 「與獸醫風險分級一致率」需兩名以上獸醫共識標註，**無法由自動化評測產生**，
  故不輸出數字。
- 本評測為 **C 組（VetLink AI）單組結果**；提案 §12.1 的 A 組（一般 LLM）與
  B 組（單純 RAG）對照需另行執行。
- 規則包狀態為 `pending_vet_signoff`。
- 上述數字量測的是**系統是否做出正確的安全決策**（狀態、拒答、輸出型別、
  引用綁定），不是自然語言品質。

---

## 設計約束

- **閘門決策路徑沒有任何 LLM 呼叫。** 規則評估、主張驗證、效期換算、影響回溯
  全部使用 stdlib + PyYAML，可離線重現、可逐條稽核。
- **主張級（非文件級）引用**：每一項醫療／產品主張各自綁定支持它的來源段落；
  找不到支持段落的主張會被刪除，或整體拒答。
- **角色政策以輸出白名單實作**，而非對模型下指令；飼主端另有文字層違規掃描
  作為最終防線。
- 規則是資料（`app/rules/*.yaml`），新增規則不需改程式碼。
