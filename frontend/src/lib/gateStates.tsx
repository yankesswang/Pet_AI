import type { ReactNode } from 'react'
import type { GateState, Role } from './types'
import { IconStop, IconQuestion, IconCheck, IconShield, IconUser, IconStethoscope, IconBuilding } from '../components/Icons'

/**
 * 四種狀態的統一身分定義。
 * 每個狀態同時具備：色彩 + 專屬字符 + 專屬圖示 + 中文標籤，
 * 四重編碼確保色盲使用者與黑白列印皆可辨識。
 */
export interface GateMeta {
  state: GateState
  /** 色盲/黑白可辨識的字符標記 */
  glyph: string
  code: string
  label: string
  icon: (p: { size?: number }) => ReactNode
  trigger: string
  behavior: string
  visible: string
}

export const GATE_META: Record<GateState, GateMeta> = {
  RED: {
    state: 'RED',
    glyph: '■',
    code: 'STATE / RED',
    label: '不得推薦',
    icon: (p) => <IconStop {...p} />,
    trigger: '急症紅旗、中毒、嚴重呼吸異常、無法排尿',
    behavior: '停止產品檢索，立即轉介',
    visible: '危險徵兆、就醫行動、經確認的急診資訊',
  },
  AMBER: {
    state: 'AMBER',
    glyph: '▲',
    code: 'STATE / AMBER',
    label: '資訊不足',
    icon: (p) => <IconQuestion {...p} />,
    trigger: '缺少物種、體重、時間、嚴重度或既有用藥',
    behavior: '僅提出固定必要追問',
    visible: '追問與暫時性安全提醒',
  },
  GREEN: {
    state: 'GREEN',
    glyph: '●',
    code: 'STATE / GREEN',
    label: '飼主可見',
    icon: (p) => <IconCheck {...p} />,
    trigger: '急症已排除、資料足夠、來源有效',
    behavior: '提供經審核衛教及就診準備',
    visible: '觀察事項、衛教、摘要、討論方向',
  },
  BLUE: {
    state: 'BLUE',
    glyph: '◆',
    code: 'STATE / BLUE',
    label: '獸醫專業模式',
    icon: (p) => <IconShield {...p} />,
    trigger: '通過獸醫身分驗證且授權成立',
    behavior: '解鎖專業產品檢索',
    visible: '核准適應症、成分、限制、仿單與比較',
  },
}

export const GATE_ORDER: GateState[] = ['RED', 'AMBER', 'GREEN', 'BLUE']

export const ROLE_META: Record<Role, { label: string; icon: (p: { size?: number }) => ReactNode; scope: string }> = {
  owner: { label: '飼主', icon: (p) => <IconUser {...p} />, scope: '分流、衛教、就診摘要；不含處方與劑量' },
  vet: { label: '獸醫', icon: (p) => <IconStethoscope {...p} />, scope: '核准仿單、成分、適應症、限制與版本' },
  admin: { label: '中化管理者', icon: (p) => <IconBuilding {...p} />, scope: '文件版本、影響回溯、重審任務與稽核' },
}

export const REFUSAL_LABEL: Record<string, string> = {
  EMERGENCY_REDFLAG: '急症紅旗',
  INSUFFICIENT_INFO: '資訊不足',
  ROLE_NOT_PERMITTED: '角色不符',
  NO_EVIDENCE: '證據不足',
  SOURCE_CONFLICT: '來源衝突',
  DOCUMENT_EXPIRED: '文件已失效',
}
