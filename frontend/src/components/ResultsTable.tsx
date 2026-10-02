import { useState, useMemo } from 'react'
import { Download, Search, ExternalLink, MessageSquare, ChevronLeft, ChevronRight, SearchX, ArrowUpDown, ArrowUp, ArrowDown, Copy, CheckCircle2, XCircle, HelpCircle, Clock } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { getDownloadUrl, type Lead } from '@/lib/api'
import { evidenceLabel } from '@/lib/tiers'
import { LeadDetailModal } from './LeadDetailModal'
import { LinkedinMessageDialog, NO_ANGLE_REASON, hasAngle } from './LinkedinMessage'

// Visual style for each email_status value the cascade can produce
// (enrichers/email_cascade.py::EMAIL_STATUSES).
const EMAIL_STATUS_STYLE: Record<string, { icon: typeof CheckCircle2; color: string; label: string }> = {
  valid_nominatif: { icon: CheckCircle2, color: '#22c55e', label: 'Email nominatif vérifié' },
  valid_generique: { icon: CheckCircle2, color: '#4d9fff', label: 'Email générique vérifié' },
  catch_all:       { icon: HelpCircle,   color: '#fbbf24', label: 'Domaine catch-all (incertain)' },
  unverified:      { icon: HelpCircle,   color: 'rgba(148,163,184,0.85)', label: 'Non vérifié' },
  not_found:       { icon: XCircle,      color: '#ef4444', label: 'Introuvable' },
  pending_quota:   { icon: Clock,        color: '#60a5fa', label: 'En attente de quota' },
  provider_failure:{ icon: XCircle,      color: '#ef4444', label: 'Échec fournisseur' },
}

const PAGE_SIZE = 10

interface Props {
  leads: Lead[]
  jobId: string
}

type Tab = 'all' | 'reachable' | 'unreachable' | 'pending'
type SortKey = 'name' | 'company' | null
type SortDir = 'asc' | 'desc'

function copyToClipboard(text: string, label: string) {
  navigator.clipboard.writeText(text).then(() => {
    toast.success(`${label} copié`)
  })
}

function getSortValue(lead: Lead, key: SortKey): string | number {
  switch (key) {
    case 'name': return `${lead.first_name ?? ''} ${lead.last_name ?? ''}`.toLowerCase()
    case 'company': return (lead.company ?? '').toLowerCase()
    default: return 0
  }
}

