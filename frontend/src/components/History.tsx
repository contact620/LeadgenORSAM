import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { Download, Eye, Trash2, AlertCircle, Clock, ArrowLeft, Loader2, Rocket, RotateCcw, Search, FileJson } from 'lucide-react'
import { getHistory, getHistoryLeads, deleteHistoryEntry, getDownloadUrl, type HistoryEntry, type Lead, type JobResult, type RerunParams } from '@/lib/api'
import { StatsBar } from './StatsBar'
import { ResultsTable } from './ResultsTable'

interface Props {
  onBack: () => void
  onRerun?: (params: RerunParams) => void
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
    + ' ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

function truncateUrl(url: string, max = 50): string {
  const clean = url.replace(/^https?:\/\//, '').replace(/#.*$/, '')
  return clean.length > max ? clean.slice(0, max) + '...' : clean
}

export function History({ onBack, onRerun }: Props) {
  const [entries, setEntries] = useState<HistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [historySearch, setHistorySearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'done' | 'error'>('all')

  const [viewEntry, setViewEntry] = useState<HistoryEntry | null>(null)
  const [viewLeads, setViewLeads] = useState<Lead[] | null>(null)
  const [viewLoading, setViewLoading] = useState(false)

  const fetchHistory = () => {
    setLoading(true)
    getHistory()
      .then(setEntries)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchHistory() }, [])

  const handleDelete = async (jobId: string) => {
    if (!confirm('Supprimer cette entrée et son fichier CSV ?')) return
    try {
      await deleteHistoryEntry(jobId)
      setEntries(prev => prev.filter(e => e.job_id !== jobId))
    } catch (err) {
      toast.error('Échec de la suppression', {
        description: err instanceof Error ? err.message : 'Erreur inconnue',
      })
    }
  }

  const handleView = async (entry: HistoryEntry) => {
    setViewEntry(entry)
    setViewLoading(true)
    try {
      const leads = await getHistoryLeads(entry.job_id)
      setViewLeads(leads)
    } catch (err) {
      setViewLeads([])
      toast.error('Impossible de charger les leads', {
        description: err instanceof Error ? err.message : 'Le fichier CSV est peut-être manquant.',
      })
    } finally {
      setViewLoading(false)
    }
  }

  // Detail view
  if (viewEntry) {
    const jobResult: JobResult = {
      job_id: viewEntry.job_id,
      status: 'done',
      total_leads: viewEntry.total_leads,
      hit_leads: viewEntry.hit_leads,
      nohit_leads: viewEntry.nohit_leads,
      stats: {
        email_pct: viewEntry.email_pct,
        linkedin_pct: viewEntry.linkedin_pct,
        phone_pct: viewEntry.phone_pct,
        website_pct: viewEntry.website_pct,
        avg_score: viewEntry.avg_score,
        email_count: 0, linkedin_count: 0, phone_count: 0, website_count: 0,
        icp_hot_count: 0, icp_warm_count: 0, icp_cold_count: 0, icp_disqualified_count: 0,
      },
      leads: viewLeads ?? [],
    }

    return (
      <div className="space-y-6">
        <button
          onClick={() => { setViewEntry(null); setViewLeads(null) }}
          className="flex items-center gap-2 text-sm transition-colors"
          style={{ color: 'var(--th-text-tertiary)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
        >
          <ArrowLeft className="w-4 h-4" />
          Retour à l'historique
        </button>

        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-base font-semibold" style={{ color: 'var(--th-text-secondary)' }}>
            Pipeline du {formatDate(viewEntry.started_at)}
          </h2>
          <span
            className="text-xs px-2 py-0.5 rounded-full font-mono"
            style={{ color: 'var(--th-text-muted)', background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)' }}
          >
            {viewEntry.job_id.slice(0, 8)}
          </span>
        </div>

        {viewLoading ? (
          <div className="flex items-center justify-center py-16 gap-3" style={{ color: 'var(--th-text-muted)' }}>
            <Loader2 className="w-5 h-5 animate-spin" />
            <span className="text-sm">Chargement des leads...</span>
          </div>
        ) : (
          <>
            <StatsBar result={jobResult} />
            {viewLeads && viewLeads.length > 0 && (
              <ResultsTable leads={viewLeads} jobId={viewEntry.job_id} />
            )}
          </>
        )}
      </div>
    )
  }

  // History list
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="flex items-center gap-2 text-sm transition-colors"
            style={{ color: 'var(--th-text-tertiary)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <h2 className="text-lg font-semibold" style={{ color: 'var(--th-text-primary)', letterSpacing: '-0.01em' }}>
            Historique des pipelines
          </h2>
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-full"
            style={{ color: 'var(--th-text-quaternary)', background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)' }}
          >
            {entries.length} run{entries.length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {/* Mini dashboard */}
      {!loading && entries.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 animate-fade-in">
          {[
            { label: 'Runs totaux', value: entries.length, color: 'var(--th-primary)' },
            { label: 'Leads générés', value: entries.reduce((s, e) => s + e.total_leads, 0), color: 'var(--th-success)' },
            { label: 'Taux de hit moyen', value: `${entries.length > 0 ? Math.round(entries.reduce((s, e) => s + (e.total_leads > 0 ? (e.hit_leads / e.total_leads) * 100 : 0), 0) / entries.length) : 0}%`, color: 'var(--th-warning)' },
            { label: 'Score moyen', value: Math.round(entries.reduce((s, e) => s + e.avg_score, 0) / entries.length), color: 'var(--th-purple)' },
          ].map((stat, i) => (
            <div key={i} className="glass-card-accent p-4">
              <p className="text-2xl font-bold" style={{ color: stat.color }}>{stat.value}</p>
              <p className="text-xs mt-1" style={{ color: 'var(--th-text-muted)' }}>{stat.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Search & filter */}
      {!loading && entries.length > 0 && (
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex gap-1 p-1 rounded-lg" style={{ background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)' }}>
            {([
              { key: 'all' as const, label: 'Tous' },
              { key: 'done' as const, label: 'Terminés' },
              { key: 'error' as const, label: 'Erreurs' },
            ]).map(f => (
              <button
                key={f.key}
                onClick={() => setStatusFilter(f.key)}
                className="px-3 py-1 rounded-md text-xs font-medium transition-all"
                style={statusFilter === f.key ? {
                  background: 'var(--th-border-strong)', color: 'var(--th-text-primary)',
                  border: 'none', cursor: 'pointer', fontFamily: 'inherit',
                } : {
                  color: 'var(--th-text-quaternary)', background: 'none',
                  border: 'none', cursor: 'pointer', fontFamily: 'inherit',
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
              placeholder="Rechercher par URL…"
              value={historySearch}
              onChange={e => setHistorySearch(e.target.value)}
              className="surface-input w-full"
              style={{ paddingLeft: 36, paddingRight: 12, paddingTop: 8, paddingBottom: 8, fontSize: 13, borderRadius: 8 }}
            />
          </div>
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-16 gap-3" style={{ color: 'var(--th-text-muted)' }}>
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Chargement...</span>
        </div>
      )}

      {error && (
        <div className="glass-card p-6 text-center space-y-2">
          <AlertCircle className="w-6 h-6 mx-auto" style={{ color: 'var(--th-error)' }} />
          <p className="text-sm" style={{ color: 'var(--th-text-tertiary)' }}>{error}</p>
        </div>
      )}

      {!loading && !error && entries.length === 0 && (
        <div className="glass-card p-10 text-center space-y-3">
          <Clock className="w-12 h-12 mx-auto" style={{ color: 'var(--th-text-ghost)' }} />
          <p className="text-sm" style={{ color: 'var(--th-text-muted)' }}>Aucun pipeline exécuté pour l'instant</p>
          <p className="text-xs" style={{ color: 'var(--th-text-faint)' }}>Lancez un pipeline depuis l'accueil pour le voir apparaître ici.</p>
          <button
            onClick={onBack}
            className="inline-flex items-center gap-2 text-sm font-medium mt-2 px-4 py-2 rounded-lg transition-all"
            style={{ color: 'var(--th-primary)', background: 'var(--th-primary-soft)', border: '1px solid var(--th-primary-border)', cursor: 'pointer', fontFamily: 'inherit' }}
          >
            <Rocket className="w-3.5 h-3.5" />
            Lancer un pipeline
          </button>
        </div>
      )}

      {!loading && entries.length > 0 && (() => {
        let displayEntries = entries
        if (statusFilter !== 'all') displayEntries = displayEntries.filter(e => e.status === statusFilter)
        if (historySearch.trim()) {
          const q = historySearch.toLowerCase()
          displayEntries = displayEntries.filter(e => e.apollo_url.toLowerCase().includes(q))
        }
        return (
        <div className="glass-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--th-border-default)', background: 'var(--th-surface-hover)' }}>
                  {['Date', 'URL Apollo', 'Leads', 'Hits', 'Score moy.', 'Statut', 'Actions'].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold whitespace-nowrap" style={{ color: 'var(--th-text-muted)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {displayEntries.map(entry => {
                  const hitRate = entry.total_leads > 0 ? Math.round((entry.hit_leads / entry.total_leads) * 100) : 0
                  return (
                    <tr
                      key={entry.job_id}
                      className="transition-colors row-hoverable"
                      style={{ borderBottom: '1px solid var(--th-border-subtle)' }}
                    >
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="font-medium" style={{ color: 'var(--th-text-primary)' }}>{formatDate(entry.started_at)}</span>
                        {entry.finished_at && (
                          <span className="block text-xs mt-0.5" style={{ color: 'var(--th-text-faint)' }}>
                            {(() => {
                              const ms = new Date(entry.finished_at).getTime() - new Date(entry.started_at).getTime()
                              const min = Math.floor(ms / 60000)
                              const sec = Math.round((ms % 60000) / 1000)
                              return `${min}m ${sec}s`
                            })()}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 max-w-[220px]">
                        <span className="text-xs font-mono block truncate" style={{ color: 'var(--th-text-quaternary)' }} title={entry.apollo_url}>
                          {truncateUrl(entry.apollo_url)}
                        </span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="font-mono font-medium" style={{ color: 'var(--th-text-primary)' }}>{entry.total_leads}</span>
                        <span className="text-xs ml-1" style={{ color: 'var(--th-text-faint)' }}>/ {entry.max_leads}</span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="font-mono" style={{ color: 'var(--th-success)' }}>{entry.hit_leads}</span>
                        <span className="text-xs ml-1" style={{ color: 'var(--th-text-faint)' }}>({hitRate}%)</span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <div className="w-10 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--th-border-default)' }}>
                            <div
                              className="h-full rounded-full"
                              style={{ width: `${entry.avg_score}%`, background: 'linear-gradient(90deg, #4d9fff, #34d399)' }}
                            />
                          </div>
                          <span className="font-mono text-xs" style={{ color: 'var(--th-text-tertiary)' }}>{entry.avg_score}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                          style={entry.status === 'done'
                            ? { background: 'var(--th-success-soft)', color: 'var(--th-success)', border: '1px solid var(--th-success-border)' }
                            : { background: 'var(--th-error-soft)', color: 'var(--th-error)', border: '1px solid var(--th-error-border)' }
                          }
                        >
                          {entry.status === 'done' ? 'Terminé' : 'Erreur'}
                        </span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-1">
                          {onRerun && (
                            <button
                              onClick={() => onRerun({ url: entry.apollo_url, max_leads: entry.max_leads, skip_gpt: entry.skip_gpt })}
                              className="p-1.5 rounded-md transition-colors"
                              style={{ color: 'var(--th-purple)', background: 'rgba(155,107,255,0.08)', border: 'none', cursor: 'pointer' }}
                              title="Relancer avec les mêmes paramètres"
                            >
                              <RotateCcw className="w-3.5 h-3.5" />
                            </button>
                          )}
                          {entry.status === 'done' && entry.csv_available && (
                            <>
                              <button
                                onClick={() => handleView(entry)}
                                className="p-1.5 rounded-md transition-colors"
                                style={{ color: 'var(--th-primary)', background: 'var(--th-primary-soft)', border: 'none', cursor: 'pointer' }}
                                title="Voir les résultats"
                              >
                                <Eye className="w-3.5 h-3.5" />
                              </button>
                              <a
                                href={getDownloadUrl(entry.job_id)}
                                download
                                className="p-1.5 rounded-md transition-colors inline-flex"
                                style={{ color: 'var(--th-success)', background: 'var(--th-success-soft)', textDecoration: 'none' }}
                                title="Télécharger CSV"
                              >
                                <Download className="w-3.5 h-3.5" />
                              </a>
                              <a
                                href={`${getDownloadUrl(entry.job_id)}?format=json`}
                                download
                                className="p-1.5 rounded-md transition-colors inline-flex"
                                style={{ color: 'var(--th-purple)', background: 'rgba(155,107,255,0.08)', textDecoration: 'none' }}
                                title="Télécharger JSON"
                              >
                                <FileJson className="w-3.5 h-3.5" />
                              </a>
                            </>
                          )}
                          {entry.status === 'done' && !entry.csv_available && (
                            <span className="text-xs" style={{ color: 'var(--th-text-ghost)' }} title="CSV supprimé">
                              Fichier absent
                            </span>
                          )}
                          {entry.status === 'error' && entry.error && (
                            <span className="text-xs max-w-[120px] truncate" style={{ color: 'var(--th-error)' }} title={entry.error}>
                              {entry.error}
                            </span>
                          )}
                          <button
                            onClick={() => handleDelete(entry.job_id)}
                            className="p-1.5 rounded-md transition-colors ml-1"
                            style={{ color: 'var(--th-text-ghost)', background: 'none', border: 'none', cursor: 'pointer' }}
                            title="Supprimer"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )})()}
    </div>
  )
}
