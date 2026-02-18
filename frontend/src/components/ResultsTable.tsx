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
    if (tab === 'hit') list = leads.filter(l => l.is_hit)
    if (tab === 'nohit') list = leads.filter(l => !l.is_hit)

    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(l =>
        [l.first_name, l.last_name, l.company, l.job_title, l.email]
          .some(v => v?.toLowerCase().includes(q))
      )
    }
    return list
  }, [leads, tab, search])

  const pageCount = Math.ceil(filtered.length / PAGE_SIZE)
  const pageLeads = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  const handleTabChange = (t: Tab) => { setTab(t); setPage(0) }

  const hitCount = leads.filter(l => l.is_hit).length
  const nohitCount = leads.filter(l => !l.is_hit).length

  return (
    <div className="w-full max-w-7xl mx-auto space-y-4">
      {/* Header row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-gray-800">
          Leads ({filtered.length})
        </h2>
        <a
          href={getDownloadUrl(jobId)}
          download
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
        >
          <Download className="w-4 h-4" />
          Télécharger CSV
        </a>
      </div>

      {/* Tabs + Search */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Tabs */}
        <div className="flex gap-1 bg-gray-100 p-1 rounded-lg">
          {([
            { key: 'all', label: `Tous (${leads.length})` },
            { key: 'hit', label: `Hits (${hitCount})` },
            { key: 'nohit', label: `No-hit (${nohitCount})` },
          ] as { key: Tab; label: string }[]).map(t => (
            <button
              key={t.key}
              onClick={() => handleTabChange(t.key)}
              className={cn(
                'px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                tab === t.key
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="relative flex-1 sm:max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Rechercher..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(0) }}
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-medium text-gray-600 whitespace-nowrap">Nom</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 whitespace-nowrap">Poste</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 whitespace-nowrap">Entreprise</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 whitespace-nowrap">Email</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 whitespace-nowrap">LinkedIn</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 whitespace-nowrap">Score</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 whitespace-nowrap">Hit</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Angle IA</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {pageLeads.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-gray-400">
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
                      className={cn(
                        'cursor-pointer transition-colors',
                        isExpanded ? 'bg-blue-50' : 'hover:bg-gray-50'
                      )}
                    >
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="font-medium text-gray-900">{fullName || '—'}</span>
                        {lead.location && (
                          <span className="block text-xs text-gray-400 mt-0.5">{lead.location}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-600 max-w-[160px] truncate whitespace-nowrap">
                        {lead.job_title || '—'}
                      </td>
                      <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                        {lead.website ? (
                          <a
                            href={lead.website}
                            target="_blank"
                            rel="noreferrer"
                            onClick={e => e.stopPropagation()}
                            className="text-blue-600 hover:underline flex items-center gap-1"
                          >
                            {lead.company || '—'}
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        ) : (lead.company || '—')}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {lead.email ? (
                          <a
                            href={`mailto:${lead.email}`}
                            onClick={e => e.stopPropagation()}
                            className="text-blue-600 hover:underline font-mono text-xs"
                          >
                            {lead.email}
                          </a>
                        ) : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {lead.linkedin_url ? (
                          <a
                            href={lead.linkedin_url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={e => e.stopPropagation()}
                            className="inline-flex items-center gap-1 text-blue-700 hover:underline text-xs"
                          >
                            Profil <ExternalLink className="w-3 h-3" />
                          </a>
                        ) : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <div className="w-12 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div
                              className={cn(
                                'h-full rounded-full',
                                (lead.hit_score ?? 0) >= 50 ? 'bg-green-500' : 'bg-gray-400'
                              )}
                              style={{ width: `${lead.hit_score ?? 0}%` }}
                            />
                          </div>
                          <span className="font-mono text-xs text-gray-700">{lead.hit_score ?? 0}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className={cn(
                          'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium',
                          lead.is_hit
                            ? 'bg-green-100 text-green-800'
                            : 'bg-gray-100 text-gray-500'
                        )}>
                          {lead.is_hit ? '✓ Hit' : 'No-hit'}
                        </span>
                      </td>
                      <td className="px-4 py-3 max-w-[200px]">
                        {lead.conversion_angle ? (
                          <span className="text-xs text-gray-600 line-clamp-2">{lead.conversion_angle}</span>
                        ) : <span className="text-gray-300 text-xs">—</span>}
                      </td>
                    </tr>

                    {/* Expanded row for AI summary */}
                    {isExpanded && (lead.activity_summary || lead.conversion_angle) && (
                      <tr key={`${globalIdx}-expanded`} className="bg-blue-50">
                        <td colSpan={8} className="px-4 py-3">
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
                            {lead.activity_summary && (
                              <div>
                                <p className="font-medium text-gray-700 mb-1">Résumé activité</p>
                                <p className="text-gray-600">{lead.activity_summary}</p>
                              </div>
                            )}
                            {lead.conversion_angle && (
                              <div>
                                <p className="font-medium text-gray-700 mb-1">Angle de conversion</p>
                                <p className="text-gray-600">{lead.conversion_angle}</p>
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
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 bg-gray-50">
            <span className="text-xs text-gray-500">
              Page {page + 1} / {pageCount} — {filtered.length} leads
            </span>
            <div className="flex gap-1">
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0}
                className={cn(
                  'p-1.5 rounded-md hover:bg-gray-200 transition-colors',
                  page === 0 && 'opacity-40 cursor-not-allowed'
                )}
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))}
                disabled={page === pageCount - 1}
                className={cn(
                  'p-1.5 rounded-md hover:bg-gray-200 transition-colors',
                  page === pageCount - 1 && 'opacity-40 cursor-not-allowed'
                )}
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
