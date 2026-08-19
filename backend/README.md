# VetLink AI — Backend（Evidence Gate 寵藥安心閘門）

2026 中化智匯盃｜題目：動物用藥知識精準 APP。

系統的核心主張不是「推薦更多藥」，而是**在生成任何內容之前，先決定有沒有資格回答**。
所有閘門決策皆為**確定性、可離線重現、不呼叫 LLM**。

---

## 快速開始

本專案使用專屬虛擬環境（系統 `python3` 沒有 fastapi）：

前後端一起起（最省事，等後端真的回應才提示可以開）：

```bash
cd <repo>
./scripts/dev.sh            # 前端 5173 + 後端 2222
./scripts/dev.sh backend    # 只起後端
```

只起後端：

```bash
cd <repo>/backend
VENV=../.venv/bin/python

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
cd <repo>/backend

$VENV -m pytest tests/ -q      # 116 項測試
$VENV eval/run_eval.py         # 177 例同源案例庫，回歸用（七項安全指標）
$VENV eval/run_holdout.py      # 107 例獨立留出測試集，有效性用（十項指標）
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
    knowledge.py       受控知識庫＋文件效期閘門＋情境標註檢索
    claim_verifier.py  主張級引用驗證
    policy.py          角色輸出白名單＋文字層違規掃描
    passport.py        回答護照組裝
    impact_replay.py   版本變更影響回溯
  rules/*.yaml         47 條獸醫安全規則（泌尿／腸胃／皮膚耳部／呼吸／跨情境）
  data/                農業部開放資料 200 筆許可證 + demo 統計
tests/                 pytest 測試
eval/
  case_bank.py         同源案例庫 177 例（回歸：規則有沒有被正確執行）
  run_eval.py          七項安全指標評測
  data/holdout_v1.jsonl 獨立留出測試集 107 例（有效性：沒看過的說法會怎樣）
  holdout.py           留出集載入與結構驗證
  run_holdout.py       十項指標評測（含過度警示、對抗語言變體、混淆矩陣）
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
| GET | `/api/knowledge` | 文件庫瀏覽：衛教段落全文＋產品統計（產品明細需 token） |
| POST | `/api/consult` | 飼主端諮詢（第一幕），回應含 `retrieval` 檢索軌跡 |
| POST | `/api/vet/search` | 獸醫端產品檢索（第二幕，需 token） |
| GET | `/api/passport/{audit_id}` | 回答護照回查 |
| GET | `/api/answers` | 稽核紀錄列表 |
| GET | `/api/eval/holdout` | 留出測試集評測（當場執行 107 例，供前端「驗證結果」頁） |
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

## 可檢查性：文件庫與檢索軌跡

「系統只講有來源的話」如果不能被當場檢查，就只是一句宣稱。因此除了回答護照
（證明每一句出自哪一段），另有兩個互補的檢查面。

### 每則回答的檢索軌跡（`ConsultResponse.retrieval`）

四層漏斗，每一層都列得出是哪些段落：

```
文件庫總段落 → 本次檢索到 → 成為主張 → 實際講出來
     15            9           6          1
```

候選段落標明 `stage`：`displayed`（已輸出）／`verified`（通過驗證但不在本次輸出型別）／
`unsupported`（無來源已刪除）／`candidate`（超出主張上限）。

**被排除的段落同樣列出並逐段給原因**（情境不符／物種不符／逾效期／未審核）——
看不到被略過的部分，就無從判斷系統是挑對了、還是根本沒看到。
拒答時一樣附軌跡。

### 文件庫瀏覽（`GET /api/knowledge`）

```bash
# 飼主視角：衛教段落全文 + 產品統計數字
curl -s http://127.0.0.1:2222/api/knowledge | python -m json.tool

# 獸醫視角：解鎖產品成分與核准適應症
curl -s http://127.0.0.1:2222/api/knowledge?species=cat \
     -H 'X-Vet-Token: demo-vet-token'
```

**角色政策同樣套用在瀏覽器上**：衛教段落是飼主可見內容（綠色狀態本來就會輸出），
產品許可證屬藍色專業模式，未通過驗證只提供統計數字。瀏覽器不是政策的後門。

前端對應 `#library` 分頁；與 `#live` 頁一樣**沒有 mock 備援** ——
顯示一個不存在的文件庫，會讓所有核對結論失效。

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
  B 組（單純 RAG）對照由 `POST /api/compare` 提供（見下方「A/B/C 三組對照」）。
  該端點為**逐案例的質性對照展示**，不產生統計指標；上表數字仍只涵蓋 C 組。
- 規則包狀態為 `pending_vet_signoff`。
- 上述數字量測的是**系統是否做出正確的安全決策**（狀態、拒答、輸出型別、
  引用綁定），不是自然語言品質。

---

## 獨立留出測試集：系統在沒看過的說法上有效嗎

上表的 177 例與規則**同源撰寫** —— 案例措辭幾乎都直接落在 `structurer.py` 的
症狀詞典裡。它證明規則有被正確執行（回歸價值），但無法回答
「使用者換個說法會怎樣」，因為每一句都看過。

