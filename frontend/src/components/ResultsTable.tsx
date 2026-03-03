import { useState, useMemo } from 'react'
import { Download, Search, ExternalLink, ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getDownloadUrl, type Lead } from '@/lib/api'

const PAGE_SIZE = 10

interface Props {
  leads: Lead[]
  jobId: string
}

type Tab = 'all' | 'hit' | 'nohit'

export function ResultsTable({ leads, jobId }: Props) {
  const [tab, setTab] = useState<Tab>('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [expandedRow, setExpandedRow] = useState<number | null>(null)

  const filtered = useMemo(() => {
    let list = leads
    if (tab === 'hit')   list = leads.filter(l => l.is_hit)
    if (tab === 'nohit') list = leads.filter(l => !l.is_hit)
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(l =>
        [l.first_name, l.last_name, l.company, l.job_title, l.email].some(v => v?.toLowerCase().includes(q))
      )
    }
    return list
  }, [leads, tab, search])

  const pageCount = Math.ceil(filtered.length / PAGE_SIZE)
  const pageLeads = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const handleTabChange = (t: Tab) => { setTab(t); setPage(0) }
  const hitCount   = leads.filter(l => l.is_hit).length
  const nohitCount = leads.filter(l => !l.is_hit).length

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <h2 className="text-base font-semibold" style={{ color: 'rgba(226,232,248,0.6)', letterSpacing: '-0.01em' }}>
          Leads ({filtered.length})
        </h2>
        <a
          href={getDownloadUrl(jobId)}
          download
          className="btn-grad inline-flex items-center gap-2 rounded-lg text-white font-medium text-sm"
          style={{ padding: '8px 16px', border: 'none', textDecoration: 'none' }}
        >
          <Download className="w-4 h-4" />
          Télécharger CSV
        </a>
      </div>

      {/* Tabs + search */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex gap-1 p-1 rounded-lg" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}>
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
                background: 'rgba(255,255,255,0.08)',
                color: '#e2e8f8',
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'inherit',
              } : {
                color: 'rgba(226,232,248,0.4)',
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
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: 'rgba(226,232,248,0.25)' }} />
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
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}>
                {['Nom', 'Poste', 'Entreprise', 'Email', 'LinkedIn', 'Score', 'Hit', 'Angle IA'].map(h => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-semibold whitespace-nowrap" style={{ color: 'rgba(226,232,248,0.3)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pageLeads.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-sm" style={{ color: 'rgba(226,232,248,0.25)' }}>
                    Aucun lead trouvé
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
                      onClick={() => setExpandedRow(isExpanded ? null : globalIdx)}
                      className="cursor-pointer transition-colors"
                      style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', background: isExpanded ? 'rgba(77,159,255,0.05)' : 'transparent' }}
                      onMouseOver={e => { if (!isExpanded) (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.025)' }}
                      onMouseOut={e => { if (!isExpanded) (e.currentTarget as HTMLTableRowElement).style.background = 'transparent' }}
                    >
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="font-medium" style={{ color: '#e2e8f8' }}>{fullName || '—'}</span>
                        {lead.location && <span className="block text-xs mt-0.5" style={{ color: 'rgba(226,232,248,0.3)' }}>{lead.location}</span>}
                      </td>
                      <td className="px-4 py-3 max-w-[160px] truncate whitespace-nowrap" style={{ color: 'rgba(226,232,248,0.5)' }}>
                        {lead.job_title || '—'}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap" style={{ color: 'rgba(226,232,248,0.5)' }}>
                        {lead.website ? (
                          <a href={lead.website} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="flex items-center gap-1" style={{ color: '#4d9fff' }}>
                            {lead.company || '—'}<ExternalLink className="w-3 h-3" />
                          </a>
                        ) : (lead.company || '—')}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {lead.email ? (
                          <a href={`mailto:${lead.email}`} onClick={e => e.stopPropagation()} className="font-mono text-xs" style={{ color: '#4d9fff' }}>
                            {lead.email}
                          </a>
                        ) : <span style={{ color: 'rgba(226,232,248,0.15)' }}>—</span>}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {lead.linkedin_url ? (
                          <a href={lead.linkedin_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="inline-flex items-center gap-1 text-xs" style={{ color: '#4d9fff' }}>
                            Profil <ExternalLink className="w-3 h-3" />
                          </a>
                        ) : <span style={{ color: 'rgba(226,232,248,0.15)' }}>—</span>}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <div className="w-12 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
                            <div
                              className="h-full rounded-full"
                              style={{ width: `${lead.hit_score ?? 0}%`, background: (lead.hit_score ?? 0) >= 50 ? '#34d399' : 'rgba(226,232,248,0.2)' }}
                            />
                          </div>
                          <span className="font-mono text-xs" style={{ color: 'rgba(226,232,248,0.5)' }}>{lead.hit_score ?? 0}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                          style={lead.is_hit ? { background: 'rgba(52,211,153,0.1)', color: '#34d399', border: '1px solid rgba(52,211,153,0.2)' } : { background: 'rgba(255,255,255,0.04)', color: 'rgba(226,232,248,0.3)', border: '1px solid rgba(255,255,255,0.07)' }}
                        >
                          {lead.is_hit ? '✓ Hit' : 'No-hit'}
                        </span>
                      </td>
                      <td className="px-4 py-3 max-w-[200px]">
                        {lead.conversion_angle
                          ? <span className="text-xs line-clamp-2" style={{ color: 'rgba(226,232,248,0.4)' }}>{lead.conversion_angle}</span>
                          : <span className="text-xs" style={{ color: 'rgba(226,232,248,0.15)' }}>—</span>}
                      </td>
                    </tr>

                    {isExpanded && (lead.activity_summary || lead.conversion_angle) && (
                      <tr key={`${globalIdx}-expanded`} style={{ background: 'rgba(77,159,255,0.04)', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        <td colSpan={8} className="px-5 py-4">
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
                            {lead.activity_summary && (
                              <div>
                                <p className="font-medium mb-1.5" style={{ color: 'rgba(226,232,248,0.5)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Résumé activité</p>
                                <p style={{ color: 'rgba(226,232,248,0.6)', lineHeight: 1.6 }}>{lead.activity_summary}</p>
                              </div>
                            )}
                            {lead.conversion_angle && (
                              <div>
                                <p className="font-medium mb-1.5" style={{ color: 'rgba(226,232,248,0.5)', fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Angle de conversion</p>
                                <p style={{ color: 'rgba(226,232,248,0.6)', lineHeight: 1.6 }}>{lead.conversion_angle}</p>
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
          <div className="flex items-center justify-between px-4 py-3" style={{ borderTop: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.01)' }}>
            <span className="text-xs" style={{ color: 'rgba(226,232,248,0.3)' }}>
              Page {page + 1} / {pageCount} — {filtered.length} leads
            </span>
            <div className="flex gap-1">
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0}
                className={cn('p-1.5 rounded-md transition-colors', page === 0 && 'opacity-30 cursor-not-allowed')}
                style={{ color: 'rgba(226,232,248,0.5)', background: 'none', border: 'none', cursor: page === 0 ? 'not-allowed' : 'pointer' }}
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))}
                disabled={page === pageCount - 1}
                className={cn('p-1.5 rounded-md transition-colors', page === pageCount - 1 && 'opacity-30 cursor-not-allowed')}
                style={{ color: 'rgba(226,232,248,0.5)', background: 'none', border: 'none', cursor: page === pageCount - 1 ? 'not-allowed' : 'pointer' }}
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