export function ResultsTable({ leads, jobId }: Props) {
  const [tab, setTab] = useState<Tab>('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null)
  const [messageLead, setMessageLead] = useState<Lead | null>(null)
  const [sortBy, setSortBy] = useState<SortKey>(null)
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const handleSort = (key: SortKey) => {
    if (sortBy === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(key)
      setSortDir('desc')
    }
    setPage(0)
  }

  const filtered = useMemo(() => {
    let list = leads
    // reachable is a tri-state: true / false / null (pending_quota — never
    // asked the question, so it must not be lumped in with unreachable).
    if (tab === 'reachable')   list = leads.filter(l => l.reachable === true)
    if (tab === 'unreachable') list = leads.filter(l => l.reachable === false)
    if (tab === 'pending')     list = leads.filter(l => l.reachable == null)
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(l =>
        [l.first_name, l.last_name, l.company, l.job_title, l.email].some(v => v?.toLowerCase().includes(q))
      )
    }
    if (sortBy) {
      list = [...list].sort((a, b) => {
        const va = getSortValue(a, sortBy)
        const vb = getSortValue(b, sortBy)
        const cmp = va < vb ? -1 : va > vb ? 1 : 0
        return sortDir === 'asc' ? cmp : -cmp
      })
    }
    return list
  }, [leads, tab, search, sortBy, sortDir])

  const pageCount = Math.ceil(filtered.length / PAGE_SIZE)
  const pageLeads = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const handleTabChange = (t: Tab) => { setTab(t); setPage(0) }
  const reachableCount   = leads.filter(l => l.reachable === true).length
  const unreachableCount = leads.filter(l => l.reachable === false).length
  const pendingCount     = leads.filter(l => l.reachable == null).length

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      {/* Lead detail modal */}
      {selectedLead && (
        <LeadDetailModal lead={selectedLead} onClose={() => setSelectedLead(null)} />
      )}
      {/* Message dialog opened from a row's action button */}
      {messageLead && (
        <LinkedinMessageDialog lead={messageLead} onClose={() => setMessageLead(null)} />
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <h2 className="text-base font-semibold" style={{ color: 'var(--th-text-secondary)', letterSpacing: '-0.01em' }}>
          Leads ({filtered.length})
        </h2>
        <div className="flex items-center gap-2">
          <a
            href={getDownloadUrl(jobId)}
            download
            className="btn-grad inline-flex items-center gap-2 rounded-lg text-white font-medium text-sm"
            style={{ padding: '8px 16px', border: 'none', textDecoration: 'none' }}
          >
            <Download className="w-4 h-4" />
            CSV
          </a>
          <a
            href={`${getDownloadUrl(jobId)}?format=xlsx`}
            download
            className="inline-flex items-center gap-2 rounded-lg text-sm font-medium"
            style={{ padding: '8px 16px', color: 'var(--th-success)', background: 'var(--th-success-soft)', border: '1px solid var(--th-success-border)', textDecoration: 'none' }}
          >
            <Download className="w-4 h-4" />
            Excel
          </a>
          <a
            href={`${getDownloadUrl(jobId)}?format=json`}
            download
            className="inline-flex items-center gap-2 rounded-lg text-sm font-medium"
            style={{ padding: '8px 16px', color: 'var(--th-purple)', background: 'rgba(155,107,255,0.08)', border: '1px solid rgba(155,107,255,0.2)', textDecoration: 'none' }}
          >
            <Download className="w-4 h-4" />
            JSON
          </a>
        </div>
      </div>

      {/* Tabs + search */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex gap-1 p-1 rounded-lg" style={{ background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)' }}>
          {([
            { key: 'all',         label: `Tous (${leads.length})` },
            { key: 'reachable',   label: `Joignables (${reachableCount})` },
            { key: 'unreachable', label: `Non joignables (${unreachableCount})` },
            { key: 'pending',     label: `En attente de quota (${pendingCount})` },
          ] as { key: Tab; label: string }[]).map(t => (
            <button
              key={t.key}
              onClick={() => handleTabChange(t.key)}
              className="px-3 py-1.5 rounded-md text-sm font-medium transition-all"
              style={tab === t.key ? {
                background: 'var(--th-border-strong)',
                color: 'var(--th-text-primary)',
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'inherit',
              } : {
                color: 'var(--th-text-quaternary)',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="relative flex-1 sm:max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: 'var(--th-text-faint)' }} />
          <input
            type="text"
            placeholder="Rechercher…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(0) }}
            className="surface-input w-full"
            style={{ paddingLeft: 36, paddingRight: 12, paddingTop: 8, paddingBottom: 8, fontSize: 13, borderRadius: 8 }}
          />
        </div>
      </div>

      {/* Table */}
      <div className="glass-card overflow-hidden">
        {/* table-fixed + percentage widths: the table always fits its card, so
            there is no horizontal scroll. Long cells truncate with a title. */}
        <div>
          <table className="w-full text-sm table-fixed" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--th-border-default)', background: 'var(--th-surface-hover)' }}>
                {([
                  { key: 'name' as SortKey, label: 'Nom', width: '17%' },
                  { key: 'company' as SortKey, label: 'Société', width: '14%' },
                  { key: null, label: 'Email', width: '25%' },
                  { key: null, label: 'Téléphone', width: '14%' },
                  { key: null, label: 'LinkedIn', width: '9%' },
                  { key: null, label: 'Angle IA', width: '16%' },
                  { key: null, label: 'Message', width: '5%' },
                ]).map(h => (
                  <th
                    key={h.label}
                    className={cn('text-left px-3 py-3 text-xs font-semibold whitespace-nowrap overflow-hidden', h.key && 'cursor-pointer select-none')}
                    style={{ width: h.width, color: sortBy === h.key ? 'var(--th-primary)' : 'var(--th-text-muted)', letterSpacing: '0.05em', textTransform: 'uppercase' }}
                    onClick={h.key ? () => handleSort(h.key) : undefined}
                  >
                    <span className="inline-flex items-center gap-1">
                      {/* The action column is an icon: its label is for screen readers. */}
                      {h.label === 'Message' ? <span className="sr-only">{h.label}</span> : h.label}
                      {h.key && (
                        sortBy === h.key
                          ? (sortDir === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)
                          : <ArrowUpDown className="w-3 h-3" style={{ opacity: 0.3 }} />
                      )}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pageLeads.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center">
                    <SearchX className="w-10 h-10 mx-auto mb-3" style={{ color: 'var(--th-text-ghost)' }} />
                    <p className="text-sm" style={{ color: 'var(--th-text-faint)' }}>Aucun lead trouvé</p>
                  </td>
                </tr>
              )}
              {pageLeads.map((lead, i) => {
                const globalIdx = page * PAGE_SIZE + i
                const fullName = [lead.first_name, lead.last_name].filter(Boolean).join(' ')
                return (
                    <tr
                      key={globalIdx}
                      onClick={() => setSelectedLead(lead)}
                      className="cursor-pointer transition-colors row-hoverable"
                      style={{ borderBottom: '1px solid var(--th-border-subtle)' }}
                    >
                      <td className="px-3 py-3 overflow-hidden">
                        <span className="block font-medium truncate" title={fullName || undefined} style={{ color: 'var(--th-text-primary)' }}>{fullName || '—'}</span>
                        {/* Second line: the evidence badge, then the job title. They
                            ride under the name so they cost no column. */}
                        {(lead.evidence_verified === false || lead.job_title) && (
                        <span className="flex items-center gap-1.5 min-w-0 mt-0.5">
                          {lead.evidence_verified === false && (
                            <span
                              // The tooltip names the evidence level: "none" and
                              // "weak" both land here, but only one of them means
                              // nothing at all was found. The sentence is fixed on
                              // purpose: icp_rationale carries "Secteur 70/100…",
                              // which would bring the 0-100 score back via hover.
                              title={[
                                lead.evidence_level
                                  ? `Niveau de preuve : ${evidenceLabel(lead.evidence_level)}`
                                  : null,
                                'Preuves insuffisantes — qualification manuelle nécessaire',
                              ].filter(Boolean).join('\n')}
                              className="text-xs px-1.5 py-0.5 rounded shrink-0"
                              style={{ background: 'rgba(148,163,184,0.12)', color: '#94a3b8' }}
                            >
                              non vérifié
                            </span>
                          )}
                          {lead.job_title && (
                            <span className="truncate text-xs" title={lead.job_title} style={{ color: 'var(--th-text-muted)' }}>
                              {lead.job_title}
                            </span>
                          )}
                        </span>
                        )}
                      </td>
                      <td className="px-3 py-3 overflow-hidden" style={{ color: 'var(--th-text-tertiary)' }}>
                        {lead.website ? (
                          <a href={lead.website} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} title={lead.company || undefined} className="flex items-center gap-1 min-w-0" style={{ color: 'var(--th-primary)' }}>
                            <span className="truncate">{lead.company || '—'}</span><ExternalLink className="w-3 h-3 shrink-0" />
                          </a>
                        ) : <span className="block truncate" title={lead.company || undefined}>{lead.company || '—'}</span>}
                      </td>
                      <td className="px-3 py-3 overflow-hidden">
                        {lead.email ? (
                          <span className="flex items-center gap-1.5 min-w-0">
                            {lead.email_status && EMAIL_STATUS_STYLE[lead.email_status] && (() => {
                              const s = EMAIL_STATUS_STYLE[lead.email_status]
                              const Icon = s.icon
                              const tooltip = `${s.label}${lead.email_confidence != null ? ` — score ${lead.email_confidence}/100` : ''}`
                              return (
                                <span
                                  title={tooltip}
                                  className="inline-flex items-center shrink-0"
                                  style={{ color: s.color }}
                                >
                                  <Icon className="w-3.5 h-3.5" />
                                </span>
                              )
                            })()}
                            <a href={`mailto:${lead.email}`} onClick={e => e.stopPropagation()} title={lead.email} className="font-mono text-xs truncate min-w-0" style={{ color: 'var(--th-primary)' }}>
                              {lead.email}
                            </a>
                            <button onClick={e => { e.stopPropagation(); copyToClipboard(lead.email!, 'Email') }} className="p-0.5 rounded transition-colors shrink-0" style={{ color: 'var(--th-text-ghost)', background: 'none', border: 'none', cursor: 'pointer' }} title="Copier"><Copy className="w-3 h-3" /></button>
                          </span>
                        ) : <span style={{ color: 'var(--th-text-ghost)' }}>—</span>}
                      </td>
                      <td className="px-3 py-3 overflow-hidden">
                        {lead.phone ? (
                          <span className="flex items-center gap-1 min-w-0">
                            <a href={`tel:${lead.phone}`} onClick={e => e.stopPropagation()} title={lead.phone} className="font-mono text-xs truncate min-w-0" style={{ color: 'var(--th-primary)' }}>
                              {lead.phone}
                            </a>
                            <button onClick={e => { e.stopPropagation(); copyToClipboard(lead.phone!, 'Téléphone') }} className="p-0.5 rounded transition-colors shrink-0" style={{ color: 'var(--th-text-ghost)', background: 'none', border: 'none', cursor: 'pointer' }} title="Copier"><Copy className="w-3 h-3" /></button>
                          </span>
                        ) : <span style={{ color: 'var(--th-text-ghost)' }}>—</span>}
                      </td>
                      <td className="px-3 py-3 overflow-hidden">
                        {lead.linkedin_url ? (
                          <span className="flex items-center gap-1 min-w-0">
                            <a href={lead.linkedin_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="inline-flex items-center gap-1 text-xs" style={{ color: 'var(--th-primary)' }}>
                              Profil <ExternalLink className="w-3 h-3" />
                            </a>
                            <button onClick={e => { e.stopPropagation(); copyToClipboard(lead.linkedin_url!, 'LinkedIn') }} className="p-0.5 rounded transition-colors shrink-0" style={{ color: 'var(--th-text-ghost)', background: 'none', border: 'none', cursor: 'pointer' }} title="Copier"><Copy className="w-3 h-3" /></button>
                          </span>
                        ) : <span style={{ color: 'var(--th-text-ghost)' }}>—</span>}
                      </td>
                      <td className="px-3 py-3 overflow-hidden">
                        {lead.conversion_angle
                          ? <span className="block truncate text-xs" title={lead.conversion_angle} style={{ color: 'var(--th-text-quaternary)' }}>{lead.conversion_angle}</span>
                          : <span className="text-xs" title="Aucun angle : la recherche IA était désactivée ou n'a rien produit pour ce lead" style={{ color: 'var(--th-text-ghost)' }}>—</span>}
                      </td>
                      <td className="px-3 py-3">
                        {/* The wrapper carries the tooltip: a disabled button does not
                            reliably show its own title in every browser. */}
                        <span title={hasAngle(lead) ? 'Générer un message LinkedIn' : NO_ANGLE_REASON} onClick={e => e.stopPropagation()} className="inline-flex">
                          <button
                            onClick={e => { e.stopPropagation(); setMessageLead(lead) }}
                            disabled={!hasAngle(lead)}
                            aria-label={hasAngle(lead) ? 'Générer un message LinkedIn' : NO_ANGLE_REASON}
                            className="p-1.5 rounded-md transition-colors"
                            style={{
                              color: hasAngle(lead) ? 'var(--th-primary)' : 'var(--th-text-ghost)',
                              background: hasAngle(lead) ? 'var(--th-primary-soft)' : 'none',
                              border: 'none',
                              cursor: hasAngle(lead) ? 'pointer' : 'not-allowed',
                              opacity: hasAngle(lead) ? 1 : 0.5,
                            }}
                          >
                            <MessageSquare className="w-4 h-4" />
                          </button>
                        </span>
                      </td>
                    </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {pageCount > 1 && (
          <div className="flex items-center justify-between px-4 py-3" style={{ borderTop: '1px solid var(--th-border-default)', background: 'var(--th-surface-hover)' }}>
            <span className="text-xs" style={{ color: 'var(--th-text-muted)' }}>
              Page {page + 1} / {pageCount} — {filtered.length} leads
            </span>
            <div className="flex gap-1">
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0}
                className={cn('p-1.5 rounded-md transition-colors', page === 0 && 'opacity-30 cursor-not-allowed')}
                style={{ color: 'var(--th-text-tertiary)', background: 'none', border: 'none', cursor: page === 0 ? 'not-allowed' : 'pointer' }}
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))}
                disabled={page === pageCount - 1}
                className={cn('p-1.5 rounded-md transition-colors', page === pageCount - 1 && 'opacity-30 cursor-not-allowed')}
                style={{ color: 'var(--th-text-tertiary)', background: 'none', border: 'none', cursor: page === pageCount - 1 ? 'not-allowed' : 'pointer' }}
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
