import type { CSSProperties } from 'react'

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
