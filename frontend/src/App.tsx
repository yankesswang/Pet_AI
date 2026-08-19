import { useEffect, useState } from 'react'
import type { Role } from './lib/types'
import { GATE_ORDER, GATE_META, ROLE_META } from './lib/gateStates'
import { USE_MOCKS, getLastSource, health, type DataSource } from './lib/api'
import { StateLegend, StateBadge } from './components/StateVisuals'
import { Thesis, SectionTitle, Note } from './components/Common'
import { DATASET_FACTS } from './mocks'
import { Act1 } from './acts/Act1'
import { Act2 } from './acts/Act2'
import { Act3 } from './acts/Act3'
import { AmberAct } from './acts/AmberAct'
import { IconShield, IconArrowRight, IconTarget, IconStop, IconRefresh, IconCheck } from './components/Icons'

/** 導覽分頁 */
type ViewId = 'overview' | 'act1' | 'amber' | 'act2' | 'act3'

interface ViewDef {
  id: ViewId
  kicker: string
  label: string
  /** 此頁的主要角色視角 — 用於角色切換器高亮 */
  role: Role
}

const VIEWS: ViewDef[] = [
  { id: 'overview', kicker: 'OVERVIEW', label: '四種狀態總覽', role: 'owner' },
  { id: 'act1', kicker: 'ACT 1 · RED', label: '第一幕｜系統拒絕用藥要求', role: 'owner' },
  { id: 'amber', kicker: 'STATE · AMBER', label: '黃色｜資訊不足時的追問', role: 'owner' },
  { id: 'act2', kicker: 'ACT 2 · BLUE', label: '第二幕｜同案例、不同角色', role: 'vet' },
  { id: 'act3', kicker: 'ACT 3 · REPLAY', label: '第三幕｜仿單更新追回舊回答', role: 'admin' },
]

export function App() {
  const [view, setView] = useState<ViewId>('overview')
  const [source, setSource] = useState<DataSource>(USE_MOCKS ? 'mock' : 'live')

  /** live 模式下確認後端是否真的活著，供頂欄標示 */
  useEffect(() => {
    if (USE_MOCKS) return
    let alive = true
    health().then((h) => {
      if (alive) setSource(h.ok ? 'live' : 'live-fallback')
    })
    return () => { alive = false }
  }, [])

  /** 每次切頁後同步實際資料來源（可能因 fallback 改變） */
  useEffect(() => {
    setSource(getLastSource())
  }, [view])

  const current = VIEWS.find((v) => v.id === view)!

  const go = (id: ViewId) => {
    setView(id)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="app">
      <TopBar source={source} />

      <nav className="actnav" aria-label="Demo 導覽">
        <div className="actnav__inner">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              className="actnav__btn"
              aria-current={view === v.id}
              onClick={() => go(v.id)}
            >
              <span className="actnav__kicker">{v.kicker}</span>
              <span className="actnav__label">{v.label}</span>
            </button>
          ))}
        </div>
      </nav>

      <main>
        <div className="shell stack gap-6">
          <RoleSwitcher current={current.role} onPick={(r) => {
            const target = VIEWS.find((v) => v.role === r && v.id !== 'overview')
            if (target) go(target.id)
          }} />

          {view === 'overview' && <Overview onStart={() => go('act1')} />}
          {view === 'act1' && <Act1 onNext={() => go('act2')} />}
          {view === 'amber' && <AmberAct />}
          {view === 'act2' && <Act2 onNext={() => go('act3')} />}
          {view === 'act3' && <Act3 />}

          <Footer />
        </div>
      </main>
    </div>
  )
}

/* ---------------- 頂欄 ---------------- */

const SOURCE_LABEL: Record<DataSource, string> = {
  mock: 'MOCK DATA',
  live: 'LIVE API',
  'live-fallback': 'LIVE → MOCK 備援',
}

function TopBar({ source }: { source: DataSource }) {
  return (
    <header className="topbar">
      <div className="topbar__inner">
        <div className="brand">
          <span className="brand__mark"><IconShield size={24} /></span>
          <div>
            <div className="brand__name">VetLink AI｜Evidence Gate 寵藥安心閘門</div>
            <div className="brand__tag">2026 中化智匯盃 · 動物用藥知識精準 APP · 中化動藥</div>
          </div>
        </div>
        <div className="topbar__meta">
          <span>資料時點 {DATASET_FACTS.as_of}</span>
          <span className="chip-mode" data-live={source === 'live'}>{SOURCE_LABEL[source]}</span>
        </div>
      </div>
    </header>
  )
}

/* ---------------- 角色切換器 ---------------- */

