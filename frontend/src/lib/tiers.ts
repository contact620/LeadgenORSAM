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

// ── Evidence level ───────────────────────────────────────────────────────────
// What the score was actually allowed to rest on, measured rather than
// declared. "none" and "weak" both cap the score at 39 and land in `cold`,
// but they call for different operator decisions: nothing was found at all,
// versus one of the expected sources answered. Showing only the
// evidence_verified boolean collapses that distinction.

export type EvidenceLevel = 'none' | 'weak' | 'sufficient'

export const EVIDENCE_LEVEL_LABEL: Record<EvidenceLevel, string> = {
  none: 'Aucune source exploitable',
  weak: 'Sources partielles (une seule des sources attendues)',
  sufficient: 'Sources complètes',
}

export const EVIDENCE_LEVEL_STYLE: Record<EvidenceLevel, CSSProperties> = {
  none: { background: 'rgba(239,68,68,0.10)', color: '#ef4444' },
  weak: { background: 'rgba(251,191,36,0.12)', color: '#fbbf24' },
  sufficient: { background: 'rgba(34,197,94,0.10)', color: '#22c55e' },
}

export function evidenceLabel(value?: string): string | null {
  if (!value) return null
  return EVIDENCE_LEVEL_LABEL[value as EvidenceLevel] ?? value
}
