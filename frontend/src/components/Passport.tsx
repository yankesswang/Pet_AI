import { useState } from 'react'
import type { AnswerPassport, Claim, SourcePassage } from '../lib/types'
import { GATE_META, ROLE_META, REFUSAL_LABEL } from '../lib/gateStates'
import { StateBadge } from './StateVisuals'
import { IconCheck, IconX, IconDoc, IconLink, IconBan, IconTarget, IconScale, IconList, IconShield, IconClock } from './Icons'

/** 版本徽章 — 生效日 / 失效日 / 是否過期 */
export function VersionBadge({ version, from, to, expired }: { version: string; from: string; to: string; expired: boolean }) {
  return (
    <span className={`verbadge ${expired ? 'verbadge--expired' : 'verbadge--valid'}`}>
      <IconClock size={13} />
      {version} · {from} → {to} {expired ? '· 已失效' : '· 有效'}
    </span>
  )
}

/** 來源段落展開面板 */
export function PassagePanel({ p }: { p: SourcePassage }) {
  return (
    <div className="passage" role="region" aria-label={`來源段落 ${p.passage_id}`}>
      <div className="passage__head">
        <IconDoc size={16} />
        <span className="passage__doc">{p.doc_title_zh}</span>
        <span className="passage__meta">
          <span>{p.passage_id}</span>
          <span>版本 {p.version}</span>
          {p.page_ref && <span>{p.page_ref}</span>}
        </span>
      </div>
      <p className="passage__text">{p.text}</p>
      <div className="passage__foot">
        {p.licence_no && <span>許可證：{p.licence_no}</span>}
        {p.issue_date_iso && <span>生效 {p.issue_date_iso}</span>}
        {p.expiry_date_iso && <span>失效 {p.expiry_date_iso}</span>}
        <span>{p.is_expired ? '狀態：已過期' : '狀態：有效'}</span>
        {p.source_url && (
          <a href={p.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--c-brand-2)', display: 'inline-flex', gap: 4, alignItems: 'center' }}>
            <IconLink size={12} /> 開放資料來源
          </a>
        )}
      </div>
    </div>
  )
}

/**
 * 可點擊主張 — 主張級溯源的核心互動。
 * 點一下即展開支持該主張的原始段落，這是與一般 RAG 的關鍵差異。
 */
