import { X, Briefcase, MapPin, Mail, Phone, Linkedin, Globe, Target, TrendingUp, DollarSign, Activity, Zap, Copy, ExternalLink, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import {
  EVIDENCE_LEVEL_STYLE, TIER_ICON, TIER_STYLE, emailSourceLabel, evidenceLabel, tierOf,
} from '@/lib/tiers'

function copyToClipboard(text: string, label: string) {
  navigator.clipboard.writeText(text).then(() => toast.success(`${label} copié`))
}

interface LeadData {
  first_name?: string
  last_name?: string
  company?: string
  job_title?: string
  location?: string
  email?: string
  phone?: string
  linkedin_url?: string
  website?: string
  reachable?: boolean | null
  prescore?: number
  // Email acquisition — which branch of the cascade produced this address.
  email_source?: string
  email_type?: string
  contact_source_url?: string
  // Domain-level facts, shared by every lead on the same domain.
  domain_catch_all?: boolean | null
  domain_mx_provider?: string
  domain_mismatch?: boolean
  icp_score?: number
  icp_tier?: string
  icp_rationale?: string
  icp_scores_detail?: string
  activity_summary?: string
  conversion_angle?: string
  digital_maturity?: string
  estimated_budget?: string
  business_signals?: string
  disqualification_reason?: string
  evidence_level?: 'none' | 'weak' | 'sufficient'
  evidence_verified?: boolean
  website_rejected?: string
  website_check_reason?: string
  enriched?: boolean
}

interface Props {
  lead: LeadData
  onClose: () => void
}

export function LeadDetailModal({ lead, onClose }: Props) {
  const fullName = [lead.first_name, lead.last_name].filter(Boolean).join(' ')
  const hasEnrichment = lead.activity_summary || lead.conversion_angle || lead.digital_maturity || lead.estimated_budget || lead.business_signals || lead.icp_rationale

  const sections = [
    { key: 'icp_rationale', label: 'Analyse ICP', icon: <Target className="w-4 h-4" /> },
    { key: 'activity_summary', label: 'Résumé d\'activité', icon: <Activity className="w-4 h-4" /> },
    { key: 'conversion_angle', label: 'Angle de conversion recommandé', icon: <TrendingUp className="w-4 h-4" /> },
    { key: 'digital_maturity', label: 'Maturité digitale', icon: <Globe className="w-4 h-4" /> },
    { key: 'estimated_budget', label: 'Budget estimé', icon: <DollarSign className="w-4 h-4" /> },
    { key: 'business_signals', label: 'Signaux business', icon: <Zap className="w-4 h-4" /> },
  ]

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-xl"
        style={{ background: 'var(--th-bg)', border: '1px solid var(--th-glass-border)', boxShadow: '0 32px 80px rgba(0,0,0,0.4)' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between p-6" style={{ borderBottom: '1px solid var(--th-border-default)' }}>
          <div>
            <h2 className="text-xl font-bold inline-flex items-center gap-2" style={{ color: 'var(--th-text-primary)' }}>
              {fullName || 'Lead'}
            </h2>
            {lead.job_title && (
              <div className="flex items-center gap-1.5 mt-1">
                <Briefcase className="w-3.5 h-3.5" style={{ color: 'var(--th-text-muted)' }} />
                <span className="text-sm" style={{ color: 'var(--th-text-secondary)' }}>{lead.job_title}</span>
              </div>
            )}
            {lead.company && (
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-sm font-medium" style={{ color: 'var(--th-text-tertiary)' }}>{lead.company}</span>
              </div>
            )}
            {lead.location && (
              <div className="flex items-center gap-1.5 mt-0.5">
                <MapPin className="w-3.5 h-3.5" style={{ color: 'var(--th-text-muted)' }} />
                <span className="text-xs" style={{ color: 'var(--th-text-quaternary)' }}>{lead.location}</span>
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg transition-colors"
            style={{ color: 'var(--th-text-muted)', background: 'var(--th-glass-inset)', border: 'none', cursor: 'pointer' }}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Disqualification / evidence / domain-mismatch warnings */}
        {(lead.disqualification_reason || lead.evidence_verified === false || lead.domain_mismatch) && (
          <div className="px-6 pt-4">
            {lead.disqualification_reason && (
              <div className="text-sm rounded-lg px-3 py-2 mb-2"
                   style={{ background: 'rgba(148,163,184,0.12)', color: '#94a3b8' }}>
                ⛔ Disqualifié — {lead.disqualification_reason}
              </div>
            )}
            {lead.evidence_verified === false && (
              <div className="text-sm rounded-lg px-3 py-2 mb-2"
                   style={{ background: 'var(--th-warning-soft)', color: 'var(--th-warning-text)' }}>
                Preuves insuffisantes — qualification manuelle nécessaire
                {lead.evidence_level && (
                  <span className="block text-xs mt-0.5" style={{ opacity: 0.85 }}>
                    {evidenceLabel(lead.evidence_level)}
                  </span>
                )}
              </div>
            )}
            {lead.domain_mismatch && (
              <div className="flex items-center gap-2 text-sm rounded-lg px-3 py-2 mb-2"
                   style={{ background: 'var(--th-warning-soft)', color: 'var(--th-warning-text)' }}>
                <AlertTriangle className="w-4 h-4 shrink-0" />
                Le fournisseur a renvoyé un email sur un domaine différent de celui attendu — à vérifier avant tout envoi.
              </div>
            )}
          </div>
        )}

        {/* Contact info */}
        <div className="p-6 grid grid-cols-2 gap-3" style={{ borderBottom: '1px solid var(--th-border-default)' }}>
          {lead.email && (
            <div className="flex items-center gap-2 p-3 rounded-lg" style={{ background: 'var(--th-glass-inset)' }}>
              <Mail className="w-4 h-4 shrink-0" style={{ color: 'var(--th-primary)' }} />
              <a href={`mailto:${lead.email}`} className="text-sm font-mono truncate" style={{ color: 'var(--th-primary)' }}>{lead.email}</a>
              <button onClick={() => copyToClipboard(lead.email!, 'Email')} className="shrink-0" style={{ color: 'var(--th-text-ghost)', background: 'none', border: 'none', cursor: 'pointer' }}><Copy className="w-3 h-3" /></button>
            </div>
          )}
          {lead.phone && (
            <div className="flex items-center gap-2 p-3 rounded-lg" style={{ background: 'var(--th-glass-inset)' }}>
              <Phone className="w-4 h-4 shrink-0" style={{ color: 'var(--th-cyan)' }} />
              <span className="text-sm font-mono" style={{ color: 'var(--th-text-primary)' }}>{lead.phone}</span>
              <button onClick={() => copyToClipboard(lead.phone!, 'Téléphone')} className="shrink-0" style={{ color: 'var(--th-text-ghost)', background: 'none', border: 'none', cursor: 'pointer' }}><Copy className="w-3 h-3" /></button>
            </div>
          )}
          {lead.linkedin_url && (
            <div className="flex items-center gap-2 p-3 rounded-lg" style={{ background: 'var(--th-glass-inset)' }}>
              <Linkedin className="w-4 h-4 shrink-0" style={{ color: 'var(--th-primary)' }} />
              <a href={lead.linkedin_url} target="_blank" rel="noreferrer" className="text-sm truncate flex items-center gap-1" style={{ color: 'var(--th-primary)' }}>
                Profil LinkedIn <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          )}
          {lead.website && (
            <div className="flex items-center gap-2 p-3 rounded-lg" style={{ background: 'var(--th-glass-inset)' }}>
              <Globe className="w-4 h-4 shrink-0" style={{ color: 'var(--th-success)' }} />
              <a href={lead.website} target="_blank" rel="noreferrer" className="text-sm truncate flex items-center gap-1" style={{ color: 'var(--th-success)' }}>
                {lead.website.replace(/^https?:\/\//, '').replace(/\/$/, '')} <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          )}
        </div>

        {/* Where each contact came from */}
        {(lead.email_source || lead.domain_mx_provider != null || lead.domain_catch_all != null) && (
          <div className="p-6 space-y-2" style={{ borderBottom: '1px solid var(--th-border-default)' }}>
            <h3 className="text-xs font-semibold mb-1" style={{ color: 'var(--th-text-faint)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
              Origine du contact
            </h3>
            <div className="grid grid-cols-2 gap-2 text-sm">
              {lead.email_source && (
                <div style={{ color: 'var(--th-text-tertiary)' }}>
                  Source email : <span style={{ color: 'var(--th-text-primary)' }}>{emailSourceLabel(lead.email_source)}</span>
                  {lead.email_type && <span style={{ color: 'var(--th-text-muted)' }}> ({lead.email_type})</span>}
                </div>
              )}
              {lead.contact_source_url && (
                <div>
                  <a
                    href={lead.contact_source_url} target="_blank" rel="noreferrer"
                    className="inline-flex items-center gap-1"
                    style={{ color: 'var(--th-primary)' }}
                  >
                    Page source <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
              )}
              {lead.domain_mx_provider != null && (
                <div style={{ color: 'var(--th-text-tertiary)' }}>
                  Fournisseur mail : <span style={{ color: 'var(--th-text-primary)' }}>{lead.domain_mx_provider || 'inconnu'}</span>
                </div>
              )}
              {lead.domain_catch_all != null && (
                <div style={{ color: 'var(--th-text-tertiary)' }}>
                  Domaine catch-all : <span style={{ color: 'var(--th-text-primary)' }}>{lead.domain_catch_all ? 'oui' : 'non'}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Scores */}
        <div className="p-6 flex items-center gap-4 flex-wrap" style={{ borderBottom: '1px solid var(--th-border-default)' }}>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold" style={{ color: 'var(--th-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Pré-score</span>
            <span className="font-mono font-bold text-lg" style={{ color: (lead.prescore ?? 0) >= 30 ? 'var(--th-success)' : 'var(--th-text-quaternary)' }}>{lead.prescore ?? 0}</span>
          </div>
          {lead.icp_score != null && (
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold" style={{ color: 'var(--th-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>ICP</span>
              <span
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-sm font-bold"
                style={TIER_STYLE[tierOf(lead.icp_tier)]}
              >
                {TIER_ICON[tierOf(lead.icp_tier)]} {lead.icp_score}
              </span>
            </div>
          )}
          {lead.evidence_level && (
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold" style={{ color: 'var(--th-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Niveau de preuve
              </span>
              <span
                className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                style={EVIDENCE_LEVEL_STYLE[lead.evidence_level] ?? { background: 'var(--th-glass-inset)', color: 'var(--th-text-muted)' }}
              >
                {evidenceLabel(lead.evidence_level)}
              </span>
            </div>
          )}
        </div>

        {lead.website_rejected && (
          <p className="text-xs mt-2 px-6" style={{ color: 'var(--th-text-faint)' }}>
            Site écarté (incohérent) : {lead.website_rejected}
            {lead.website_check_reason ? ` — ${lead.website_check_reason}` : ''}
          </p>
        )}

        {/* AI Enrichment Data */}
        {hasEnrichment ? (
          <div className="p-6 space-y-5">
            <h3 className="text-xs font-semibold" style={{ color: 'var(--th-text-faint)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
              Données d'enrichissement IA
            </h3>
            {sections.map(({ key, label, icon }) => {
              const value = (lead as Record<string, unknown>)[key] as string | undefined
              if (!value) return null
              return (
                <div key={key}>
                  <div className="flex items-center gap-2 mb-2">
                    <span style={{ color: 'var(--th-primary)' }}>{icon}</span>
                    <span className="text-sm font-semibold" style={{ color: 'var(--th-text-secondary)' }}>{label}</span>
                  </div>
                  <div
                    className="rounded-lg p-4 text-sm leading-relaxed"
                    style={{ background: 'var(--th-surface-hover)', color: 'var(--th-text-secondary)', border: '1px solid var(--th-border-subtle)' }}
                  >
                    {value}
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="p-6 text-center">
            <p className="text-sm" style={{ color: 'var(--th-text-muted)' }}>
              Ce lead n'a pas encore été enrichi par l'IA.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