function RoleSwitcher({ current, onPick }: { current: Role; onPick: (r: Role) => void }) {
  return (
    <div
      style={{
        display: 'flex', gap: 'var(--sp-4)', alignItems: 'center',
        flexWrap: 'wrap', padding: 'var(--sp-3) 0',
      }}
    >
      <span className="label">目前角色視角</span>
      <div className="roleswitch" role="group" aria-label="角色切換">
        {(Object.keys(ROLE_META) as Role[]).map((r) => (
          <button
            key={r}
            type="button"
            className="roleswitch__btn"
            aria-pressed={current === r}
            onClick={() => onPick(r)}
          >
            {ROLE_META[r].icon({ size: 17 })} {ROLE_META[r].label}
          </button>
        ))}
      </div>
      <span className="muted" style={{ flex: 1, minWidth: 260 }}>
        {ROLE_META[current].scope}
      </span>
    </div>
  )
}

/* ---------------- 四種狀態總覽 ---------------- */

function Overview({ onStart }: { onStart: () => void }) {
  return (
    <div className="stack gap-8">
      <header className="stack gap-4">
        <SectionTitle num="總覽">四種狀態，而不是一個模糊答案</SectionTitle>
        <p className="lede">
          市面上的寵物問診 AI 幾乎都在比誰「答得更多」。但動物用藥的真正風險，
          從來不是回答得不夠詳細，而是<b>在不該回答的時候給了一個聽起來很合理的答案</b>。
          VetLink AI 把系統定位從推薦引擎改為<b>推薦資格引擎</b>：在呼叫生成模型之前，
          先用確定性規則判定這一次「有沒有資格回答」，並輸出四種明確狀態，
          而不是用單一信心分數掩蓋不確定性。
        </p>
      </header>

      <Thesis>
        這套系統的價值，在於它知道什麼時候必須拒絕回答 —— 而且每一次拒絕都留下可稽核的證明。
      </Thesis>

      {/* 四種狀態 */}
      <section className="stack gap-4">
        <SectionTitle num="§4">Evidence Gate 的四種狀態</SectionTitle>
        <StateLegend />
        <Note>
          四種狀態同時以<b>色彩、專屬字符（■ ▲ ● ◆）、專屬圖示與中文標籤</b>四重編碼，
          確保色盲使用者與黑白列印皆可辨識，不依賴單一色彩通道傳達安全訊息。
        </Note>
      </section>

      {/* 五項資格檢查 */}
      <section className="stack gap-4">
        <SectionTitle num="§4">一次回答必須通過的五項檢查</SectionTitle>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 132 }}>資格檢查</th>
                <th>判定內容</th>
                <th style={{ width: 190 }}>未通過時的狀態</th>
              </tr>
            </thead>
            <tbody>
              {[
                ['安全資格', '未觸發需立即處理的紅旗規則。', 'RED', '不得推薦'],
                ['資料資格', '必要資訊已補齊，且沒有關鍵矛盾。', 'AMBER', '資訊不足'],
                ['角色資格', '輸出內容符合飼主、獸醫或管理者權限。', 'RED', '角色不符 → 遮蔽'],
                ['證據資格', '每項醫療或產品主張都有有效且未過期的來源。', 'RED', '證據不足 → 拒答'],
                ['一致性資格', '來源沒有未解決衝突；否則拒答並轉介。', 'RED', '來源衝突 → 拒答'],
              ].map(([k, v, state, label]) => (
                <tr key={k}>
                  <td style={{ fontWeight: 700 }}>{k}</td>
                  <td>{v}</td>
                  <td>
                    <span className="risk" data-state={state} style={{ color: 'var(--st)', background: 'var(--st-bg)' }}>
                      {label}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* 三幕導覽 */}
      <section className="stack gap-4">
        <SectionTitle num="§10">三幕 Demo：證明拒答、分權與可追回</SectionTitle>
        <div className="grid-3">
          {[
            {
              state: 'RED' as const, icon: <IconStop size={22} />,
              title: '第一幕｜拒答',
              body: '飼主問「可以先吃什麼藥？」系統在檢索任何產品資料之前就停止流程，不顯示藥名或劑量，改為急診轉介。',
              proof: 'AI 的價值不是每次都回答，而是知道何時必須停止。',
            },
            {
              state: 'BLUE' as const, icon: <IconCheck size={22} />,
              title: '第二幕｜分權',
              body: '獸醫掃描授權 QR Code 後解鎖藍色專業模式，可檢索核准仿單並點擊任一主張回溯原始段落。',
              proof: '把高品質資訊交到有資格決策的人手上，而不是把決策藏在 AI 裡。',
            },
            {
              state: 'GREEN' as const, icon: <IconRefresh size={22} />,
              title: '第三幕｜可追回',
              body: '許可證屆期後，系統找出曾引用舊段落的歷史回答，依風險分級失效、重審或更新標示。',
              proof: '可追溯不是靜態引用，而是持續運作的知識治理能力。',
            },
          ].map((c) => (
            <div className="legend__item" data-state={c.state} key={c.title}>
              <div className="legend__head">
                <span className="legend__glyph">{c.icon}</span>
                <span className="legend__name" style={{ fontSize: 'var(--t-md)' }}>{c.title}</span>
              </div>
              <div className="legend__row">{c.body}</div>
              <div
                className="legend__row"
                style={{ marginTop: 'auto', paddingTop: 'var(--sp-3)', borderTop: '1px solid var(--c-border)' }}
              >
                <b>證明重點：</b>{c.proof}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 回答護照 摘要 */}
      <section className="stack gap-4">
        <SectionTitle num="§8">回答護照：從文件級引用提升為主張級證據</SectionTitle>
        <p className="lede">
          每一次回答（包含每一次<b>拒絕</b>回答）都附帶一份回答護照。
          若任何醫療或產品主張找不到直接支持的來源段落，系統必須刪除該主張、標示資料不足，或拒絕回答並交回獸醫。
        </p>
        <div className="grid-4">
          {[
            ['回答狀態', '紅、黃、綠或藍色狀態'],
            ['適用角色', '飼主、獸醫或管理者'],
            ['觸發規則', '哪些規則成立、哪些未成立'],
            ['支持來源', '每項主張對應的原始段落'],
            ['文件版本', '版本號、生效日、最後審核日及失效日'],
            ['適用範圍', '動物種類、年齡或其他限制'],
            ['拒絕原因', '資訊不足、急症、角色不符、證據不足或來源衝突'],
            ['稽核編號', '可回查完整輸入、檢索結果、回答與攔截紀錄'],
          ].map(([k, v]) => (
            <div className="stat" key={k}>
              <div style={{ fontSize: 'var(--t-md)', fontWeight: 900 }}>{k}</div>
              <div className="stat__k">{v}</div>
            </div>
          ))}
        </div>
      </section>

      {/* 資料基礎 */}
      <section className="stack gap-4">
        <SectionTitle num="資料">本 Demo 使用的真實資料基礎</SectionTitle>
        <div className="grid-4">
          <div className="stat">
            <div className="stat__n">{DATASET_FACTS.total_licences.toLocaleString()}</div>
            <div className="stat__k">農業部動物用藥許可證總數</div>
          </div>
          <div className="stat stat--MEDIUM">
            <div className="stat__n">{DATASET_FACTS.expired.toLocaleString()}</div>
            <div className="stat__k">已過期許可證</div>
          </div>
          <div className="stat stat--HIGH">
            <div className="stat__n">{DATASET_FACTS.silent_expired.toLocaleString()}</div>
            <div className="stat__k">已過期但來源未標示（已失效）</div>
          </div>
          <div className="stat stat--LOW">
            <div className="stat__n">{DATASET_FACTS.ccpc_valid}</div>
            <div className="stat__k">中化現行有效許可證（共 {DATASET_FACTS.ccpc_total} 張）</div>
          </div>
        </div>
        <Note>
          來源：農業部動物用藥品許可證開放資料，資料時點 {DATASET_FACTS.as_of}。
          第三幕的核心案例即取自其中一張<b>來源未標示失效、僅能由民國日期換算判定</b>的許可證。
        </Note>
      </section>

      <div style={{ display: 'flex', gap: 'var(--sp-4)', flexWrap: 'wrap', alignItems: 'center' }}>
        <button className="btn btn--primary btn--lg" onClick={onStart}>
          從第一幕開始 <IconArrowRight size={18} />
        </button>
        <span className="muted">建議依序觀看：第一幕 → 黃色狀態 → 第二幕 → 第三幕</span>
      </div>
    </div>
  )
}

/* ---------------- 頁尾 ---------------- */

function Footer() {
  return (
    <footer className="stack gap-4" style={{ marginTop: 'var(--sp-12)', paddingTop: 'var(--sp-6)', borderTop: '2px solid var(--c-border)' }}>
      <div style={{ display: 'flex', gap: 'var(--sp-3)', flexWrap: 'wrap', alignItems: 'center' }}>
        <span className="thesis__icon"><IconTarget size={20} /></span>
        <span style={{ fontWeight: 700 }}>四種狀態速查</span>
        <div style={{ display: 'flex', gap: 'var(--sp-2)', flexWrap: 'wrap', marginLeft: 'auto' }}>
          {GATE_ORDER.map((s) => <StateBadge key={s} state={s} size="sm" />)}
        </div>
      </div>
      <p className="muted">
        本畫面為 2026 中化智匯盃競賽 Demo。所有臨床規則均標示來源與審核狀態；
        產品資料取自農業部動物用藥品許可證開放資料。
        系統不提供劑量計算、處方生成或處方藥購買通路 —— 處方藥依法須由執業獸醫師診斷後開具處方，始得販賣及使用。
        {GATE_ORDER.map((s) => `${GATE_META[s].glyph} ${GATE_META[s].label}`).join('　')}
      </p>
    </footer>
  )
}
