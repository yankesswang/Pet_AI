import { useState } from 'react'
import type { ImpactReplayResponse, ImpactRisk, PassageDiff } from '../lib/types'
import { impactReplay } from '../lib/api'
import { ACT3_IMPACT_REPLAY, SILENT_EXPIRY_CASE, DATASET_EXPIRY_STATS } from '../mocks'
import { Thesis, SectionTitle, Steps, Note } from '../components/Common'
import { ROLE_META } from '../lib/gateStates'
import {
  IconArrowRight, IconRefresh, IconClock, IconAlert, IconCheck, IconBan,
  IconShield, IconDoc, IconList,
} from '../components/Icons'

const RISK_LABEL: Record<ImpactRisk, string> = {
  HIGH: '高｜立即失效',
  MEDIUM: '中｜人工重審',
  LOW: '低｜更新標示',
}

export function Act3() {
  const [data, setData] = useState<ImpactReplayResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const run = async () => {
    setLoading(true)
    try {
      setData(await impactReplay({ doc_id: ACT3_IMPACT_REPLAY.doc_id, new_version: ACT3_IMPACT_REPLAY.new_version }))
    } finally {
      setLoading(false)
    }
  }

  const d = data

  return (
    <div className="stack gap-8">
      <header className="stack gap-4">
        <SectionTitle num="第三幕">仿單更新後追回舊回答</SectionTitle>
        <p className="lede">
          可追溯不是在回答旁邊印一個版本號就結束。當許可證屆期、仿單改版或法規變更時，
          <b>過去已經送出的回答會在無人察覺的情況下變成錯的</b>。
          VetLink AI 把回答的生命週期納入治理：差異比對 → 影響查找 → 風險分級 → 重新驗證 → 通知與稽核。
        </p>
        <Steps
          steps={['每日效期重新判定', '新舊版本差異比對', '找出引用舊段落的回答', '風險分級與處置', '通知與稽核']}
          current={d ? 4 : 0}
        />
      </header>

      {/* ============ 核心證據：來源未標示的沉默失效 ============ */}
      <section className="stack gap-4">
        <SectionTitle num="3-1">本幕的起點：一張「來源沒說它過期」的許可證</SectionTitle>
        <p className="lede">
          農業部開放資料的「有效期間」欄位，多數過期許可證會附加 <span className="mono">(已失效)</span> 標記。
          但有 <b>{DATASET_EXPIRY_STATS.expired_silent.toLocaleString()} 張沒有</b>，
          它們只寫著一個民國日期。任何直接信任來源狀態欄位的系統，都會把這些許可證當成現行有效並提供給使用者。
        </p>

        {/* 來源 vs 系統 對照：本幕最重要的一張圖 */}
        <div className="split">
          <div className="split__col" data-state="RED">
            <div className="split__head">
              <IconDoc size={20} />
              <span className="split__role">來源資料怎麼說</span>
              <span className="split__note">農業部開放資料原文</span>
            </div>
            <div className="split__body">
              <div className="stack gap-2">
                <div className="label">{SILENT_EXPIRY_CASE.source_field_label}</div>
                <div
                  className="mono"
                  style={{
                    fontSize: 'var(--t-xl)', fontWeight: 700, padding: 'var(--sp-4)',
                    background: 'var(--c-surface-sunk)', border: '2px solid var(--c-border-strong)',
                    borderRadius: 'var(--r-md)', textAlign: 'center', letterSpacing: '0.02em',
                  }}
                >
                  {SILENT_EXPIRY_CASE.source_field_value}
                </div>
              </div>
              <div className="blocked-row">
                <span className="blocked-row__x" aria-hidden><IconBan size={18} /></span>
                {/* 這裡描述的是「欄位裡缺少標記」：不是被刪除的內容，故不加刪除線 */}
                <span className="blocked-row__text" style={{ textDecoration: 'none', color: 'var(--c-ink)', fontWeight: 700 }}>
                  {SILENT_EXPIRY_CASE.source_marker}
                </span>
                <span className="blocked-row__tag">NO MARKER</span>
              </div>
              <div
                className="halted__reason"
                style={{ borderLeftColor: 'var(--s-red)', fontWeight: 700, fontSize: 'var(--t-md)' }}
              >
                來源判定：{SILENT_EXPIRY_CASE.source_verdict}
              </div>
              <div className="note">
                若系統直接讀取狀態欄位，這張許可證會被當作有效產品，繼續出現在檢索結果與歷史回答裡。
              </div>
            </div>
          </div>

          <div className="split__col" data-state="BLUE">
            <div className="split__head">
              <IconShield size={20} />
              <span className="split__role">系統怎麼判定</span>
              <span className="split__note">VG-EXP-002 效期閘門</span>
            </div>
            <div className="split__body">
              <div className="stack gap-2">
                <div className="label">效期正規化步驟</div>
                {SILENT_EXPIRY_CASE.system_steps.map((s, i) => (
                  <div
                    key={i}
                    style={{
                      display: 'flex', gap: 'var(--sp-3)', alignItems: 'flex-start',
                      padding: 'var(--sp-2) var(--sp-3)',
                      background: i === SILENT_EXPIRY_CASE.system_steps.length - 1 ? 'var(--s-blue-bg)' : 'var(--c-surface-alt)',
                      border: '1px solid var(--c-border)', borderRadius: 'var(--r-sm)',
                      fontWeight: i === SILENT_EXPIRY_CASE.system_steps.length - 1 ? 700 : 400,
                      fontSize: 'var(--t-sm)', lineHeight: 1.6,
                    }}
                  >
                    <span
                      className="mono"
                      style={{
                        flexShrink: 0, width: 22, height: 22, borderRadius: 'var(--r-sm)',
                        background: 'var(--s-blue)', color: '#fff', display: 'grid',
                        placeItems: 'center', fontSize: 11, fontWeight: 700, marginTop: 2,
                      }}
                    >
                      {i + 1}
                    </span>
                    <span className="mono">{s}</span>
                  </div>
                ))}
              </div>
              <div
                className="halted__reason"
                style={{ borderLeftColor: 'var(--s-blue)', fontWeight: 700, fontSize: 'var(--t-md)' }}
              >
                系統判定：{SILENT_EXPIRY_CASE.system_verdict}
              </div>
              <div className="note" style={{ borderColor: 'var(--s-blue-soft)', background: 'var(--s-blue-bg)' }}>
                <span className="note__icon" style={{ color: 'var(--s-blue)' }}><IconCheck size={18} /></span>
                <span>閘門攔到了上游來源自己都沒標示的失效。</span>
              </div>
            </div>
          </div>
        </div>

        {/* 案件識別 */}
        <div className="tbl-wrap">
          <table className="tbl">
            <tbody>
              <tr><th style={{ width: 150 }}>許可證字號</th><td className="mono strong">{SILENT_EXPIRY_CASE.licence_no}</td></tr>
              <tr><th>品名</th><td className="strong">{SILENT_EXPIRY_CASE.name_zh}</td></tr>
              <tr><th>持證公司</th><td>{SILENT_EXPIRY_CASE.company}</td></tr>
              <tr><th>判定基準日</th><td className="mono">{DATASET_EXPIRY_STATS.as_of}</td></tr>
            </tbody>
          </table>
        </div>

        {/* 規模統計 */}
        <div className="grid-4">
          <div className="stat">
            <div className="stat__n">{DATASET_EXPIRY_STATS.total.toLocaleString()}</div>
            <div className="stat__k">全庫許可證總數</div>
          </div>
          <div className="stat stat--MEDIUM">
            <div className="stat__n">{DATASET_EXPIRY_STATS.expired_total.toLocaleString()}</div>
            <div className="stat__k">已過期</div>
          </div>
          <div className="stat stat--LOW">
            <div className="stat__n">{DATASET_EXPIRY_STATS.expired_marked.toLocaleString()}</div>
            <div className="stat__k">來源已標示 (已失效)</div>
          </div>
          <div className="stat stat--HIGH">
            <div className="stat__n">{DATASET_EXPIRY_STATS.expired_silent.toLocaleString()}</div>
            <div className="stat__k">來源未標示｜僅能由日期判定</div>
          </div>
        </div>

        <Thesis>
          {SILENT_EXPIRY_CASE.scale_note}
        </Thesis>
      </section>

      {/* ============ 執行影響回溯 ============ */}
      <section className="stack gap-4">
        <SectionTitle num="3-2">當這張許可證被判定失效，過去的回答怎麼辦</SectionTitle>
        <div className="card">
          <div className="card__head">
            <span className="card__title" style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
              <IconRefresh size={19} /> 中化管理者後台｜Impact Replay
            </span>
            <span className="mono muted">ADM-003</span>
          </div>
          <div className="card__body stack gap-4">
            <div className="tbl-wrap">
              <table className="tbl">
                <tbody>
                  <tr><th style={{ width: 150 }}>目標文件</th><td>{ACT3_IMPACT_REPLAY.doc_title_zh}</td></tr>
                  <tr><th>版本變更</th>
                    <td className="mono">{ACT3_IMPACT_REPLAY.old_version} → {ACT3_IMPACT_REPLAY.new_version}</td>
                  </tr>
                  <tr><th>生效日</th><td className="mono">{ACT3_IMPACT_REPLAY.effective_date_iso}</td></tr>
                </tbody>
              </table>
            </div>
            {!d && (
              <button className="btn btn--primary btn--lg" onClick={run} disabled={loading} style={{ alignSelf: 'flex-start' }}>
                {loading ? '回溯中…' : '執行影響回溯 Impact Replay'}
                {!loading && <IconRefresh size={18} />}
              </button>
            )}
            {loading && (
              <div className="note">
                <span className="note__icon"><IconClock size={18} /></span>
                正在依序執行：差異比對 → 影響查找 → 風險分級 → 重新驗證 → 通知與稽核
              </div>
            )}
          </div>
        </div>
      </section>

      {d && (
        <>
          {/* 統計 */}
          <section className="stack gap-4">
            <SectionTitle num="3-3">回溯結果</SectionTitle>
            <div className="grid-4">
              <div className="stat">
                <div className="stat__n">{d.stats.scanned_answers.toLocaleString()}</div>
                <div className="stat__k">掃描的歷史回答</div>
              </div>
              <div className="stat stat--HIGH">
                <div className="stat__n">{d.stats.high}</div>
                <div className="stat__k">高風險｜立即失效</div>
              </div>
              <div className="stat stat--MEDIUM">
                <div className="stat__n">{d.stats.medium}</div>
                <div className="stat__k">中風險｜人工重審</div>
              </div>
              <div className="stat stat--LOW">
                <div className="stat__n">{d.stats.low}</div>
                <div className="stat__k">低風險｜更新標示</div>
              </div>
            </div>
            <Note>
              {d.stats.scanned_answers.toLocaleString()} 筆歷史回答之所以掃得動，是因為每一筆都留有回答護照，
              記錄了它引用了哪一個段落、哪一個版本。沒有主張級溯源，就沒有影響回溯。
            </Note>
          </section>

          {/* 差異比對 */}
          <section className="stack gap-4">
            <SectionTitle num="3-4">步驟一｜差異比對</SectionTitle>
            {d.diffs.map((diff) => <DiffPanel key={diff.passage_id} diff={diff} />)}
          </section>

          {/* 影響查找 + 風險分級 */}
          <section className="stack gap-4">
            <SectionTitle num="3-5">步驟二、三｜影響查找與風險分級</SectionTitle>
            <div className="stack gap-4">
              {d.affected.map((a) => (
                <div className="card" key={a.audit_id}>
                  <div className="card__head">
                    <span className="card__title t-base">{a.question_zh}</span>
                    <div style={{ display: 'flex', gap: 'var(--sp-2)', alignItems: 'center', flexWrap: 'wrap' }}>
                      <span className="verbadge">
                        {ROLE_META[a.role].icon({ size: 13 })} {ROLE_META[a.role].label}
                      </span>
                      <span className={`risk risk--${a.risk}`}>{RISK_LABEL[a.risk]}</span>
                    </div>
                  </div>
                  <div className="card__body stack gap-3">
                    <div className="tbl-wrap">
                      <table className="tbl">
                        <tbody>
                          <tr><th style={{ width: 132 }}>稽核編號</th><td className="mono">{a.audit_id}</td></tr>
                          <tr><th>提問時間</th><td className="mono">{new Date(a.asked_at_iso).toLocaleString('zh-TW')}</td></tr>
                          <tr><th>引用段落</th><td className="mono">{a.cited_passage_id}</td></tr>
                        </tbody>
                      </table>
                    </div>
                    <div className="stack gap-2">
                      <div className="label">當時輸出的主張</div>
                      <div
                        style={{
                          padding: 'var(--sp-3) var(--sp-4)', background: 'var(--c-surface-alt)',
                          borderLeft: '4px solid var(--c-border-strong)', borderRadius: '0 var(--r-sm) var(--r-sm) 0',
                          fontSize: 'var(--t-sm)', lineHeight: 1.7,
                        }}
                      >
                        {a.cited_claim_zh}
                      </div>
                    </div>
                    <div className="stack gap-2">
                      <div className="label">風險判定理由</div>
                      <div className="rule__basis" style={{ fontSize: 'var(--t-sm)', marginTop: 0 }}>{a.risk_reason_zh}</div>
                    </div>
                    <div
                      style={{
                        display: 'flex', gap: 'var(--sp-3)', alignItems: 'center', flexWrap: 'wrap',
                        padding: 'var(--sp-3) var(--sp-4)', borderRadius: 'var(--r-md)',
                        background: a.risk === 'HIGH' ? 'var(--s-red-bg)' : a.risk === 'MEDIUM' ? 'var(--s-amber-bg)' : 'var(--s-green-bg)',
                        border: `1px solid ${a.risk === 'HIGH' ? 'var(--s-red-soft)' : a.risk === 'MEDIUM' ? 'var(--s-amber-soft)' : 'var(--s-green-soft)'}`,
                      }}
                    >
                      <span style={{ color: a.risk === 'HIGH' ? 'var(--s-red)' : a.risk === 'MEDIUM' ? 'var(--s-amber)' : 'var(--s-green)' }}>
                        <IconArrowRight size={18} />
                      </span>
                      <span style={{ fontWeight: 700, fontSize: 'var(--t-sm)' }}>系統處置：{a.action_zh}</span>
                      <span className="verbadge" style={{ marginLeft: 'auto' }}>新狀態：{a.new_status_zh}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* 重審任務 */}
          <section className="stack gap-4">
            <SectionTitle num="3-6">步驟四｜重新驗證：人工重審任務</SectionTitle>
            <div className="tbl-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>任務編號</th><th>對應回答</th><th>指派對象</th><th>到期日</th><th>優先級</th><th>狀態</th>
                  </tr>
                </thead>
                <tbody>
                  {d.tasks.map((t) => (
                    <tr key={t.task_id}>
                      <td className="mono strong">{t.task_id}</td>
                      <td className="mono">{t.audit_id}</td>
                      <td>{t.assignee_zh}</td>
                      <td className="mono">{t.due_date_iso}</td>
                      <td><span className={`risk risk--${t.priority}`}>{t.priority}</span></td>
                      <td><span className="verbadge">{t.status_zh}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Note>
              高風險回答由系統直接失效，不等人工；中風險才進入重審佇列。
              系統不會用「已通知管理者」取代「已停止提供錯誤資訊」。
            </Note>
          </section>

          {/* 稽核軌跡 */}
          <section className="stack gap-4">
            <SectionTitle
              num="3-7"
              right={<span className="mono muted">批次編號 IR-2026-0819-A</span>}
            >
              步驟五｜稽核軌跡（不可竄改、可回查）
            </SectionTitle>
            <div className="card">
              <div className="card__body">
                <div className="timeline">
                  {d.audit_log.map((l, i) => (
                    <div className="tl tl--info" key={i}>
                      <div className="tl__time mono">
                        {new Date(l.ts_iso).toLocaleTimeString('zh-TW', { hour12: false })}
                      </div>
                      <div className="tl__rail">
                        <span className="tl__dot" />
                        {i < d.audit_log.length - 1 && <span className="tl__line" />}
                      </div>
                      <div className="tl__body">
                        <div className="strong">{l.event_zh}</div>
                        <div className="muted">{l.actor_zh}</div>
                        <div style={{ fontSize: 'var(--t-sm)', color: 'var(--c-ink-2)', marginTop: 2 }}>{l.detail_zh}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <Thesis>
            可追溯不是靜態引用，而是持續運作的知識治理能力，
            系統不只知道當時用了什麼資料，還知道資料改變後，哪些既有回答不再值得信任，以及如何找到並處理它們。
          </Thesis>
        </>
      )}
    </div>
  )
}

/** 差異比對面板 — 新舊版本逐段標示 */
function DiffPanel({ diff }: { diff: PassageDiff }) {
  return (
    <div className="card">
      <div className="card__head">
        <span className="card__title" style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
          <IconList size={19} /> {diff.section_zh}
        </span>
        <span className="mono muted">{diff.passage_id}</span>
      </div>
      <div className="card__body stack gap-3">
        <div style={{ display: 'flex', gap: 'var(--sp-3)', flexWrap: 'wrap', alignItems: 'center' }}>
          <span className="verbadge verbadge--expired">{diff.old_version}</span>
          <IconArrowRight size={16} />
          <span className="verbadge verbadge--valid">{diff.new_version}</span>
        </div>
        <div className="diff">
          {diff.segments.map((s, i) =>
            s.kind === 'added' ? <ins key={i}>{s.text}</ins>
            : s.kind === 'removed' ? <del key={i}>{s.text}</del>
            : <span key={i}>{s.text}</span>,
          )}
        </div>
        <div className="note">
          <span className="note__icon"><IconAlert size={18} /></span>
          <span>{diff.change_summary_zh}</span>
        </div>
      </div>
    </div>
  )
}