`eval/data/holdout_v1.jsonl`（107 例）刻意避開詞典字串，並補上同源案例庫
沒有的兩類案例：**陰性對照**（帶急症詞彙但不是急症）與**分診邊界**
（該就醫但非分秒必爭），因此能量到原本測不到的兩個方向 ——
過度警示與不足警示。與 case_bank 零文字重疊，每次測試都驗證。

同一套系統、同一份規則包，兩份資料集的差距：

| | case_bank（同源，177 例） | holdout（留出，107 例） |
| --- | ---: | ---: |
| 急症紅旗召回率 | **100.0%**（40/40） | **13.3%**（4/30） |

留出集主要結果（完整十項與根因分析見
[`docs/holdout-測試資料集與有效性驗證.md`](../docs/holdout-測試資料集與有效性驗證.md)）：

| 指標 | 目標 | **實測** | 樣本 | 結果 |
| --- | ---: | ---: | ---: | :---: |
| 危險漏判率 | ≤0% | **83.9%** | 26/31 | FAIL |
| 改寫後急症召回率 | ≥95% | **13.3%** | 4/30 | FAIL |
| 過度警示率 | ≤5% | **34.6%** | 9/26 | FAIL |
| 對抗提示洩漏率 | ≤0% | **0.0%** | 0/25 | PASS |
| 資訊不足追問率 | 100% | **66.7%** | 8/12 | FAIL |
| 飼主端產品檢索停止率 | 100% | **100.0%** | 107/107 | PASS |

讀法：**問題集中在分診的召回與特異度，不在輸出管制。**
26 例被漏判成綠色的急症案例，沒有任何一例洩漏產品或劑量 ——
輸出白名單不依賴語言理解，因此英文／簡體／角色扮演／提示注入
等 25 例語言變體攻擊全數無效。分診則相反：詞典是字面比對，
改寫即失效，且沒有否定與時態語意，導致「我想先知道尿不出來的徵兆」
這類衛教問題被判成急症。

前端有對應的分頁（`#validation`「驗證結果｜留出測試集」）：
它打 `GET /api/eval/holdout`，後端在該請求裡**當場把 107 例跑完**再回傳，
不是讀 `holdout_results.json`。頁面同時顯示混淆矩陣、按擾動型別拆解的召回率，
以及可篩選的 107 例逐案結果（含臨床依據）。

留出集的結果**未達標且未修**，這是刻意的：先量出來、講清楚根因，
修法（規則語意、否定處理、追問路徑、或啟用 LLM 症狀結構化）
才有可比較的基準。`tests/test_holdout.py` 已鎖住目前的失敗數，
只允許變好不允許變差。

---

## 設計約束

- **閘門決策路徑沒有任何 LLM 呼叫。** 規則評估、主張驗證、效期換算、影響回溯
  全部使用 stdlib + PyYAML，可離線重現、可逐條稽核。
- **主張級（非文件級）引用**：每一項醫療／產品主張各自綁定支持它的來源段落；
  找不到支持段落的主張會被刪除，或整體拒答。
- **角色政策以輸出白名單實作**，而非對模型下指令；飼主端另有文字層違規掃描
  作為最終防線。
- 規則是資料（`app/rules/*.yaml`），新增規則不需改程式碼。

---

## LLM 接入（選用）與安全邊界

系統**預設完全不呼叫 LLM**，行為與本文件其餘章節所述一致。以下為選用的接入方式。

### 安全邊界：LLM 只被允許出現在兩個位置

提案 §7.1 明確界定哪些模組可以由 LLM 決定。實作嚴格遵守：

| 模組 | LLM 可否介入 | 實作位置 |
| --- | :---: | --- |
| 症狀結構化器 | **可**（需 Schema 驗證） | `app/llm/structurer_llm.py` |
| 衛教語言轉譯 | **可**（限白名單段落） | `app/llm/translator_llm.py` |
| 必要追問引擎 | 否 | `app/engine/state.py` |
| 紅旗規則引擎 | 否 | `app/engine/rules.py` |
| 角色政策引擎 | 否 | `app/engine/policy.py` |
| 文件效期閘門 | 否 | `app/engine/knowledge.py` |
| 主張驗證器 | 否 | `app/engine/claim_verifier.py` |
| 稽核與回溯引擎 | 否 | `app/engine/impact_replay.py` |

> **閘門決策路徑（RED／YELLOW／GREEN／BLUE 的判定）永遠是確定性的。**
> `GET /api/health` 的 `llm_in_gate_path` 恆為 `false`，且不受任何環境變數影響。
> LLM 無法決定狀態、無法評估規則、無法驗證主張、無法判定效期。

### 環境變數

```bash
export OPENAI_API_KEY="sk-..."          # 未設定 → 整個 LLM 層停用，系統照常運作
export OPENAI_MODEL="gpt-4o-mini"       # 選用，預設 gpt-4o-mini
export OPENAI_BASE_URL="..."            # 選用，自架或代理端點
export VETLINK_LLM_TIMEOUT=10           # 選用，單次呼叫逾時秒數，預設 10

export VETLINK_LLM_STRUCTURING=on       # 症狀結構化改用 LLM 輔助（預設 off）
export VETLINK_LLM_TRANSLATION=on       # 衛教語言轉譯改用 LLM（預設 off）
```

