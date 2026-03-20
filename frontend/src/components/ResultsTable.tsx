import { useState, useMemo } from 'react'
import { Download, Search, ExternalLink, ChevronLeft, ChevronRight, SearchX, ArrowUpDown, ArrowUp, ArrowDown, Copy } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { getDownloadUrl, type Lead } from '@/lib/api'
import { LeadDetailModal } from './LeadDetailModal'

const PAGE_SIZE = 10

interface Props {
  leads: Lead[]
  jobId: string
}

type Tab = 'all' | 'hit' | 'nohit'
type SortKey = 'name' | 'company' | 'score' | 'icp' | null
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
    case 'score': return lead.hit_score ?? 0
    case 'icp': return lead.icp_score ?? -1
    default: return 0
  }
}

export function ResultsTable({ leads, jobId }: Props) {
  const [tab, setTab] = useState<Tab>('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [expandedRow, setExpandedRow] = useState<number | null>(null)
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null)
  const [sortBy, setSortBy] = useState<SortKey>(null)
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [icpFilter, setIcpFilter] = useState<'all' | 'hot' | 'warm' | 'cold'>('all')

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
    if (tab === 'hit')   list = leads.filter(l => l.is_hit)
    if (tab === 'nohit') list = leads.filter(l => !l.is_hit)
    if (icpFilter !== 'all') list = list.filter(l => l.icp_tier === icpFilter)
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
  }, [leads, tab, search, sortBy, sortDir, icpFilter])

  const pageCount = Math.ceil(filtered.length / PAGE_SIZE)
  const pageLeads = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const handleTabChange = (t: Tab) => { setTab(t); setPage(0) }
  const hitCount   = leads.filter(l => l.is_hit).length
  const nohitCount = leads.filter(l => !l.is_hit).length

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      {/* Lead detail modal */}
      {selectedLead && (
        <LeadDetailModal lead={selectedLead} onClose={() => setSelectedLead(null)} />
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
        </div>
      </div>

      {/* Tabs + search */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex gap-1 p-1 rounded-lg" style={{ background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)' }}>
          {([
            { key: 'all',   label: `Tous (${leads.length})` },
            { key: 'hit',   label: `Hits (${hitCount})` },
            { key: 'nohit', label: `No-hit (${nohitCount})` },
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

        {/* ICP filter */}
        <div className="flex gap-1 p-1 rounded-lg" style={{ background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)' }}>
          {([
            { key: 'all', label: 'ICP: Tous' },
            { key: 'hot', label: '🔥 Hot' },
            { key: 'warm', label: '🟡 Warm' },
            { key: 'cold', label: '❄️ Cold' },
          ] as { key: typeof icpFilter; label: string }[]).map(f => (
            <button
              key={f.key}
              onClick={() => { setIcpFilter(f.key); setPage(0) }}
              className="px-2 py-1 rounded-md text-xs font-medium transition-all"
              style={icpFilter === f.key ? {
                background: 'var(--th-border-strong)',
                color: 'var(--th-text-primary)',
                border: 'none', cursor: 'pointer', fontFamily: 'inherit',
              } : {
                color: 'var(--th-text-quaternary)',
                background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit',
              }}
            >
              {f.label}
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
        <div className="overflow-x-auto">
          <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--th-border-default)', background: 'var(--th-surface-hover)' }}>
                {([
                  { key: 'name' as SortKey, label: 'Nom' },
                  { key: null, label: 'Poste' },
                  { key: 'company' as SortKey, label: 'Entreprise' },
                  { key: null, label: 'Email' },
                  { key: null, label: 'LinkedIn' },
                  { key: 'score' as SortKey, label: 'Score' },
                  { key: null, label: 'Hit' },
                  { key: 'icp' as SortKey, label: 'ICP' },
                  { key: null, label: 'Angle IA' },
                ]).map(h => (
                  <th
                    key={h.label}
                    className={cn('text-left px-4 py-3 text-xs font-semibold whitespace-nowrap', h.key && 'cursor-pointer select-none')}
                    style={{ color: sortBy === h.key ? 'var(--th-primary)' : 'var(--th-text-muted)', letterSpacing: '0.05em', textTransform: 'uppercase' }}
                    onClick={h.key ? () => handleSort(h.key) : undefined}
                  >
                    <span className="inline-flex items-center gap-1">
                      {h.label}
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
                  <td colSpan={9} className="px-4 py-12 text-center">
                    <SearchX className="w-10 h-10 mx-auto mb-3" style={{ color: 'var(--th-text-ghost)' }} />
                    <p className="text-sm" style={{ color: 'var(--th-text-faint)' }}>Aucun lead trouvé</p>
                  </td>
                </tr>
              )}
              {pageLeads.map((lead, i) => {
                const globalIdx = page * PAGE_SIZE + i
                const isExpanded = expandedRow === globalIdx
                const fullName = [lead.first_name, lead.last_name].filter(Boolean).join(' ')
                return (
                  <>
                    <tr
                      key={globalIdx}
                      onClick={() => setSelectedLead(lead)}
                      className={cn('cursor-pointer transition-colors', !isExpanded && 'row-hoverable')}
                      style={{ borderBottom: '1px solid var(--th-border-subtle)', background: isExpanded ? 'var(--th-primary-soft)' : 'transparent' }}
                    >
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="font-medium" style={{ color: 'var(--th-text-primary)' }}>{fullName || '—'}</span>
                        {lead.location && <span className="block text-xs mt-0.5" style={{ color: 'var(--th-text-muted)' }}>{lead.location}</span>}
                      </td>
                      <td className="px-4 py-3 max-w-[160px] truncate whitespace-nowrap" style={{ color: 'var(--th-text-tertiary)' }}>
                        {lead.job_title || '—'}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap" style={{ color: 'var(--th-text-tertiary)' }}>
                        {lead.website ? (
                          <a href={lead.website} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="flex items-center gap-1" style={{ color: 'var(--th-primary)' }}>
                            {lead.company || '—'}<ExternalLink className="w-3 h-3" />
                          </a>
                        ) : (lead.company || '—')}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {lead.email ? (
                          <span className="inline-flex items-center gap-1">
                            <a href={`mailto:${lead.email}`} onClick={e => e.stopPropagation()} className="font-mono text-xs" style={{ color: 'var(--th-primary)' }}>
                              {lead.email}
                            </a>
                            <button onClick={e => { e.stopPropagation(); copyToClipboard(lead.email!, 'Email') }} className="p-0.5 rounded transition-colors" style={{ color: 'var(--th-text-ghost)', background: 'none', border: 'none', cursor: 'pointer' }} title="Copier"><Copy className="w-3 h-3" /></button>
                          </span>
                        ) : <span style={{ color: 'var(--th-text-ghost)' }}>—</span>}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {lead.linkedin_url ? (
                          <span className="inline-flex items-center gap-1">
                            <a href={lead.linkedin_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="inline-flex items-center gap-1 text-xs" style={{ color: 'var(--th-primary)' }}>
                              Profil <ExternalLink className="w-3 h-3" />
                            </a>
                            <button onClick={e => { e.stopPropagation(); copyToClipboard(lead.linkedin_url!, 'LinkedIn') }} className="p-0.5 rounded transition-colors" style={{ color: 'var(--th-text-ghost)', background: 'none', border: 'none', cursor: 'pointer' }} title="Copier"><Copy className="w-3 h-3" /></button>
                          </span>
                        ) : <span style={{ color: 'var(--th-text-ghost)' }}>—</span>}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <div className="w-12 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--th-border-default)' }}>
                            <div
                              className="h-full rounded-full"
                              style={{ width: `${lead.hit_score ?? 0}%`, background: (lead.hit_score ?? 0) >= 50 ? 'var(--th-success)' : 'var(--th-text-ghost)' }}
                            />
                          </div>
                          <span className="font-mono text-xs" style={{ color: 'var(--th-text-tertiary)' }}>{lead.hit_score ?? 0}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                          style={lead.is_hit ? { background: 'var(--th-success-soft)', color: 'var(--th-success)', border: '1px solid var(--th-success-border)' } : { background: 'var(--th-glass-inset)', color: 'var(--th-text-muted)', border: '1px solid var(--th-glass-sm-border)' }}
                        >
                          {lead.is_hit ? '✓ Hit' : 'No-hit'}
                        </span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {lead.icp_score != null ? (
                          <span
                            className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                            style={
                              lead.icp_tier === 'hot' ? { background: 'rgba(249,115,22,0.12)', color: '#fb923c', border: '1px solid rgba(249,115,22,0.25)' }
                              : lead.icp_tier === 'warm' ? { background: 'rgba(251,191,36,0.10)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.22)' }
                              : { background: 'rgba(148,163,184,0.08)', color: 'rgba(148,163,184,0.7)', border: '1px solid rgba(148,163,184,0.15)' }
                            }
                          >
                            {lead.icp_tier === 'hot' ? '🔥' : lead.icp_tier === 'warm' ? '🟡' : '❄️'} {lead.icp_score}
                          </span>
                        ) : <span style={{ color: 'var(--th-text-ghost)' }}>—</span>}
                      </td>
                      <td className="px-4 py-3 max-w-[200px]">
                        {lead.conversion_angle
                          ? <span className="text-xs line-clamp-2" style={{ color: 'var(--th-text-quaternary)' }}>{lead.conversion_angle}</span>
                          : <span className="text-xs" style={{ color: 'var(--th-text-ghost)' }}>—</span>}
                      </td>
                    </tr>

                    {isExpanded && (lead.activity_summary || lead.conversion_angle || lead.digital_maturity || lead.estimated_budget || lead.business_signals || lead.icp_rationale) && (
                      <tr key={`${globalIdx}-expanded`} style={{ background: 'var(--th-primary-soft)', borderBottom: '1px solid var(--th-border-subtle)' }}>
                        <td colSpan={9} className="px-5 py-4">
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
                            {lead.icp_rationale && (
                              <div className="sm:col-span-2">
                                <p className="font-medium mb-1.5" style={{ color: 'var(--th-text-tertiary)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                                  Scoring ICP — {lead.icp_tier?.toUpperCase()} ({lead.icp_score}/100)
                                </p>
                                <p className="mb-2" style={{ color: 'var(--th-text-secondary)', lineHeight: 1.6 }}>{lead.icp_rationale}</p>
                                {lead.icp_scores_detail && (() => {
                                  try {
                                    const detail = JSON.parse(lead.icp_scores_detail)
                                    const axes = [
                                      { key: 'secteur', label: 'Secteur', weight: '20%' },
                                      { key: 'taille', label: 'Taille', weight: '20%' },
                                      { key: 'localisation', label: 'Localisation', weight: '20%' },
                                      { key: 'signaux', label: 'Signaux', weight: '40%' },
                                    ]
                                    return (
                                      <div className="flex gap-4 flex-wrap">
                                        {axes.map(a => (
                                          <div key={a.key} className="flex items-center gap-2">
                                            <span className="text-xs" style={{ color: 'var(--th-text-muted)', minWidth: 80 }}>{a.label} ({a.weight})</span>
                                            <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--th-border-default)' }}>
                                              <div className="h-full rounded-full" style={{ width: `${detail[a.key] ?? 0}%`, background: (detail[a.key] ?? 0) > 70 ? 'var(--th-success)' : (detail[a.key] ?? 0) >= 40 ? '#fbbf24' : 'var(--th-text-ghost)' }} />
                                            </div>
                                            <span className="font-mono text-xs" style={{ color: 'var(--th-text-quaternary)' }}>{detail[a.key] ?? 0}</span>
                                          </div>
                                        ))}
                                      </div>
                                    )
                                  } catch { return null }
                                })()}
                              </div>
                            )}
                            {lead.activity_summary && (
                              <div>
                                <p className="font-medium mb-1.5" style={{ color: 'var(--th-text-tertiary)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Résumé activité</p>
                                <p style={{ color: 'var(--th-text-secondary)', lineHeight: 1.6 }}>{lead.activity_summary}</p>
                              </div>
                            )}
                            {lead.conversion_angle && (
                              <div>
                                <p className="font-medium mb-1.5" style={{ color: 'var(--th-text-tertiary)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Angle de conversion</p>
                                <p style={{ color: 'var(--th-text-secondary)', lineHeight: 1.6 }}>{lead.conversion_angle}</p>
                              </div>
                            )}
                            {lead.digital_maturity && (
                              <div>
                                <p className="font-medium mb-1.5" style={{ color: 'var(--th-text-tertiary)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Maturité digitale</p>
                                <p style={{ color: 'var(--th-text-secondary)', lineHeight: 1.6 }}>{lead.digital_maturity}</p>
                              </div>
                            )}
                            {lead.estimated_budget && (
                              <div>
                                <p className="font-medium mb-1.5" style={{ color: 'var(--th-text-tertiary)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Budget estimé</p>
                                <p style={{ color: 'var(--th-text-secondary)', lineHeight: 1.6 }}>{lead.estimated_budget}</p>
                              </div>
                            )}
                            {lead.business_signals && (
                              <div className="sm:col-span-2">
                                <p className="font-medium mb-1.5" style={{ color: 'var(--th-text-tertiary)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Signaux business</p>
                                <p style={{ color: 'var(--th-text-secondary)', lineHeight: 1.6 }}>{lead.business_signals}</p>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
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
