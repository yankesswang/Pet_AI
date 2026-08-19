import type { ReactNode } from 'react'
import type { TimelineEntry, ContentBlock } from '../lib/types'
import { IconTarget, IconAlert, IconArrowRight, IconStop, IconBan } from './Icons'

/** 每一幕的「證明重點」強調條 */
export function Thesis({ children }: { children: ReactNode }) {
  return (
    <div className="thesis">
      <span className="thesis__icon"><IconTarget size={22} /></span>
      <span>{children}</span>
    </div>
  )
}

export function Note({ children }: { children: ReactNode }) {
  return (
    <div className="note">
      <span className="note__icon"><IconAlert size={18} /></span>
      <span>{children}</span>
    </div>
  )
}

export function SectionTitle({ num, children, right }: { num: string; children: ReactNode; right?: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-4)', flexWrap: 'wrap' }}>
      <h2 className="section-title">
        <span className="section-num">{num}</span>
        {children}
      </h2>
      {right && <div style={{ marginLeft: 'auto' }}>{right}</div>}
    </div>
  )
}

/**
 * 停止檢索面板 —— 第一幕的關鍵證據。
 * 必須看起來像「系統主動封鎖」，因此使用警示斜紋、刪除線與 HALTED 戳記，
 * 而不是單純的空白或錯誤訊息。
 */
export function HaltedPanel({
  reason, fields,
}: { reason: string; fields: Array<{ label_zh: string; tag: string }> }) {
  return (
    <section className="halted" aria-label="產品檢索已停止">
      <header className="halted__head">
        <IconStop size={22} />
        <span>產品檢索已停止</span>
        <span className="halted__stamp">RETRIEVAL HALTED</span>
      </header>
      <div className="halted__body">
        <p className="halted__reason">{reason}</p>
        <div className="label">本次原本會產生、但已被規則攔截的欄位</div>
        <ul className="blocked-list">
          {fields.map((f) => (
            <li className="blocked-row" key={f.label_zh}>
              <span className="blocked-row__x" aria-hidden><IconBan size={18} /></span>
              <span className="blocked-row__text">{f.label_zh}</span>
              <span className="blocked-row__tag">{f.tag}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

/** 症狀時間軸 */
export function Timeline({ entries }: { entries: TimelineEntry[] }) {
  return (
    <div className="timeline">
      {entries.map((e, i) => (
        <div className={`tl tl--${e.severity}`} key={i}>
          <div className="tl__time">{e.time_label_zh}</div>
          <div className="tl__rail">
            <span className="tl__dot" />
            {i < entries.length - 1 && <span className="tl__line" />}
          </div>
          <div className="tl__body">{e.detail_zh}</div>
        </div>
      ))}
    </div>
  )
}

const BLOCK_CLASS: Record<ContentBlock['kind'], string> = {
  danger_signs: 'block block--danger',
  action: 'block block--action',
  education: 'block block--edu',
  observe: 'block block--edu',
  forbidden: 'block block--forbid',
  note: 'block',
}

/** 內容區塊 — 可帶 claim 溯源 */
export function Block({
  block, renderItem,
}: {
  block: ContentBlock
  renderItem?: (claimId: string, text: string) => ReactNode
}) {
  return (
    <section className={BLOCK_CLASS[block.kind]}>
      <header className="block__head">
        {block.kind === 'danger_signs' && <IconAlert size={17} />}
        {block.kind === 'action' && <IconArrowRight size={17} />}
        {block.kind === 'forbidden' && <IconBan size={17} />}
        {block.title_zh}
      </header>
      <div className="block__body">
        {block.items.map((it, i) =>
          it.claim_id && renderItem ? (
            <div key={i}>{renderItem(it.claim_id, it.text_zh)}</div>
          ) : (
            <div className="bullet" key={i}>
              <span className="bullet__dot" />
              <span>{it.text_zh}</span>
            </div>
          ),
        )}
      </div>
    </section>
  )
}

/** 步驟指示器 */
export function Steps({ steps, current }: { steps: string[]; current: number }) {
  return (
    <div className="steps" role="list">
      {steps.map((s, i) => (
        <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
          <span className="step" data-done={i < current} data-current={i === current} role="listitem">
            <span className="step__n">{i + 1}</span>
            {s}
          </span>
          {i < steps.length - 1 && <span className="step__arrow" aria-hidden>→</span>}
        </span>
      ))}
    </div>
  )
}

/** 靜態 QR 佔位圖 — 不引入外部相依 */
export function QrPlaceholder({ code }: { code: string }) {
  const cells = 11
  // 由授權碼衍生的確定性圖樣，確保畫面穩定可截圖
  const seedNum = Array.from(code).reduce((a, c) => a + c.charCodeAt(0), 0)
  const on = (r: number, c: number) => {
    if ((r < 3 && c < 3) || (r < 3 && c > cells - 4) || (r > cells - 4 && c < 3)) return true
    return ((r * 7 + c * 13 + seedNum) % 3) === 0
  }
  return (
    <div className="qr">
      <svg className="qr__code" width="132" height="132" viewBox={`0 0 ${cells} ${cells}`} role="img" aria-label={`授權 QR Code ${code}`}>
        <rect width={cells} height={cells} fill="#fff" />
        {Array.from({ length: cells }).map((_, r) =>
          Array.from({ length: cells }).map((_, c) =>
            on(r, c) ? <rect key={`${r}-${c}`} x={c} y={r} width="1" height="1" fill="#0B1220" /> : null,
          ),
        )}
      </svg>
      <span className="qr__label">{code}</span>
    </div>
  )
}
