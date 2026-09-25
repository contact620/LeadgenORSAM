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

// ── Reachability (replaces the hit score, 2026-09-25) ────────────────────────
// A lead either has a route to a human or it does not — see
// processors/reachability.py. contact_level grades the best available route;
// "indetermine" is a pending_quota lead that was never asked the question.

export type ContactLevel = 'direct' | 'indirect' | 'aucun' | 'indetermine'

export const CONTACT_LEVEL_LABEL: Record<ContactLevel, string> = {
  direct: 'Direct',
  indirect: 'Indirect',
  aucun: 'Aucun',
  indetermine: 'En attente de quota',
}

export const CONTACT_LEVEL_ICON: Record<ContactLevel, string> = {
  direct: '🟢',
  indirect: '🟠',
  aucun: '⚪',
  indetermine: '🔵',
}

export const CONTACT_LEVEL_STYLE: Record<ContactLevel, CSSProperties> = {
  direct: { background: 'rgba(34,197,94,0.10)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.25)' },
  indirect: { background: 'rgba(251,191,36,0.10)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.25)' },
  aucun: { background: 'rgba(148,163,184,0.10)', color: '#94a3b8', border: '1px solid rgba(148,163,184,0.25)' },
  indetermine: { background: 'rgba(96,165,250,0.10)', color: '#60a5fa', border: '1px solid rgba(96,165,250,0.25)' },
}

export function contactLevelOf(value?: string | null): ContactLevel {
  return (['direct', 'indirect', 'aucun', 'indetermine'] as const).includes(value as ContactLevel)
    ? (value as ContactLevel)
    : 'indetermine'
}

// ── Email source (cascade branch that produced the address) ─────────────────

export const EMAIL_SOURCE_LABEL: Record<string, string> = {
  website: 'Site web',
  pattern_verified: 'Pattern vérifié',
  prospeo: 'Prospeo',
  getprospect: 'GetProspect',
  hunter: 'Hunter.io',
}

export const EMAIL_SOURCE_ICON: Record<string, string> = {
  website: '🌐',
  pattern_verified: '🧩',
  prospeo: '🔎',
  getprospect: '🔎',
  hunter: '🔎',
}

export function emailSourceLabel(value?: string | null): string {
  if (!value) return 'Aucune'
  return EMAIL_SOURCE_LABEL[value] ?? value
}
