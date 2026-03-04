import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { Download, Eye, Trash2, AlertCircle, Clock, ExternalLink, ArrowLeft, Loader2 } from 'lucide-react'
import { getHistory, getHistoryLeads, deleteHistoryEntry, getDownloadUrl, type HistoryEntry, type Lead, type JobResult } from '@/lib/api'
import { StatsBar } from './StatsBar'
import { ResultsTable } from './ResultsTable'

interface Props {
  onBack: () => void
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
    + ' ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

function truncateUrl(url: string, max = 50): string {
  // Remove protocol + hash part, keep the path
  const clean = url.replace(/^https?:\/\//, '').replace(/#.*$/, '')
  return clean.length > max ? clean.slice(0, max) + '...' : clean
}

export function History({ onBack }: Props) {
  const [entries, setEntries] = useState<HistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Detail view state
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

  // Detail view — reuse StatsBar + ResultsTable
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
      },
      leads: viewLeads ?? [],
    }

    return (
      <div className="space-y-6">
        <button
          onClick={() => { setViewEntry(null); setViewLeads(null) }}
          className="flex items-center gap-2 text-sm transition-colors"
          style={{ color: 'rgba(226,232,248,0.5)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
        >
          <ArrowLeft className="w-4 h-4" />
          Retour à l'historique
        </button>

        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-base font-semibold" style={{ color: 'rgba(226,232,248,0.6)' }}>
            Pipeline du {formatDate(viewEntry.started_at)}
          </h2>
          <span
            className="text-xs px-2 py-0.5 rounded-full font-mono"
            style={{ color: 'rgba(226,232,248,0.3)', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}
          >
            {viewEntry.job_id.slice(0, 8)}
          </span>
        </div>

        {viewLoading ? (
          <div className="flex items-center justify-center py-16 gap-3" style={{ color: 'rgba(226,232,248,0.3)' }}>
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
            style={{ color: 'rgba(226,232,248,0.5)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <h2 className="text-lg font-semibold" style={{ color: '#e2e8f8', letterSpacing: '-0.01em' }}>
            Historique des pipelines
          </h2>
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-full"
            style={{ color: 'rgba(226,232,248,0.4)', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}
          >
            {entries.length} run{entries.length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-16 gap-3" style={{ color: 'rgba(226,232,248,0.3)' }}>
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Chargement...</span>
        </div>
      )}

      {error && (
        <div className="glass-card p-6 text-center space-y-2">
          <AlertCircle className="w-6 h-6 mx-auto" style={{ color: '#ef4444' }} />
          <p className="text-sm" style={{ color: 'rgba(226,232,248,0.5)' }}>{error}</p>
        </div>
      )}

      {!loading && !error && entries.length === 0 && (
        <div className="glass-card p-10 text-center space-y-3">
          <Clock className="w-8 h-8 mx-auto" style={{ color: 'rgba(226,232,248,0.15)' }} />
          <p className="text-sm" style={{ color: 'rgba(226,232,248,0.3)' }}>Aucun pipeline exécuté pour l'instant</p>
          <p className="text-xs" style={{ color: 'rgba(226,232,248,0.2)' }}>Lancez un pipeline depuis l'accueil pour le voir apparaître ici.</p>
        </div>
      )}

      {!loading && entries.length > 0 && (
        <div className="glass-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}>
                  {['Date', 'URL Apollo', 'Leads', 'Hits', 'Score moy.', 'Statut', 'Actions'].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold whitespace-nowrap" style={{ color: 'rgba(226,232,248,0.3)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {entries.map(entry => {
                  const hitRate = entry.total_leads > 0 ? Math.round((entry.hit_leads / entry.total_leads) * 100) : 0
                  return (
                    <tr
                      key={entry.job_id}
                      className="transition-colors"
                      style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}
                      onMouseOver={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.025)')}
                      onMouseOut={e => (e.currentTarget.style.background = 'transparent')}
                    >
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="font-medium" style={{ color: '#e2e8f8' }}>{formatDate(entry.started_at)}</span>
                        {entry.finished_at && (
                          <span className="block text-xs mt-0.5" style={{ color: 'rgba(226,232,248,0.25)' }}>
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
                        <span className="text-xs font-mono block truncate" style={{ color: 'rgba(226,232,248,0.4)' }} title={entry.apollo_url}>
                          {truncateUrl(entry.apollo_url)}
                        </span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="font-mono font-medium" style={{ color: '#e2e8f8' }}>{entry.total_leads}</span>
                        <span className="text-xs ml-1" style={{ color: 'rgba(226,232,248,0.25)' }}>/ {entry.max_leads}</span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="font-mono" style={{ color: '#34d399' }}>{entry.hit_leads}</span>
                        <span className="text-xs ml-1" style={{ color: 'rgba(226,232,248,0.25)' }}>({hitRate}%)</span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <div className="w-10 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
                            <div
                              className="h-full rounded-full"
                              style={{ width: `${entry.avg_score}%`, background: 'linear-gradient(90deg, #4d9fff, #34d399)' }}
                            />
                          </div>
                          <span className="font-mono text-xs" style={{ color: 'rgba(226,232,248,0.5)' }}>{entry.avg_score}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                          style={entry.status === 'done'
                            ? { background: 'rgba(52,211,153,0.1)', color: '#34d399', border: '1px solid rgba(52,211,153,0.2)' }
                            : { background: 'rgba(239,68,68,0.1)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.2)' }
                          }
                        >
                          {entry.status === 'done' ? 'Terminé' : 'Erreur'}
                        </span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-1">
                          {entry.status === 'done' && entry.csv_available && (
                            <>
                              <button
                                onClick={() => handleView(entry)}
                                className="p-1.5 rounded-md transition-colors"
                                style={{ color: '#4d9fff', background: 'rgba(77,159,255,0.08)', border: 'none', cursor: 'pointer' }}
                                title="Voir les résultats"
                              >
                                <Eye className="w-3.5 h-3.5" />
                              </button>
                              <a
                                href={getDownloadUrl(entry.job_id)}
                                download
                                className="p-1.5 rounded-md transition-colors inline-flex"
                                style={{ color: '#34d399', background: 'rgba(52,211,153,0.08)', textDecoration: 'none' }}
                                title="Télécharger CSV"
                              >
                                <Download className="w-3.5 h-3.5" />
                              </a>
                            </>
                          )}
                          {entry.status === 'done' && !entry.csv_available && (
                            <span className="text-xs" style={{ color: 'rgba(226,232,248,0.2)' }} title="CSV supprimé">
                              Fichier absent
                            </span>
                          )}
                          {entry.status === 'error' && entry.error && (
                            <span className="text-xs max-w-[120px] truncate" style={{ color: 'rgba(239,68,68,0.6)' }} title={entry.error}>
                              {entry.error}
                            </span>
                          )}
                          <button
                            onClick={() => handleDelete(entry.job_id)}
                            className="p-1.5 rounded-md transition-colors ml-1"
                            style={{ color: 'rgba(226,232,248,0.2)', background: 'none', border: 'none', cursor: 'pointer' }}
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
      )}
    </div>
  )
}
