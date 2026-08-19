/** 內嵌 SVG 圖示 — 無外部相依，統一 1.9px stroke */
interface P { size?: number; className?: string }
const base = (size: number) => ({
  width: size, height: size, viewBox: '0 0 24 24',
  fill: 'none', stroke: 'currentColor',
  strokeWidth: 1.9, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
  'aria-hidden': true, focusable: false as unknown as boolean,
})

export const IconStop = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="9" /><path d="M8 12h8" strokeWidth="2.6" />
  </svg>
)
export const IconQuestion = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.2 9.3a2.8 2.8 0 0 1 5.4 1c0 1.9-2.6 2.3-2.6 4" />
    <path d="M12 17.4h.01" strokeWidth="2.6" />
  </svg>
)
export const IconCheck = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="9" /><path d="M8 12.4l2.6 2.6L16 9.4" strokeWidth="2.4" />
  </svg>
)
export const IconShield = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 3l7.2 2.9v5.4c0 4.3-3 8.1-7.2 9.4-4.2-1.3-7.2-5.1-7.2-9.4V5.9L12 3z" />
    <path d="M9.3 12.2l1.9 1.9 3.6-3.9" strokeWidth="2.2" />
  </svg>
)
export const IconX = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M6 6l12 12M18 6L6 18" strokeWidth="2.4" />
  </svg>
)
export const IconBan = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="9" strokeWidth="2.2" />
    <path d="M5.6 5.6l12.8 12.8" strokeWidth="2.2" />
  </svg>
)
export const IconDoc = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" />
    <path d="M14 3v5h5M9 13h6M9 17h4" />
  </svg>
)
export const IconLink = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M10 13a4 4 0 0 0 5.7.4l2.6-2.6a4 4 0 0 0-5.7-5.7l-1.5 1.5" />
    <path d="M14 11a4 4 0 0 0-5.7-.4l-2.6 2.6a4 4 0 0 0 5.7 5.7l1.5-1.5" />
  </svg>
)
export const IconUser = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="8" r="3.6" /><path d="M4.8 20c.7-3.6 3.7-5.6 7.2-5.6s6.5 2 7.2 5.6" />
  </svg>
)
export const IconStethoscope = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M5 3v5a4 4 0 0 0 8 0V3" /><path d="M4 3h2M12 3h2" />
    <path d="M9 12v2.5a5 5 0 0 0 10 0V13" /><circle cx="19" cy="11" r="2" />
  </svg>
)
export const IconBuilding = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M4 21V6a1 1 0 0 1 1-1h7a1 1 0 0 1 1 1v15" />
    <path d="M13 10h6a1 1 0 0 1 1 1v10M3 21h18" />
    <path d="M7 9h2M7 13h2M7 17h2M16 14h1M16 18h1" />
  </svg>
)
export const IconClock = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="9" /><path d="M12 7v5.3l3.4 2" />
  </svg>
)
export const IconAlert = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 4.2L2.8 20h18.4L12 4.2z" /><path d="M12 10v4.2M12 17.4h.01" strokeWidth="2.3" />
  </svg>
)
export const IconArrowRight = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M4 12h15M13 6l6 6-6 6" />
  </svg>
)
export const IconSearch = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" strokeWidth="2.2" />
  </svg>
)
export const IconUpload = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" />
    <path d="M12 15V4M7.5 8.5L12 4l4.5 4.5" />
  </svg>
)
export const IconQr = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <rect x="3.5" y="3.5" width="7" height="7" rx="1" />
    <rect x="13.5" y="3.5" width="7" height="7" rx="1" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="1" />
    <path d="M14 14h2.5M20 14v2.5M14 18.5h2M18 20.5h2.5M18.5 17h.01" />
  </svg>
)
export const IconLock = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <rect x="4.5" y="10" width="15" height="10.5" rx="2" />
    <path d="M8 10V7.2a4 4 0 0 1 8 0V10" />
  </svg>
)
export const IconUnlock = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <rect x="4.5" y="10" width="15" height="10.5" rx="2" />
    <path d="M8 10V7.2a4 4 0 0 1 7.6-1.7" />
  </svg>
)
export const IconRefresh = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M20 11a8 8 0 0 0-13.7-4.6L3 9" /><path d="M3 4.5V9h4.5" />
    <path d="M4 13a8 8 0 0 0 13.7 4.6L21 15" /><path d="M21 19.5V15h-4.5" />
  </svg>
)
export const IconList = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" strokeWidth="2.2" />
  </svg>
)
export const IconTarget = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="1" strokeWidth="2.4" />
  </svg>
)
export const IconPhone = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M6.5 3.5h3l1.5 4-2 1.4a12 12 0 0 0 6.1 6.1l1.4-2 4 1.5v3a2 2 0 0 1-2.2 2A17 17 0 0 1 4.5 5.7a2 2 0 0 1 2-2.2z" />
  </svg>
)
export const IconScale = ({ size = 20, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 4v16M7 20h10M6 8h12l-2.5-2.5" />
    <path d="M3 14l3-6 3 6a3 3 0 0 1-6 0zM15 14l3-6 3 6a3 3 0 0 1-6 0z" />
  </svg>
)
