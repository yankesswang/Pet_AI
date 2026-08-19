import type { GateState } from '../lib/types'
import { GATE_META, GATE_ORDER } from '../lib/gateStates'

/** 小型狀態標記 */
export function StateBadge({ state, size = 'md' }: { state: GateState; size?: 'sm' | 'md' }) {
  const m = GATE_META[state]
  return (
    <span className={`statebadge${size === 'sm' ? ' statebadge--sm' : ''}`} data-state={state}>
      <span className="statebadge__glyph" aria-hidden>{m.glyph}</span>
      <span className="statebadge__text">
        <span className="statebadge__code">{m.code}</span>
        <span className="statebadge__label">{m.label}</span>
      </span>
    </span>
  )
}

/** 大型判決橫幅 — 每一幕結果畫面的最上方 */
export function Verdict({
  state, headline, auditId, children,
}: {
  state: GateState; headline: string; auditId: string; children?: React.ReactNode
}) {
  const m = GATE_META[state]
  return (
    <section className="verdict" data-state={state} aria-label={`閘門判定：${m.label}`}>
      <header className="verdict__top">
        <span className="verdict__glyph" aria-hidden>
          {m.icon({ size: 30 })}
        </span>
        <div className="verdict__titles">
          <div className="verdict__code">
            {m.code} · {m.glyph}
          </div>
          <h2 className="verdict__label">{m.label}</h2>
        </div>
        <span className="verdict__audit">稽核編號 {auditId}</span>
      </header>
      <div className="verdict__body stack gap-4">
        <p className="verdict__headline">{headline}</p>
        {children}
      </div>
    </section>
  )
}

/** 四狀態圖例 — 產品簽名，任何畫面都可放 */
export function StateLegend({ active }: { active?: GateState }) {
  return (
    <div className="legend" role="list" aria-label="Evidence Gate 四種狀態">
      {GATE_ORDER.map((s) => {
        const m = GATE_META[s]
        return (
          <div className="legend__item" key={s} data-state={s} data-active={active === s} role="listitem">
            <div className="legend__head">
              <span className="legend__glyph" aria-hidden>{m.glyph}</span>
              <span className="legend__name">{m.label}</span>
            </div>
            <div className="legend__row"><b>觸發：</b>{m.trigger}</div>
            <div className="legend__row"><b>行為：</b>{m.behavior}</div>
            <div className="legend__row"><b>可見：</b>{m.visible}</div>
          </div>
        )
      })}
    </div>
  )
}
