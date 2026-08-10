import type { CSSProperties } from 'react'

export type IcpTier = 'hot' | 'warm' | 'cold' | 'disqualified'

export const TIER_ICON: Record<IcpTier, string> = {
  hot: '🔥',
  warm: '🟡',
  cold: '❄️',
  disqualified: '⛔',
}

export const TIER_STYLE: Record<IcpTier, CSSProperties> = {
  hot: { background: 'rgba(249,115,22,0.12)', color: '#fb923c', border: '1px solid rgba(249,115,22,0.25)' },
  warm: { background: 'rgba(251,191,36,0.10)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.22)' },
  cold: { background: 'rgba(96,165,250,0.10)', color: '#60a5fa', border: '1px solid rgba(96,165,250,0.22)' },
  disqualified: { background: 'rgba(148,163,184,0.12)', color: '#94a3b8', border: '1px solid rgba(148,163,184,0.28)' },
}

export function tierOf(value?: string): IcpTier {
  return (['hot', 'warm', 'cold', 'disqualified'] as const).includes(value as IcpTier)
    ? (value as IcpTier)
    : 'cold'
}