兩個旗標**預設皆為 off**，因此未設定時所有既有測試與評測結果不變。

確認目前狀態：

```bash
curl -s http://127.0.0.1:2222/api/health | python -m json.tool
```

```json
{
  "llm_in_gate_path": false,
  "llm": {
    "enabled": false, "model": "gpt-4o-mini",
    "structuring": "off", "translation": "off", "key_present": false
  }
}
```

### 1. 症狀結構化器（`VETLINK_LLM_STRUCTURING=on`）

```
自然語言 → [LLM 抽取] → Pydantic Schema 驗證 → 與詞典結果安全合併 → facts
                                                                    ↓
                                                    Evidence Gate（確定性）
```

* LLM 輸出必須通過 `LLMStructuredSymptoms`（`extra="forbid"`，列舉值與數值範圍皆檢查）。
  任一欄位不合法 → **整份結果作廢**，退回純詞典結果。
* `symptoms` 只接受詞典既有的正規名稱。模型自創的症狀名會被丟棄 ——
  否則等於讓模型有機會繞過規則比對。
* 合併規則為**安全優先**：
  * 詞典命中的症狀一律保留，LLM 只能新增。
  * 純數值欄位只在詞典缺值時補齊，不覆寫。
  * 紅旗相關欄位衝突時**取較危險的值**
    （如詞典判 `can_urinate=False`、LLM 判 `True` → 取 `False`）。
  * `mentation` 衝突時取較嚴重者。
* 請求中明確給定的欄位（如 `species`）永遠優先於任何抽取結果。

### 2. 衛教語言轉譯（`VETLINK_LLM_TRANSLATION=on`）

```
已核准段落（白名單） → [LLM 改寫] → 主張驗證器 → 角色政策掃描 → 輸出
                                        ↓ 任一關失敗
                                     退回原始段落
```

* 輸入**只能**是已通過效期與審核閘門的段落原文；過期或未審核的段落直接拒絕改寫。
* 改寫後仍須通過詞彙涵蓋度檢查（門檻 0.60，高於主張驗證器預設的 0.55）——
  模型若加入來源沒有的內容，涵蓋度會掉下來，該段改寫即被丟棄。
* 再經 `policy.redact` 掃描角色違規（劑量／購買／確診／停換藥／人藥套用）。
* 任何一關失敗 → 回傳原文，行為與未啟用時相同。
* 改寫發生在**狀態判定與內容選取之後**，只替換顯示文字：主張綁定、護照引用
  與稽核紀錄一律保留段落原文與 `passage_id`，因此「這句話出自哪一段」不會因
  改寫而失真；危險徵兆的分類也一律以原文判定，避免改寫掉「立即」兩個字就把
  危險徵兆降級成一般衛教。
* `POST /api/consult` 的回應含 `llm_translation`，揭露這次幾段實際改寫、
  幾段退回原文；前端據此在回答卡上明示「本次有 N 段經 AI 改寫」。

### 優雅降級

`app/llm/client.py` 的所有公開方法**永不向請求路徑拋出例外**。
無金鑰、逾時、API 錯誤、輸出無法解析 → 一律回傳 `None`，由呼叫端退回既有確定性路徑。
逾時預設 10 秒、重試 1 次。

---

## A/B/C 三組對照（提案 §12.1）

```bash
curl -s -X POST http://127.0.0.1:2222/api/compare \
     -H 'Content-Type: application/json' -d '{}'
```

以**同一輸入**跑三組架構（預設為提案 §十 第一幕旗艦案例）：

| 組別 | 架構 | 實作 |
| --- | --- | --- |
| **A** | 使用者輸入 → LLM → 輸出 | 無閘門、無來源、無角色政策 |
| **B** | 使用者輸入 → 檢索 → LLM → 輸出 | 有文件級來源，但無閘門／角色政策／主張驗證 |
| **C** | 使用者輸入 → 結構化 → Evidence Gate → 白名單輸出 → 主張驗證 → 回答護照 | 完整系統 |

四個對比維度：`是否提供劑量` / `是否有來源` / `是否可稽核` / `是否攔截急症`。

> **A、B 組的「是否提供劑量」是由本系統既有的 `policy.scan_text_for_violations`
> 實際掃出來的，不是人工標註。** 同一支掃描器也套用在 C 組，結果為零違規。

### 無 API 金鑰時的誠實標示

沒有 `OPENAI_API_KEY` 時，A、B 兩組回傳**預錄範例**，並在回應中明確標示：

```json
{ "is_prerecorded": true, "label_zh": "預錄範例（示範用）" }
```

前端據此以警示樣式呈現。**預錄內容絕不會被呈現為即時模型呼叫的結果。**
C 組永遠是即時的確定性閘門判定，不受金鑰有無影響。
