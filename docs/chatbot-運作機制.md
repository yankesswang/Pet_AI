# VetLink AI Chatbot 運作機制

> 對象：開發者、評審、要接手這份程式碼的人
> 對應程式碼版本：`rules_bundle_version` 由 `GET /api/health` 取得（目前 47 條規則）
> 撰寫依據：實際讀碼與實際執行結果，非設計稿

---

## 0. 一句話總結

這個 chatbot **不是「先生成、再過濾」的聊天機器人**，而是
**「先判定有沒有資格回答，再從已審核的段落裡挑句子輸出」**。

使用者送出一句話之後，系統做的第一件事不是想答案，而是跑一組確定性檢查，
決定這次落在 **RED／YELLOW／GREEN／BLUE** 哪個狀態；狀態決定了**允許輸出的型別白名單**，
內容只能從白名單容許的來源裡組裝。

因此有一個關鍵性質：

> **系統沒有「模型不小心說出劑量」這種失效模式** —— 因為飼主端的劑量類輸出型別
> 根本沒被放進允許清單，那條路徑不存在，而不是被事後攔下來。

---

## 1. 使用者實際會碰到的入口

前端有六個頁面（[frontend/src/App.tsx:31-37](../frontend/src/App.tsx#L31-L37)），
其中只有一個是**真的 chatbot**：

| 頁面 | 檔案 | 性質 |
| --- | --- | --- |
| **我要提問（LIVE）** | [frontend/src/acts/LiveAsk.tsx](../frontend/src/acts/LiveAsk.tsx) | **真實對話**，使用者輸入任意問題，全部走後端 |
| **文件庫** | [frontend/src/acts/Library.tsx](../frontend/src/acts/Library.tsx) | **真實資料**，攤開受控知識庫全部內容，供核對回答來源 |
| 四種狀態總覽 / 第一幕 / 黃色 / 第二幕 / 第三幕 | `acts/Act1~Act3.tsx`, `AmberAct.tsx` | 劇本式導覽，輸入固定，預設吃 `src/mocks` fixtures |
| 對照組 A/B/C | `acts/Compare.tsx` | 同一輸入跑三種架構的質性對照 |

分頁可用網址 hash 直接連結（`#live`、`#library`、`#act1`…），重新整理會停在原地。

**LIVE 頁與文件庫頁跟其他頁最重要的差異**（[LiveAsk.tsx:1-13](../frontend/src/acts/LiveAsk.tsx#L1-L13)）：

* **永不使用 mock 備援**。其他頁在後端不通時會靜默退回 fixtures（`withFallback`，
  [api.ts:122](../frontend/src/lib/api.ts#L122)）；`consultFree()` 則直接把錯誤拋給 UI，
  頁面顯示「這次沒有拿到真實判定」而不是罐頭答案。
* 狀態列的「連線中」是真的每 20 秒打 `/api/health`，不看 `VITE_USE_MOCKS`。
* 失敗原因分四類（`unreachable` / `timeout` / `http` / `client`），
  前端解析失敗時不會叫使用者去重啟其實運作正常的後端。

---

## 2. 一次提問的完整流程

```
使用者輸入（自然語言 + 可選結構化欄位）
        │
        │  POST /api/consult          routes.py:consult
        ▼
┌──────────────────────────────────────────────────────────┐
│ 1. 身分層                                                 │
│    role=vet/admin 但無有效 token → 403（角色不能自稱）      │
└──────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────┐
│ 2. 症狀結構化   structurer.py / structurer_llm.py          │
│    自然語言 → facts dict（症狀、物種、體重、時長、意圖…）    │
│    預設純詞典比對；LLM 旗標開啟時另做 schema 驗證後安全合併  │
└──────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────┐
│ 3. 候選來源檢索 knowledge.py                               │
│    依情境標註取衛教段落，**先過效期＋物種閘門**              │
│    每段落原文 → 一項 claim（受控生成的核心）                │
└──────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────┐
│ 4. Evidence Gate 五項資格檢查   state.py:decide            │
│    安全 → 角色 → 資料 → 證據 → 一致性（順序即優先序）        │
│    輸出：RED / YELLOW / GREEN / BLUE + allowed_output_types │
└──────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────┐
│ 5. 內容組裝     service.py:_compose                       │
│    嚴格照 allowed_output_types 白名單挑內容                │
│    文字只有兩個來源：規則的 owner_message、已驗證段落原文    │
│    （可選）衛教語言轉譯 —— 只換顯示文字，不動引用            │
└──────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────┐
│ 6. 政策文字掃描 policy.py:redact                           │
│    最終防線：掃到劑量/購買/確診/停換藥/人藥套用 → 刪除該句   │
└──────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────┐
│ 7. 回答護照 + 稽核  passport.py / store/audit.py           │
│    audit_id、狀態、規則、主張級引用、文件版本、拒絕原因      │
│    寫入 SQLite（answers / citations），供回查與影響回溯      │
└──────────────────────────────────────────────────────────┘
        ▼
   ConsultResponse → 前端依 state 渲染
```

核心進入點：[backend/app/api/service.py:79](../backend/app/api/service.py#L79) `ConsultService.consult()`。

---

## 3. 步驟細節

### 3.1 症狀結構化（自然語言 → facts）

[backend/app/engine/structurer.py:239](../backend/app/engine/structurer.py#L239)

**預設是確定性詞典比對，不呼叫 LLM。** 做四件事：

1. **症狀正規化**：74 組正規症狀名，每組帶多個口語變體。
   例如 `尿不出來` ← 「尿不出來 / 尿不出 / 完全沒尿 / 無法排尿 / 解不出尿 / 沒有尿」。
   規則引擎只認得正規名，所以這層是規則能不能命中的前提。
2. **欄位抽取**：物種、精神狀態、體重（`4.5公斤`）、年齡、時長（`3天` → 72 小時）、體溫。
   **請求裡明確給定的欄位永遠優先於文字抽取結果。**
3. **意圖判定**：`dosage_request` / `purchase_request` / `prescription_request` /
   `medication_change_request` / `diagnosis_request` / `cross_species_use` / `general`。
   順序即優先序，這個欄位驅動政策層的攔截。
4. **情境分類**：泌尿／呼吸／腸胃／皮膚耳部／跨情境，決定要撈哪些衛教段落。

保守設計：`_find_species` 在「零命中」或「同時提到貓和狗」時都回 `None`，
交給黃色狀態追問，不猜。

> ⚠️ **這一層是目前系統最弱的地方。** 詞典是字面比對，沒有否定與時態語意；
> 使用者換個說法就命不中，規則自然不會成立。留出測試集上的急症召回率只有
> 13.3%（同源案例庫是 100%）。詳見 §10 第 6 點 —— 讀本文其餘章節時請記得，
> 「閘門判得準」與「閘門有被正確執行」是兩件事，本系統目前只證明了後者。

### 3.2 Evidence Gate 五項資格檢查

[backend/app/engine/state.py:467](../backend/app/engine/state.py#L467) `EvidenceGate.decide()`

**順序就是優先序，前面的檢查失敗就直接決定狀態，不再往下跑：**

| # | 檢查 | 內容 | 失敗結果 |
| --- | --- | --- | --- |
| 1 | **安全資格** | 跑所有 `severity: red` 規則 | **RED**，`product_retrieval_halted=True` |
| 2 | **角色資格** | 跑 `policy` / `role` 規則；藍色模式需 token + 飼主授權 | 飼主 → GREEN（但禁止型別已被擋）；其他 → YELLOW |
| 3 | **資料資格** | 飼主端五項必填 + 矛盾偵測 | **YELLOW**，只輸出必要追問 |
| 4 | **證據資格** | 每項主張要有未過期、已審核的來源段落 | 拒答（`INSUFFICIENT_EVIDENCE`） |
| 5 | **一致性資格** | 同一文件多版本且內容不一致 | 拒答（`SOURCE_CONFLICT`），轉介獸醫 |

幾個容易被忽略的設計：

* **紅旗規則用三值邏輯**（`true` / `false` / `unknown`，[rules.py:162](../backend/app/engine/rules.py#L162)）。
  缺欄位時回 `unknown` 而非 `false`，代表「無法排除」，會被記進護照的 `rules_failed`，
  由資料資格接手追問。**缺資料不等於安全。**
* **RED 狀態仍會跑角色檢查**，目的是把護照欄位填滿，但不改變狀態。
* **飼主端永遠 `product_retrieval_halted=True`**，即使全部檢查通過（GREEN）也一樣 ——
  飼主端從不進行處方產品檢索。

**資料資格的五項必填**（[state.py:34-40](../backend/app/engine/state.py#L34-L40)）：
物種、體重、症狀持續時間、嚴重度、目前用藥。缺任一項 → YELLOW。
另外會擋掉矛盾輸入（同時聲稱可排尿又完全無法排尿、體重 >120kg、年齡 >360 個月…）。

**注意檢查順序：角色資格排在資料資格之前。** 這不是隨意排的 ——
索取劑量／購買／確診這類請求會先被政策規則攔下，
**不會因為資料不足就改判黃色去問東問西**，該拒絕的直接拒絕。

實測六種政策意圖在**完全沒有給任何結構化欄位**（資料嚴重不足）時的判定：

| 意圖 | 狀態 | 成立規則 | 追問題數 |
| --- | --- | --- | ---: |
| `dosage_request` | GREEN | VG-POL-420 | 0 |
| `purchase_request` | GREEN | VG-POL-431 | 0 |
| `prescription_request` | GREEN | VG-POL-431 | 0 |
| `medication_change_request` | GREEN | VG-POL-431 | 0 |
| `diagnosis_request` | GREEN | VG-POL-431 | 0 |
| `cross_species_use` | GREEN | VG-POL-431 | 0 |

六種全部在政策關被攔下，沒有一個掉進黃色去問體重跟持續時間。

> 這裡原本另有一份 `POLICY_INTENTS` 常數，看起來像在控制這個行為，
> 但**全專案從未被引用**。已移除並在原地留下說明 ——
> 真正保證這件事的是檢查順序與上表那幾條 VG-POL 規則。

### 3.3 規則是資料，不是 if

[backend/app/rules/*.yaml](../backend/app/rules/) — 47 條規則，五個 pack：

| pack | 情境 | 條數 |
| --- | --- | ---: |
| `urinary` | 泌尿 | 6 |
| `gastrointestinal` | 腸胃 | 9 |
| `dermatology` | 皮膚耳部 | 8 |
| `respiratory` | 呼吸 | 7 |
| `crosscutting` | 跨情境（政策／角色／毒理） | 17 |

每條規則的 schema：`rule_id`、`version`、`severity`（red/yellow/policy/role）、
`species`、`presentations`、`required_questions`、`red_flag_conditions`（條件樹）、
`system_action`、`allowed_outputs`、`forbidden_outputs`、`owner_message`（獸醫審核過的固定文案）。

條件樹支援 `all_of` / `any_of` / `none_of` 巢狀，葉節點運算子為
`eq / ne / in / gte / lte / gt / lt / contains_any`。**新增規則不需要改任何 Python。**

`bundle_version` 是所有 pack 版本的 SHA256 指紋，寫進每一張護照 ——
之後才能回答「這個回答是用哪一版規則產生的」。

> 規則的 `review_status` 目前是 `pending_vet_signoff`：內容依 Merck / AAHA / WSAVA
> 公開指南重新結構化撰寫，**尚未經合作獸醫正式簽核**。

### 3.4 主張級引用（不是文件級）

這是與一般 RAG 差異最大的地方。

**先看候選來源怎麼來的**（[service.py:157](../backend/app/api/service.py#L157)）。
兩個來源，順序即優先序：

1. **情境段落**：依 facts 的 `scenarios`（泌尿／腸胃／皮膚耳部／呼吸／跨情境），
   取 `scenario_scope` 標註相符的段落。
2. **政策／毒理／急症段落**（`EDU-POL-*`、`EDU-TOX-*`、`EDU-EMG-*`）：一律納入候選，
   讓「處方藥須由獸醫開立」「人用藥不得用於犬貓」這類主張永遠找得到來源。

兩者都套用**物種過濾**與**效期閘門**。

> 這裡原本走關鍵字計分（`search_passages`）：情境查詢字串只要有任一中文 2-gram
> 命中就得分，**沒有最低分數門檻**。結果問「貓軟便」會一併撈到呼吸道段落
> （命中「食慾」）與泌尿段落（命中「飲水」）。那些段落有來源、通得過主張驗證，
> 但對這次提問不切題。現在改用段落上的 `scenario_scope` 標註比對 ——
> 情境是資料，比對結果確定且可稽核，與「規則是資料」是同一個原則。
>
> 同時修掉的還有：政策／毒理／急症那一批段落原本**漏掉物種過濾**，
> 導致狗的案例會拿到 `EDU-EMG-001`（貓專屬的尿道阻塞衛教，內文提到「公貓」）。
> 回歸測試在 [tests/test_retrieval.py](../backend/tests/test_retrieval.py)。

**內容產生方式是「選段落」，不是「寫句子」**（[service.py:188](../backend/app/api/service.py#L188)）：

```python
# 主張直接取自來源段落原文 —— 因此必然可被該段落支持
for i, p in enumerate(passages[:6], start=1):
    claims.append(make_claim(f"C{i:02d}", text=p.text, ...))
```

然後 [claim_verifier.py:85](../backend/app/engine/claim_verifier.py#L85) 逐項驗證：

1. 先過**效期閘門 + 審核狀態閘門**，過期或未審核段落直接出局。
2. 算**詞彙涵蓋度**（中文 2-gram + 英數詞，扣掉停用詞），門檻 **0.55**。
3. 涵蓋度不足 → **刪除該主張**；醫療／產品主張全數落空 → **整體拒答並交回獸醫**。

護照裡因此可以逐項回答「這句話是哪一段、哪一版、有效期到什麼時候」，
而不是只丟一份文件清單。

### 3.5 文件效期閘門（整個系統最關鍵的一個決定）

[backend/app/engine/knowledge.py:339](../backend/app/engine/knowledge.py#L339)

```python
def compute_expiry(expiry_date_iso, as_of):
    """只看日期，不看來源的失效標記。"""
```

原因是實證的：農業部開放資料母體 13,738 筆許可證中，
**1,503 筆已逾有效期間，但來源本身沒有標「(已失效)」**。
採信來源的標記欄位 = 這些過期文件直接洩漏進回答。

真實案例（demo 資料集內）：

```
動物藥入字第07363號「一錠除犬用滴劑（巨型犬）」
  有效期間原文 = "至115年06月30日止"   ← 沒有任何失效標記
  民國 115/06/30 → 西元 2026-06-30
  基準日 2026-08-19 → 已過期
```

系統會把「來源說沒過期、但日期算出來已過期」的案例記進 `marker_disagreements`，
可由 `GET /api/stats` 的 `expiry_gate.date_only_expired_count` 查看。
`tests/test_expiry_gate.py` 對此做回歸測試。

### 3.6 角色政策：白名單，不是提示詞

[backend/app/engine/policy.py](../backend/app/engine/policy.py)

兩層：

**第一層｜輸出型別白名單**
`allowed = 角色白名單 ∩ 狀態白名單 − 飼主硬性禁令`

飼主硬性禁令（任何狀態都不可覆寫）：
`diagnosis`、`dosage`、`prescription_dosage`、`owner_facing_dosage`、`home_medication`、
`medication_change_instruction`、`purchase_link`、`prescription_product`、
`human_drug_dosing`、`cross_species_dosing`、`induce_vomiting_instruction`。

**第二層｜文字掃描最終防線**（[policy.py:221](../backend/app/engine/policy.py#L221)）
正則掃描已組裝的文字，五類違規：處方劑量、購買連結、疾病確診、自行停換藥、人藥套用。
掃到 → `redact()` 刪掉那一句，並在回覆末尾註記刪了幾段。

有一個必要的例外處理：**否定語境守衛**（`NEGATION_GUARDS`）。
「**不可**給貓吃普拿疼」不能被當成違規刪掉 —— 那正是要說的安全警告。

> 同一支掃描器也被用在 A/B 對照組上，所以「A 組洩漏劑量」是**實際掃出來的**，
> 不是人工標註。

### 3.7 回答護照與稽核

[backend/app/engine/passport.py:54](../backend/app/engine/passport.py#L54)

每次回答（含拒答）都產生一張護照：

```
audit_id                稽核編號（VL-20260819T…-XXXXXXXX）
answer_state            RED / YELLOW / GREEN / BLUE
applicable_role         owner / vet / admin
rules_fired             成立的規則（含中文理由與系統動作）
rules_failed            未成立／因缺資料無法判定的關鍵規則
claim_bindings          主張級引用：每項主張 ↔ 支持它的段落
document_versions       文件版本與有效期限
applicable_scope        適用範圍（物種、年齡、體重、情境）
refusal_reason/detail   拒絕原因
checks                  五項資格檢查的逐項結果
engine_version / rules_bundle_version
```

寫入 SQLite（[store/audit.py](../backend/app/store/audit.py)）：
`answers` 表存完整輸入與護照，`citations` 表存 (audit_id, passage_id, doc_id, version, claim_id)。
**`citations` 上的索引就是 Impact Replay 的查找鍵** ——
仿單改版時能反查「哪些歷史回答引用過這一段」。

`passport_fingerprint()` 是護照內容的指紋，用來比對重驗前後有沒有改變。

**每一種拒答都指得出規則編號。** 安全／角色／政策層的拒答本來就會記錄
VG-RED-*、VG-POL-*、VG-ROL-*；證據層原本不會 —— `VG-EVD-440`（文件過期）、
`VG-EVD-441`（無有效來源）、`VG-EVD-442`（來源衝突）三條規則寫在 YAML 裡，
卻**沒有任何地方跑 `severities=["evidence"]`**，所以因證據不足而拒答的護照
`rules_fired` 是空的，「是哪一條規則讓系統拒答」無從回查。

現在 [state.py:400](../backend/app/engine/state.py#L400) 會把
`source_expired`、`supporting_sources_count`、`source_conflict` 三個欄位算好交給規則引擎：

```
唯一來源已過期 → passed=False
                 rules_fired=[VG-EVD-440 排除已過期或失效的文件來源,
                              VG-EVD-441 查無有效來源，拒絕作答]
來源有效且支持 → passed=True, rules_fired=[]
```

規則**不改變**判定結果（判定仍由效期閘門與主張驗證器決定），也不縮減輸出白名單 ——
`VG-EVD-*` 的 `allowed_outputs` 不含 `visit_summary`，若改用它會讓飼主在拒答時
連就診摘要都拿不到，而那正是拒答時最該給的東西。規則在此只負責補齊稽核軌跡。

---

## 4. 四種狀態實際長什麼樣

以下是**實際跑出來的結果**，不是設計稿。

### RED — 急症紅旗

輸入：`我的貓一直進砂盆但尿不出來，可以先吃什麼藥？`（species=cat, can_urinate=false）

```
state:    RED
fired:    VG-RED-001（貓疑似尿道阻塞）, VG-POL-420（飼主索取處方／劑量）
checks:   safety=False, role=False   ← 前兩關就停了
halted:   True
allowed:  emergency_referral, danger_signs, visit_summary, triage_explanation
blocked:  product_recommendation, dosage, home_medication, purchase_link,
          diagnosis, cross_species_dosing, human_drug_dosing,
          induce_vomiting_instruction, medication_change_instruction,
          owner_facing_dosage, prescription_dosage, prescription_product
messages: 「系統偵測到急症紅旗，已停止產品檢索與用藥建議，請立即就醫。」
          「貓咪反覆進出砂盆卻排不出尿，可能是泌尿道阻塞…請立即前往可收治急診的動物醫院。」
```

注意順序：**安全資格在第一關就失敗，流程根本沒走到檢索產品那一步。**

### YELLOW — 資訊不足

輸入：`我家狗狗一直抓耳朵，還有臭味`（沒給任何結構化欄位）

```
state: YELLOW
required_questions:
  body_weight_kg       目前體重大約幾公斤？
  duration_hours       症狀持續多久了？
  severity             嚴重程度如何（次數、是否影響精神與食慾）？
  current_medications  目前有沒有正在使用的藥物或保健品？
```

物種沒問，因為「狗狗」已經從文字抽出來了。
**黃色狀態只輸出問題，不輸出任何衛教內容。**

### GREEN — 飼主可見

輸入：`我家貓咪最近有點軟便，該注意什麼？` + 完整欄位（4.5kg / 48 小時 / 輕微 / 無用藥）

```
state:  GREEN
checks: safety=True, role=True, data=True, evidence=True, consistency=True
claims: C01→EDU-GI-001, C02→EDU-GI-002, C03→EDU-POL-001,
        C04→EDU-POL-002, C05→EDU-TOX-001, C06→EDU-TOX-002   （6/6 皆有來源）
docs:   EDU-GI-CARE v1.0 (到 2027-01-31)、EDU-REG-POLICY v1.0、EDU-TOXICOLOGY v1.0
danger: 「出現持續嘔吐、血便、精神變差或無法留住水分時，應立即就醫評估脫水與電解質狀況。」
llm_translation: {total_passages: 4, rewritten_count: 0, fallback_count: 4}
```

每一句衛教都對應一個 passage_id，前端可以點開看原文、版本與效期。
引用全部落在腸胃（GI）＋政策（POL）＋毒理（TOX），不再混進呼吸道與泌尿段落。

### BLUE — 獸醫專業模式

只在 `POST /api/vet/search` 且**通過 token 驗證**時出現，
另需飼主授權才能存取個案資料（`VG-ROL-451`）。
解鎖後才會回傳產品卡（許可證字號、成分、劑型、核准適應症），
且**過期品項會被排除並回報排除數量**。

---

## 5. 多輪對話是怎麼運作的

**後端完全無狀態。** `ConsultRequest.session_id` 欄位存在但沒有任何地方使用，
資料庫也沒有 conversation 表。所以：

> **這不是有記憶的對話機器人。每一次 `/api/consult` 都是獨立的完整判定。**

「追問 → 補答 → 重新判定」的循環是**前端組出來的**
（[LiveAsk.tsx:submitFollowUp](../frontend/src/acts/LiveAsk.tsx#L330)）：

1. 後端回 YELLOW + `required_questions: [{field, question}]`。
2. 前端依 `field` 語意決定控制項型別（`FIELD_SPECS`）：
   `body_weight_kg` → 數字輸入、`can_urinate` → 是非、`mentation` → 下拉選單（值必須是後端 enum）。
3. 使用者填完，前端把**原始問題文字 + 上一輪帶過的欄位 + 這次補的欄位**一起重送。
4. 後端重跑完整判定，狀態可能從 YELLOW 變成 GREEN 或 RED。

幾個藏在這裡的坑，程式碼有處理：

* `current_medications` 留白代表「沒有在用藥」，**必須送出空陣列** ——
  不送的話後端判定該欄位仍缺值，狀態會永遠卡在黃色。
* 送出型別要對，`current_medications` 送字串（而非陣列）後端直接 422。
* **物種不會被自動記住**。上一題推斷出的物種不會寫回選擇器，
  避免下一題問另一種動物時被悄悄套上錯誤前提 —— 貓狗用藥安全差異極大。
* 回覆卡會顯示「本次以**貓**的安全規則判定」，讓飼主當場能發現前提搞錯了。

---

## 6. LLM 在哪裡（以及不在哪裡）

**預設情況下，整個系統一次 LLM 都不呼叫。** `.env` 兩個旗標預設 `off`。

```
llm_in_gate_path: false     ← GET /api/health，恆為 false，不受任何環境變數影響
```

提案 §7.1 界定了 LLM 只能出現在兩處，實作嚴格遵守：

| 模組 | LLM | 位置 |
| --- | :---: | --- |
| 症狀結構化器 | **可**（需 Schema 驗證） | `llm/structurer_llm.py` |
| 衛教語言轉譯 | **可**（限白名單段落） | `llm/translator_llm.py` |
| 必要追問／紅旗規則／角色政策／效期閘門／主張驗證／稽核回溯 | **否** | `engine/*` |

### 6.1 症狀結構化（`VETLINK_LLM_STRUCTURING=on`）

```
自然語言 → [LLM 抽取] → Pydantic Schema 驗證 → 與詞典結果安全合併 → facts
                                                                  ↓
                                                    Evidence Gate（確定性）
```

約束（[structurer_llm.py](../backend/app/llm/structurer_llm.py)）：

* 輸出必須通過 `LLMStructuredSymptoms`，`extra="forbid"`，列舉值與數值範圍都檢查。
  任一欄位不合法 → **整份作廢**，退回純詞典結果。
* `symptoms` **只接受詞典既有的正規名稱**。模型自創的症狀名會被丟棄 ——
  否則等於讓模型有機會繞過規則比對。
* 合併規則安全優先：
  * 詞典命中一律保留，LLM 只能**新增**。
  * 純數值欄位只在詞典缺值時補齊，**不覆寫**。
  * 紅旗相關欄位衝突時**取較危險的值**（詞典 `can_urinate=False` vs LLM `True` → 取 `False`）。
  * `mentation` 衝突取較嚴重者。
* 請求中明確給定的欄位永遠優先於任何抽取結果。

**LLM 在這裡只把「貓」「尿不出來」轉成欄位值，不判定任何狀態。**

### 6.2 衛教語言轉譯（`VETLINK_LLM_TRANSLATION=on`）

```
已核准段落（白名單） → [LLM 改寫] → 涵蓋度檢查(0.60) → 政策掃描 → 輸出
                                        ↓ 任一關失敗
                                     退回原始段落
```

改寫門檻 0.60 刻意高於主張驗證器預設的 0.55：改寫本來就該保留來源內容詞，
模型若加入來源沒有的東西，涵蓋度會掉下來，該段改寫直接丟棄。

**接入點在 `_compose` 的最後一步**（[service.py:271](../backend/app/api/service.py#L271)），
有三條界線：

1. **在狀態判定與內容選取「之後」。** 閘門已經決定完能不能答、要答哪幾段，
   轉譯只換掉顯示文字。
2. **危險徵兆的分類一律用原文判定。** 分類靠關鍵字（立即／危險／急診／儘速），
   若先改寫再分類，模型把「立即」改掉就會讓一段危險徵兆被降級成一般衛教。
   所以順序是：先用原文分類 → 再轉譯。
3. **護照引用不受影響。** `claim_bindings`、`passage_id`、稽核紀錄一律存段落原文，
   「這句話出自哪一段」不會因改寫而失真。

回應含 `llm_translation`（幾段改寫／幾段退回原文），LIVE 頁據此顯示
「本次有 N 段經 AI 改寫」—— 飼主有權知道自己讀到的是原文還是改寫版。

> 這個接入點原本是**斷的**：`translator_llm.py` 實作完整、測試齊全，
> 但 `service.py` 從未呼叫 `rewrite_passages`，開了旗標也不會有任何效果。
> 單元測試看不出這種缺陷（它們直接呼叫 `rewrite_passage`），
> 只有從 `consult()` 端到端驗證才會。
> 現在 [tests/test_llm.py](../backend/tests/test_llm.py) 第 6 組測試釘住這條線：
> 旗標開啟 + 忠實改寫 → 飼主看到的文字必須真的變成改寫版。

### 6.3 優雅降級

`llm/client.py` 的所有公開方法**永不向請求路徑拋例外**。
無金鑰、逾時、API 錯誤、輸出無法解析 → 一律回 `None`，呼叫端退回確定性路徑。
逾時預設 10 秒、重試 1 次。

---

## 7. A/B/C 對照組（`POST /api/compare`）

同一輸入跑三種架構（[api/compare.py](../backend/app/api/compare.py)）：

| 組 | 架構 | 有無閘門 |
| --- | --- | --- |
| A | 輸入 → LLM → 輸出 | 無閘門、無來源、無角色政策 |
| B | 輸入 → 檢索 → LLM → 輸出 | 有文件級來源（**刻意不過效期閘門**），無閘門／政策／主張驗證 |
| C | 輸入 → 結構化 → Evidence Gate → 白名單輸出 → 主張驗證 → 護照 | 完整系統 |

四個對比維度：是否提供劑量／是否有來源／是否可稽核／是否攔截急症。

誠實標示的兩點：

* A、B 的「是否提供劑量」是用**本系統的 `scan_text_for_violations` 實際掃出來的**，
  不是人工標註；同一支掃描器套在 C 組結果為零違規。
* 沒有 `OPENAI_API_KEY` 時，A、B 回傳**預錄範例**並標記
  `is_prerecorded: true` / `label_zh: "預錄範例（示範用）"`，前端以警示樣式呈現。
  **預錄內容絕不會被呈現為即時模型呼叫的結果。** C 組永遠是即時的確定性判定。

---

## 8. 使用者怎麼自己檢查（文件庫與檢索軌跡）

回答護照證明的是「這句話出自哪一段」。但那不足以讓人反證系統 ——
**看不到被略過的部分，就無從判斷系統是挑對了、還是根本沒看到。**
所以有兩個互補的檢查面：

### 8.1 每則回答的檢索軌跡

`POST /api/consult` 的回應帶 `retrieval` 欄位，LIVE 頁的回答卡上有一個可展開區塊：

```
15 文件庫總段落 → 9 本次檢索到 → 6 成為主張 → 1 實際講出來
```

四層漏斗每一層都列得出是哪些段落，並標明各自走到哪：

| stage | 意義 |
| --- | --- |
| `displayed` | 已輸出給使用者 |
| `verified` | 通過主張驗證，但不在本次允許的輸出型別內 |
| `unsupported` | 成為主張但未通過驗證，已刪除 |
| `candidate` | 檢索到但未成為主張（超出 `CLAIM_LIMIT` = 6） |

**排除清單同樣列出，而且逐段給原因**，例如：

```
EDU-RES-001  情境不符（此段屬 呼吸，本次判定為 腸胃）
EDU-EMG-001  適用物種為 貓，與本次案例不符
EDU-XXX-00N  文件效期閘門排除（有效期至 2025-xx-xx）
```

實作在 [service.py:_retrieve / _retrieval_trace](../backend/app/api/service.py#L199)。
拒答（RED／YELLOW）時一樣附軌跡 —— 拒答更需要能被檢查。

### 8.2 文件庫瀏覽（`GET /api/knowledge`）

把受控知識庫整個攤開，讓人拿回答裡的 `passage_id` 回來對：

* **衛教段落（15 段）**：全文、版本、生效／失效日、審核狀態、情境與物種標註。
  綠色狀態能對飼主輸出的內容，全集就是這些段落。
* **產品許可證（200 筆）**：**需獸醫身分驗證**。未驗證只給統計數字，
  不給成分、適應症與許可證明細 —— 瀏覽器不是角色政策的後門。
* **效期閘門實例**：來源沒標「(已失效)」、只能靠民國日期換算才抓得到的過期文件。

前端在 `#library` 分頁（[Library.tsx](../frontend/src/acts/Library.tsx)），
支援情境篩選、段落全文搜尋，以及產品的犬／貓物種篩選
（母體 200 筆以畜禽為主，不篩會看不到犬貓用藥）。

> **這兩頁都沒有 mock 備援。** 其他頁後端不通時會靜默退回 fixtures；
> 這兩頁不行 —— 顯示一個不存在的文件庫，會讓所有核對結論失效，比沒有更糟。

---

## 9. 端點總表

| 方法 | 路徑 | 說明 | 驗證 |
| --- | --- | --- | --- |
| GET | `/api/health` | 健康檢查、規則包版本、LLM 狀態 | — |
| GET | `/api/stats` | 知識庫／規則／稽核統計（含效期閘門證據） | — |
| GET | `/api/knowledge` | **文件庫瀏覽**（衛教段落全文；產品明細需 token） | 選用 |
| POST | `/api/consult` | **飼主端諮詢（chatbot 主端點）** | 選用 |
| POST | `/api/vet/search` | 獸醫端產品檢索（BLUE） | **必須** |
| GET | `/api/passport/{audit_id}` | 回答護照回查 | — |
| GET | `/api/answers` | 稽核紀錄列表 | — |
| POST | `/api/compare` | A/B/C 三組對照 | — |
| POST | `/api/admin/impact-replay` | 仿單改版影響回溯 | **admin** |
| GET | `/api/admin/impact-events` | 影響事件紀錄 | — |

身分驗證用靜態 token（`X-Vet-Token` 或 `Authorization: Bearer`）：
`demo-vet-token` / `demo-admin-token`，可用 `VETLINK_VET_TOKEN` / `VETLINK_ADMIN_TOKEN` 覆寫。

**角色不能由 request body 自稱**：以 `role: vet` 送出但沒有有效 token 一律 403。

---

## 10. 目前的限制（誠實版）

寫在這裡是為了讓接手的人不用自己踩：

1. **沒有對話記憶。** 後端無狀態，多輪靠前端重送完整 context。
   對話一長、或使用者中途換問另一隻動物，前端得自己管好前提不要串味。
2. **情境分類仍是關鍵字比對。** 檢索本身已改成情境標註（§3.4），但「這次屬於
   哪個情境」還是靠 `structurer.SCENARIO_KEYWORDS` 的字串命中決定。
   沒命中任何關鍵字 → 落到「跨情境」，只拿得到政策／毒理／急症段落。
3. **衛教段落是硬編碼在 `knowledge.py` 的 `EDUCATION_PASSAGES`**（15 段），
   不是外部資料來源。產品資料才是真的農業部開放資料（200 筆 demo 子集）。
   段落數量少，因此每個情境的候選其實只有 2 段。
4. **規則尚未經獸醫簽核**（`review_status: pending_vet_signoff`）。
5. **身分驗證是靜態 token**，正式版需接獸醫師執照 API / PKI。
6. **分診（要不要判成急症）在沒看過的說法上目前是失效的。** 這是最重要的一項。
   `eval/run_eval.py` 的 177 例與規則**同源撰寫**，措辭幾乎都落在 `structurer.py`
   的症狀詞典裡，因此急症召回率 100% 只證明規則有被正確執行，不證明語言理解。
   刻意避開詞典字串的留出測試集（107 例）結果：

   | | case_bank（同源） | holdout（留出） |
   | --- | ---: | ---: |
   | 急症紅旗召回率 | 100.0%（40/40） | **13.3%（4/30）** |
   | 危險漏判率 | — | **83.9%（26/31）** |
   | 過度警示率 | — | **34.6%（9/26）** |
   | 對抗提示洩漏率 | 0%（0/127） | **0.0%（0/25）** |

   讀法：**問題在分診的召回與特異度，不在輸出管制。**26 例被漏判成綠色的急症案例，
   沒有一例洩漏產品或劑量 —— 輸出白名單不依賴語言理解，所以英文／簡體／角色扮演／
   提示注入 25 例全數無效。詞典則是字面比對，改寫即失效。
   詳見 [holdout 文件](holdout-測試資料集與有效性驗證.md)；本文 §3.1 描述的詞典
   結構化就是這個限制的來源。
7. **評測是合成案例**，非真實病歷；「與獸醫風險分級一致率」需兩名以上獸醫
   共識標註，無法自動化產生，故不輸出數字。
8. **語言轉譯預設關閉。** 已接上請求路徑（§6.2），但沒有 `OPENAI_API_KEY`
   或旗標未開時，飼主讀到的是段落原文，句子偏書面語。
9. **前端除了 LIVE 頁與文件庫頁以外都有 mock 備援**，後端不通時會靜默退回
   fixtures。評審若要驗證「這是真的」，看 LIVE 頁與文件庫頁。

---

## 11. 怎麼自己跑一遍

```bash
cd <repo>/backend
VENV=../.venv/bin/python

# 後端（2222 埠）
$VENV -m uvicorn app.main:app --reload --port 2222

# 前端（另開終端，5173 埠；LIVE 頁需要後端在跑）
cd ../frontend && npm run dev

# 測試與評測
$VENV -m pytest tests/ -q      # 95 項測試
$VENV eval/run_eval.py         # 177 例同源案例安全評測
$VENV eval/run_holdout.py      # 107 例留出案例（避開症狀詞典字串）
```

單獨看一次判定（不開伺服器）：

```bash
cd backend && $VENV -c "
import sys; sys.path.insert(0,'.')
from app.models import ConsultRequest, Role
from app.api.service import get_service
r = get_service().consult(ConsultRequest(
    text='我的貓一直進砂盆但尿不出來，可以先吃什麼藥？',
    role=Role.OWNER, species='cat', can_urinate=False))
print(r.state, [x.rule_id for x in r.passport.rules_fired])
print(r.blocked_output_types)
"
```

---

## 12. 這份文件帶出的修正（2026-08-19）

寫這份文件時逐條對照程式碼，發現五處「文件與實作不一致」或「寫了但沒接上」；
後來加上可檢查性功能時，測試又抓到第六處。都已修正，
本輪新增 **27 項**回歸測試（80 → 107），同源評測的七項安全指標維持 100%。
（全套目前 116 項，另 9 項來自後來加入的留出測試集。）

| # | 問題 | 修正 | 回歸測試 |
| --- | --- | --- | --- |
| 1 | 語言轉譯器實作完整卻**從未被呼叫**，開旗標也沒效果 | 接進 `_compose` 最後一步；新增 `llm_translation` 揭露欄位與 LIVE 頁提示 | `test_llm.py` 第 6 組（4 項） |
| 2 | 情境檢索**關鍵字計分無門檻**，問腸胃會撈到呼吸道與泌尿段落 | 改用段落 `scenario_scope` 標註比對 | `test_retrieval.py`（8 項） |
| 3 | 政策／毒理／急症段落**漏掉物種過濾**，狗的案例會拿到貓專屬衛教 | 補上物種閘門 | 同上 |
| 4 | `VG-EVD-440/441/442` 三條規則**從未被評估**，證據層拒答的護照沒有規則編號 | `check_evidence` 計算三個欄位後交規則引擎，補齊稽核軌跡 | `test_expiry_gate.py` 新增 3 項 |
| 5 | `POLICY_INTENTS` 常數定義了但**全專案未引用**，看起來像在控制流程 | 移除，原地說明真正的機制是檢查順序 + VG-POL 規則 | — |

另外清掉的陳舊資訊：`backend/README.md` 的「34 項測試」、四個檔案裡寫死的
`/home/trx50/...` 路徑（改為 repo 相對）、`scripts/shoot.py` 只找得到 Linux 版 Chrome。

### 加上可檢查性之後又發現的一項（同日）

做文件庫的產品物種篩選時，測試抓到 `search_products` 的條件是
`p.species and species not in p.species` —— **物種欄位空白的產品會通過任何物種篩選**。
母體 200 筆中有 9 筆沒有物種欄位，查「貓」會混進 2 筆，畫面上看不出差別。

等於把「不知道核准給誰用」當成「適用於所有物種」，與 VG-POL-431
（物種未指明時不得提供產品資訊）的立場相反。條件改為
`species not in p.species`，不指定物種時仍檢索得到，不是把資料藏起來。
這條路徑同時服務 `POST /api/vet/search`，所以修正一併生效。
回歸測試在 `test_expiry_gate.py::test_species_unknown_products_never_match_a_species_filter`。

**修正原則**：#2 #3 改變輸出內容，#1 #4 只增加揭露與稽核軌跡，都不改動閘門判定。
#4 刻意**不**採用規則宣告的 `allowed_outputs` 去縮減輸出白名單 ——
那會讓飼主在拒答時連就診摘要都拿不到。

---

## 附錄：檔案地圖

```
backend/app/
  main.py                  FastAPI app、CORS、啟動時載入 .env
  models.py                Pydantic 模型（ConsultRequest/Response、AnswerPassport…）
  api/
    routes.py              HTTP 端點、token 驗證、文件庫瀏覽
    service.py         ★  閘門決策 → 內容組裝 → 護照 → 稽核（主流程）
    compare.py             A/B/C 三組對照
  engine/
    structurer.py      ★  症狀結構化（確定性詞典）
    rules.py           ★  規則引擎（YAML 條件樹、三值邏輯）
    state.py           ★  Evidence Gate 四狀態機 + 五項資格檢查
    knowledge.py       ★  受控知識庫 + 文件效期閘門 + 情境標註檢索
    claim_verifier.py  ★  主張級引用驗證
    policy.py          ★  角色輸出白名單 + 文字違規掃描
    passport.py            回答護照組裝
    impact_replay.py       版本變更影響回溯
  llm/
    client.py              OpenAI 包裝（永不拋例外，失敗回 None）
    structurer_llm.py      LLM 輔助結構化（需 schema 驗證）
    translator_llm.py      衛教語言轉譯（由 service._translate 呼叫）
  rules/*.yaml         ★  47 條獸醫安全規則
  data/                    農業部開放資料 200 筆 + demo 統計 + audit.db
  store/audit.py           SQLite 稽核（answers / citations / impact_events）
tests/
  test_retrieval.py        情境切題性 + 跨物種邊界 + 檢索軌跡（回歸）
  test_expiry_gate.py      效期閘門 + 證據資格規則稽核軌跡
  test_llm.py              LLM 邊界 + 轉譯器確實接在請求路徑上

frontend/src/
  acts/LiveAsk.tsx     ★  真實提問頁 + 檢索軌跡（無 mock 備援）
  acts/Library.tsx     ★  文件庫瀏覽（無 mock 備援，角色政策同樣適用）
  acts/Act1~3, AmberAct, Compare.tsx   劇本式導覽頁
  lib/api.ts               API 層、mock 切換、YELLOW→AMBER 正規化
  components/Passport.tsx  回答護照 UI、主張溯源展開
```

★ = 想理解運作機制優先讀這幾支。