export function ClaimButton({
  claim, passages, defaultOpen = false,
}: { claim: Claim; passages: Record<string, SourcePassage>; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const sources = claim.supported_by.map((id) => passages[id]).filter(Boolean)
  return (
    <div>
      <button
        type="button"
        className={`claim${claim.verified ? '' : ' claim--unverified'}`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="claim__text">{claim.text_zh}</span>
        <span className="claim__cite">
          {claim.verified ? <IconCheck size={12} /> : <IconBan size={12} />}
          {claim.supported_by.length > 0 ? claim.supported_by.join(' / ') : '無來源'}
          <span aria-hidden>{open ? '▾' : '▸'}</span>
        </span>
      </button>
      {open && (
        <div className="stack gap-2">
          {sources.length > 0
            ? sources.map((p) => <PassagePanel key={p.passage_id} p={p} />)
            : <div className="note"><IconBan size={16} className="note__icon" />此主張未比對到支持段落，依主張驗證器規則應刪除或拒答。</div>}
        </div>
      )}
    </div>
  )
}

/** 一組主張（帶說明） */
export function ClaimList({ claims, passages, title }: { claims: Claim[]; passages: Record<string, SourcePassage>; title?: string }) {
  return (
    <div className="stack gap-2">
      {title && <div className="label">{title}</div>}
      {claims.map((c) => <ClaimButton key={c.claim_id} claim={c} passages={passages} />)}
    </div>
  )
}

const Row = ({ icon, k, children }: { icon: React.ReactNode; k: string; children: React.ReactNode }) => (
  <div className="passport__row">
    <div className="passport__k">{icon}{k}</div>
    <div className="passport__v">{children}</div>
  </div>
)

/**
 * 回答護照 — 提案 §八 完整八欄位。
 * 同時顯示成立與未成立規則，是「規則驅動而非模型判斷」的視覺證據。
 */
export function AnswerPassportCard({ passport, defaultOpenClaim }: { passport: AnswerPassport; defaultOpenClaim?: string }) {
  const fired = passport.rules.filter((r) => r.fired)
  const passed = passport.rules.filter((r) => !r.fired)
  const m = GATE_META[passport.gate_state]

  return (
    <section className="passport" aria-label="回答護照">
      <header className="passport__head">
        <IconShield size={22} />
        <div>
          <div className="passport__title">回答護照 ANSWER PASSPORT</div>
          <div className="passport__sub">每項主張綁定來源段落、版本與適用範圍</div>
        </div>
        <span className="passport__id">{passport.audit_id}</span>
      </header>

      <div className="passport__grid">
        <Row icon={<IconTarget size={15} />} k="回答狀態">
          <div className="stack gap-2">
            <StateBadge state={passport.gate_state} size="sm" />
            <span className="muted">{m.behavior}</span>
          </div>
        </Row>

        <Row icon={<IconList size={15} />} k="適用角色">
          <div style={{ display: 'flex', gap: 'var(--sp-3)', flexWrap: 'wrap' }}>
            {passport.applicable_roles.map((r) => (
              <span key={r} className="verbadge">
                {ROLE_META[r].icon({ size: 13 })} {ROLE_META[r].label}
              </span>
            ))}
          </div>
          <div className="muted" style={{ marginTop: 'var(--sp-2)' }}>
            {passport.applicable_roles.map((r) => ROLE_META[r].scope).join('；')}
          </div>
        </Row>

        <Row icon={<IconScale size={15} />} k="觸發規則">
          <div className="stack gap-3">
            <div>
              <div className="label label--block">成立（{fired.length}）：造成本次系統動作</div>
              <div className="stack gap-2">
                {fired.map((r) => (
                  <div className="rule rule--fired" key={r.rule_id}>
                    <span className="rule__icon"><IconX size={17} /></span>
                    <div className="rule__main">
                      <div><span className="rule__id">{r.rule_id}</span><span className="rule__ver">{r.version}</span></div>
                      <div className="rule__name">{r.name_zh}</div>
                      <div className="rule__action">→ {r.action_zh}</div>
                      {r.basis_zh && <div className="rule__basis">判定依據：{r.basis_zh}</div>}
                      {r.clinical_source && <div className="rule__basis">臨床依據：{r.clinical_source}</div>}
                      {r.reviewed_by && <div className="rule__basis">審核：{r.reviewed_by}（{r.reviewed_at}）</div>}
                    </div>
                    <span className="rule__verdict">FIRED</span>
                  </div>
                ))}
                {fired.length === 0 && <div className="muted">本次無規則成立。</div>}
              </div>
            </div>
            <div>
              <div className="label label--block">未成立（{passed.length}）：已檢查並通過</div>
              <div className="stack gap-2">
                {passed.map((r) => (
                  <div className="rule rule--passed" key={r.rule_id}>
                    <span className="rule__icon"><IconCheck size={17} /></span>
                    <div className="rule__main">
                      <div><span className="rule__id">{r.rule_id}</span><span className="rule__ver">{r.version}</span></div>
                      <div className="rule__name">{r.name_zh}</div>
                      <div className="rule__action">若成立則：{r.action_zh}</div>
                      {r.basis_zh && <div className="rule__basis">{r.basis_zh}</div>}
                    </div>
                    <span className="rule__verdict">PASSED</span>
                  </div>
                ))}
                {passed.length === 0 && <div className="muted">本次無未成立規則紀錄。</div>}
              </div>
            </div>
          </div>
        </Row>

        <Row icon={<IconDoc size={15} />} k="支持來源">
          {passport.claims.length > 0 ? (
            <div className="stack gap-2">
              <div className="muted" style={{ marginBottom: 'var(--sp-1)' }}>
                點擊任一主張即可展開支持它的原始段落（主張級溯源）
              </div>
              {passport.claims.map((c) => (
                <ClaimButton key={c.claim_id} claim={c} passages={passport.passages} defaultOpen={c.claim_id === defaultOpenClaim} />
              ))}
            </div>
          ) : (
            <div className="note">
              <IconBan size={16} className="note__icon" />
              本次未輸出任何醫療或產品主張，因此無主張級來源。所引用之規則與轉介資訊列於上方觸發規則欄。
            </div>
          )}
        </Row>

        <Row icon={<IconClock size={15} />} k="文件版本">
          <div className="stack gap-2">
            {passport.documents.map((d) => (
              <div key={d.doc_id} style={{ display: 'flex', gap: 'var(--sp-3)', flexWrap: 'wrap', alignItems: 'center' }}>
                <span style={{ fontWeight: 600 }}>{d.title_zh}</span>
                <VersionBadge version={d.version} from={d.issue_date_iso} to={d.expiry_date_iso} expired={d.is_expired} />
                <span className="muted">來源：{d.source_org}{d.last_reviewed_iso ? `｜最後審核 ${d.last_reviewed_iso}` : ''}</span>
              </div>
            ))}
          </div>
        </Row>

        <Row icon={<IconTarget size={15} />} k="適用範圍">
          <ul className="stack gap-2">
            {passport.scope_zh.map((s, i) => (
              <li key={i} className="bullet"><span className="bullet__dot" /><span>{s}</span></li>
            ))}
          </ul>
        </Row>

        <Row icon={<IconBan size={15} />} k="拒絕原因">
          {passport.refusal_reason ? (
            <div className="stack gap-2">
              <span className="risk risk--HIGH">{REFUSAL_LABEL[passport.refusal_reason] ?? passport.refusal_reason}</span>
              <span>{passport.refusal_detail_zh}</span>
            </div>
          ) : (
            <span className="muted">無。本次通過全部五項資格檢查（安全、資料、角色、證據、一致性）。</span>
          )}
        </Row>

        <Row icon={<IconShield size={15} />} k="稽核編號">
          <div className="stack gap-2">
            <span className="mono" style={{ fontSize: 'var(--t-md)', fontWeight: 700 }}>{passport.audit_id}</span>
            <span className="muted">
              建立時間 {passport.created_at_iso}｜可回查完整輸入、檢索結果、回答與攔截紀錄
            </span>
          </div>
        </Row>
      </div>
    </section>
  )
}
