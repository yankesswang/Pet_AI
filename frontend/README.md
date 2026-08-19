# VetLink AI｜Evidence Gate 寵藥安心閘門 — Demo 前端

2026 中化智匯盃參賽作品（題目：動物用藥知識精準 APP／事業體：中化動藥）的互動 Demo。
畫面用途是產出初賽 PDF 所需的截圖，核心論點只有一句：

> **這套系統的價值，在於它知道什麼時候必須拒絕回答 —— 而且每一次拒絕都留下可稽核的證明。**

---

## 環境需求

| 項目 | 版本 |
| --- | --- |
| Node.js | **18 以上**（實際驗證於 v20.20.2） |
| npm | 隨 Node 一併安裝 |

> **注意：系統預設的 `node` 可能是 v12，無法建置本專案。**
> 本機的 Node 20 透過 nvm 安裝，**每一個新的 shell 都必須先載入 nvm**：
>
> ```bash
> export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"
> ```
>
> 執行 `node -v` 應顯示 `v20.x`（或任何 ≥ 18 的版本）才可繼續。

---

## 安裝與啟動

```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"   # 每個新 shell 都要先跑這行
cd /home/trx50/Project/Pet_AI/frontend

npm install        # 安裝相依套件
npm run dev        # 開發伺服器 → http://localhost:5173
```

其他指令：

```bash
npm run build      # 產出 production 版本至 dist/（含 tsc 型別檢查）
npm run typecheck  # 只做型別檢查，不輸出檔案
npm run preview    # 預覽 build 後的結果
```

---

## Mock / Live 資料切換

**Demo 預設完全離線執行，不需要後端也能跑完整三幕。** 這是刻意的設計 —— 簡報現場不能開天窗。

切換方式為單一開關，位於 `.env`（可從 `.env.example` 複製）：

```bash
VITE_USE_MOCKS=true    # 預設。完全使用 src/mocks 的 fixtures，不發任何網路請求
VITE_USE_MOCKS=false   # 改呼叫 FastAPI 後端，經 Vite proxy /api → http://localhost:8000
```

在 `live` 模式下，若後端無回應或回傳錯誤，`src/lib/api.ts` 會**自動退回 mock 資料**，
並在畫面右上角將標記從 `LIVE API` 改為 `LIVE → MOCK 備援`，因此 Demo 在任何情況下都不會中斷。

### 後端 API 對應

| 端點 | 方法 | 備註 |
| --- | --- | --- |
| `/api/consult` | POST | 閘門判定 + 回答護照 |
| `/api/vet/search` | POST | 藍色模式產品檢索（需授權 token） |
| `/api/passport/{audit_id}` | GET | 取回單筆回答護照 |
| `/api/admin/impact-replay` | POST | 影響回溯 |
| `/api/health` | GET | 健康檢查 |

> **狀態命名差異：** 後端以 `YELLOW` 表示「資訊不足」，前端型別統一使用 `AMBER`。
> `src/lib/api.ts` 的 `normalizeGates()` 會在資料入口遞迴改寫所有 `gate_state` 欄位
> （`YELLOW` → `AMBER`），因此 UI 層永遠只需處理 `RED / AMBER / GREEN / BLUE` 四個值。

---

## 畫面導覽

導覽列共五頁，建議依序觀看：

| 頁面 | 狀態 | 證明重點 |
| --- | --- | --- |
| **四種狀態總覽** | — | 四種狀態、五項資格檢查、回答護照八欄位、真實資料基礎 |
| **第一幕｜系統拒絕用藥要求** | 🔴 RED | AI 的價值不是每次都回答，而是知道何時必須停止 |
| **黃色｜資訊不足時的追問** | 🟡 AMBER | 系統不用推測值填補缺漏，追問題目由規則庫固定提供 |
| **第二幕｜同案例、不同角色** | 🔵 BLUE | 把高品質資訊交到有資格決策的人手上，而不是把決策藏在 AI 裡 |
| **第三幕｜仿單更新追回舊回答** | — | 可追溯不是靜態引用，而是持續運作的知識治理能力 |

各幕的互動需要按下畫面上的主要按鈕才會展開結果
（第一幕「送出並執行判定」、第二幕需先「掃描 QR Code」再「執行檢索」、第三幕「執行影響回溯」）。

### 第三幕的核心證據

第三幕的重點是一張**來源自己都沒標示失效**的許可證：

- 許可證：動物藥入字第07363號「一錠除犬用滴劑（巨型犬）」
- 來源「有效期間」欄位原文：`至115年06月30日止` —— **沒有任何 `(已失效)` 標記**
- 民國 115 年換算為西元 2026-06-30，對照基準日 2026-08-19 → **已屆期 50 天**

農業部開放資料共 13,738 張許可證，其中 9,120 張已過期；
**有 1,503 張與本例相同 —— 來源未標示，只能靠民國日期換算比對才判定得出。**
任何直接信任來源狀態欄位的系統都會把它們當成有效產品。這證明閘門攔到了上游來源自己都沒攔到的失效。

---

## 專案結構

```
src/
├── main.tsx              React 進入點（載入三個 CSS）
├── App.tsx               外殼：頂欄、導覽、角色切換器、四種狀態總覽
├── acts/
│   ├── Act1.tsx          第一幕 — 紅色拒答
│   ├── Act2.tsx          第二幕 — 角色分權、藍色專業模式
│   ├── Act3.tsx          第三幕 — 影響回溯、沉默失效
│   └── AmberAct.tsx      黃色狀態 — 固定必要追問
├── components/
│   ├── StateVisuals.tsx  狀態標記、判決橫幅、四狀態圖例
│   ├── Passport.tsx      回答護照、可點擊主張、來源段落
│   ├── Common.tsx        論點強調條、停止面板、時間軸、QR 等
│   └── Icons.tsx         內嵌 SVG 圖示（無外部相依）
├── lib/
│   ├── types.ts          全部型別定義
│   ├── gateStates.tsx    四種狀態與三種角色的統一身分定義
│   └── api.ts            mock / live 切換、YELLOW→AMBER 正規化
├── mocks/                各幕 fixtures（真實農業部開放資料）
└── styles/               tokens / base / components
```

---

## 設計原則

- **四重編碼**：四種狀態同時以色彩、專屬字符（■ ▲ ● ◆）、專屬圖示與中文標籤呈現，
  確保色盲使用者與黑白列印皆可辨識，不依賴單一色彩通道傳達安全訊息。
- **截圖友善**：內文字級下限 17px，中性 slate 基調，飽和色只保留給四種狀態，
  在 PDF 縮放後仍具足夠對比與可讀性。
- **臨床而非消費風格**：深海軍藍主色、實線邊框、等寬字體標示版本與編號，
  視覺語彙貼近法規文件而非消費型 App。

---

## 資料來源

- 產品資料：[農業部動物用藥品許可證開放資料](https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx)（資料時點 2026-08-19，共 13,738 筆）
- 法規：[獸醫師（佐）處方藥品販賣及使用管理辦法](https://law.moa.gov.tw/LawContent.aspx?id=FL035300)
- 臨床規則：獸醫安全規則庫（依 WSAVA／Merck Veterinary Manual 重新結構化，標示審核者與審核日期）

> 本系統不提供劑量計算、處方生成或處方藥購買通路 ——
> 處方藥依法須由執業獸醫師診斷後開具處方，始得販賣及使用。
