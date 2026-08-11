import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { ArrowLeft, Database, Rocket, Trash2, Loader2, Users, Zap, ChevronDown, ChevronUp } from 'lucide-react'
import { getPools, getPoolLeads, deletePool, type LeadPool, type PoolLead } from '@/lib/api'
import { LeadDetailModal } from './LeadDetailModal'

interface Props {
  onBack: () => void
  onEnrichStarted?: (jobId: string) => void
}

function truncateUrl(url: string, max = 50): string {
  const clean = url.replace(/^https?:\/\//, '').replace(/#.*$/, '')
  return clean.length > max ? clean.slice(0, max) + '...' : clean
}

// ── Main Component ───────────────────────────────────────────────────────────

export function LeadPools({ onBack, onEnrichStarted }: Props) {
  const [pools, setPools] = useState<LeadPool[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedPool, setExpandedPool] = useState<string | null>(null)
  const [poolLeads, setPoolLeads] = useState<PoolLead[]>([])
  const [leadsLoading, setLeadsLoading] = useState(false)
  const [enrichBatchSize, setEnrichBatchSize] = useState(10)
  const [enrichInstructions, setEnrichInstructions] = useState('')
  const [enrichingPool, setEnrichingPool] = useState<string | null>(null)
  const [selectedLead, setSelectedLead] = useState<PoolLead | null>(null)

  const fetchPools = () => {
    setLoading(true)
    getPools()
      .then(setPools)
      .catch(() => toast.error('Impossible de charger les pools'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchPools() }, [])

  const handleExpand = async (poolId: string) => {
    if (expandedPool === poolId) {
      setExpandedPool(null)
      return
    }
    setExpandedPool(poolId)
    setLeadsLoading(true)
    try {
      const leads = await getPoolLeads(poolId, false, false, 50)
      setPoolLeads(leads)
    } catch {
      toast.error('Impossible de charger les leads')
    } finally { setLeadsLoading(false) }
  }

  const handleEnrich = async (poolId: string) => {
    setEnrichingPool(poolId)
    try {
      const res = await fetch('/api/enrich', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pool_id: poolId,
          batch_size: enrichBatchSize,
          enrich_instructions: enrichInstructions.trim(),
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Erreur inconnue' }))
        toast.error(err.detail || 'Impossible de lancer l\'enrichissement')
        fetchPools()
        return
      }
      const { job_id } = await res.json()
      toast.success(`Enrichissement lancé — ${enrichBatchSize} leads`)
      onEnrichStarted?.(job_id)
    } catch (err) {
      toast.error('Impossible de lancer l\'enrichissement', {
        description: err instanceof Error ? err.message : '',
      })
    } finally { setEnrichingPool(null) }
  }

  const handleDelete = async (poolId: string) => {
    if (!confirm('Supprimer ce pool et tous ses leads ?')) return
    try {
      await deletePool(poolId)
      setPools(prev => prev.filter(p => p.pool_id !== poolId))
      if (expandedPool === poolId) setExpandedPool(null)
    } catch {
      toast.error('Erreur lors de la suppression')
    }
  }

  return (
    <div className="w-full max-w-3xl mx-auto space-y-6">
      {/* Lead detail modal */}
      {selectedLead && (
        <LeadDetailModal lead={selectedLead} onClose={() => setSelectedLead(null)} />
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-sm transition-colors"
          style={{ color: 'var(--th-text-tertiary)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h2 className="text-lg font-semibold" style={{ color: 'var(--th-text-primary)' }}>
          Lead Pools
        </h2>
        <span className="text-xs font-medium px-2 py-0.5 rounded-full"
          style={{ color: 'var(--th-text-quaternary)', background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)' }}>
          {pools.length} pool{pools.length !== 1 ? 's' : ''}
        </span>
      </div>

      <p className="text-sm" style={{ color: 'var(--th-text-muted)' }}>
        Scrapez des milliers de prospects en une fois, puis enrichissez-les par lots de 10, 20 ou 50 pour contrôler les coûts API.
      </p>

      {loading && (
        <div className="flex items-center justify-center py-16 gap-3" style={{ color: 'var(--th-text-muted)' }}>
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Chargement...</span>
        </div>
      )}

      {!loading && pools.length === 0 && (
        <div className="glass-card p-10 text-center space-y-3">
          <Database className="w-12 h-12 mx-auto" style={{ color: 'var(--th-text-ghost)' }} />
          <p className="text-sm" style={{ color: 'var(--th-text-muted)' }}>Aucun pool de leads</p>
          <p className="text-xs" style={{ color: 'var(--th-text-faint)' }}>
            Lancez un scraping depuis le formulaire principal en mode "Scrape uniquement" pour créer un pool.
          </p>
        </div>
      )}

      {!loading && pools.map(pool => {
        const isExpanded = expandedPool === pool.pool_id
        const unenriched = pool.hit_leads - pool.enriched_leads
        const progressPct = pool.hit_leads > 0 ? Math.round((pool.enriched_leads / pool.hit_leads) * 100) : 0

        return (
          <div key={pool.pool_id} className="glass-card overflow-hidden">
            {/* Pool header */}
            <div
              className="flex items-center justify-between p-5 cursor-pointer row-hoverable"
              onClick={() => handleExpand(pool.pool_id)}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <Database className="w-4 h-4" style={{ color: 'var(--th-primary)' }} />
                  <span className="font-semibold text-sm" style={{ color: 'var(--th-text-primary)' }}>{pool.name}</span>
                </div>
                <p className="text-xs font-mono truncate" style={{ color: 'var(--th-text-quaternary)' }}>
                  {truncateUrl(pool.apollo_url)}
                </p>
                <div className="flex items-center gap-4 mt-2">
                  <span className="inline-flex items-center gap-1 text-xs" style={{ color: 'var(--th-text-muted)' }}>
                    <Users className="w-3 h-3" /> {pool.total_leads} leads
                  </span>
                  <span className="inline-flex items-center gap-1 text-xs" style={{ color: 'var(--th-success)' }}>
                    <Zap className="w-3 h-3" /> {pool.hit_leads} hits
                  </span>
                  <span className="text-xs" style={{ color: 'var(--th-text-faint)' }}>
                    {pool.enriched_leads}/{pool.hit_leads} enrichis ({progressPct}%)
                  </span>
                </div>
                <div className="mt-2 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--th-border-default)', maxWidth: 200 }}>
                  <div className="h-full rounded-full" style={{ width: `${progressPct}%`, background: 'linear-gradient(90deg, #4d9fff, #34d399)' }} />
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0 ml-4">
                {isExpanded ? <ChevronUp className="w-4 h-4" style={{ color: 'var(--th-text-muted)' }} /> : <ChevronDown className="w-4 h-4" style={{ color: 'var(--th-text-muted)' }} />}
              </div>
            </div>

            {/* Expanded content */}
            {isExpanded && (
              <div style={{ borderTop: '1px solid var(--th-border-subtle)' }}>
                {/* Enrich controls */}
                {unenriched > 0 && (
                  <div className="p-5 space-y-3" style={{ background: 'var(--th-surface-hover)' }}>
                    <div className="flex items-center gap-4 flex-wrap">
                    <span className="text-sm font-medium" style={{ color: 'var(--th-text-secondary)' }}>
                      Enrichir le prochain lot :
                    </span>
                    <div className="flex items-center gap-2">
                      {[10, 25, 50, 100].map(n => (
                        <button
                          key={n}
                          onClick={(e) => { e.stopPropagation(); setEnrichBatchSize(n) }}
                          className="px-3 py-1 rounded-md text-xs font-medium transition-all"
                          style={enrichBatchSize === n ? {
                            background: 'var(--th-primary-soft)', color: 'var(--th-primary)',
                            border: '1px solid var(--th-primary-border)', cursor: 'pointer', fontFamily: 'inherit',
                          } : {
                            color: 'var(--th-text-quaternary)', background: 'var(--th-glass-inset)',
                            border: '1px solid var(--th-glass-sm-border)', cursor: 'pointer', fontFamily: 'inherit',
                          }}
                        >
                          {n}
                        </button>
                      ))}
                    </div>
                    <span className="text-xs" style={{ color: 'var(--th-text-faint)' }}>
                      sur {unenriched} restants
                    </span>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleEnrich(pool.pool_id) }}
                      disabled={enrichingPool === pool.pool_id}
                      className="btn-grad flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white"
                      style={{ opacity: enrichingPool === pool.pool_id ? 0.4 : 1, cursor: enrichingPool === pool.pool_id ? 'not-allowed' : 'pointer', border: 'none', fontFamily: 'inherit' }}
                    >
                      {enrichingPool === pool.pool_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Rocket className="w-3.5 h-3.5" />}
                      Enrichir {Math.min(enrichBatchSize, unenriched)} leads
                    </button>
                    </div>
                    <div onClick={e => e.stopPropagation()}>
                      <label className="block text-xs mb-1" style={{ color: 'var(--th-text-muted)' }}>
                        Instructions de recherche (optionnel) — orientent la collecte de preuves
                        et la rédaction des angles
                      </label>
                      <textarea
                        value={enrichInstructions}
                        onChange={e => setEnrichInstructions(e.target.value)}
                        rows={2}
                        placeholder="Ex. : cibler les entreprises qui recrutent au marketing…"
                        className="surface-input w-full"
                        style={{ padding: 8, fontSize: 13, borderRadius: 8, resize: 'vertical' }}
                      />
                    </div>
                  </div>
                )}

                {unenriched === 0 && pool.hit_leads > 0 && (
                  <div className="p-5 flex items-center gap-2" style={{ background: 'var(--th-success-soft)' }}>
                    <Zap className="w-4 h-4" style={{ color: 'var(--th-success)' }} />
                    <span className="text-sm font-medium" style={{ color: 'var(--th-success)' }}>
                      Tous les leads hit sont enrichis !
                    </span>
                  </div>
                )}

                {/* Lead table */}
                <div className="overflow-x-auto">
                  {leadsLoading ? (
                    <div className="flex items-center justify-center py-8 gap-2" style={{ color: 'var(--th-text-muted)' }}>
                      <Loader2 className="w-4 h-4 animate-spin" /> Chargement...
                    </div>
                  ) : (
                    <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid var(--th-border-default)', background: 'var(--th-surface-hover)' }}>
                          {['Nom', 'Entreprise', 'Email', 'Score', 'Hit', 'Enrichi'].map(h => (
                            <th key={h} className="text-left px-4 py-2 text-xs font-semibold" style={{ color: 'var(--th-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {poolLeads.slice(0, 50).map(lead => (
                          <tr
                            key={lead.id}
                            className="row-hoverable cursor-pointer"
                            style={{ borderBottom: '1px solid var(--th-border-subtle)' }}
                            onClick={() => setSelectedLead(lead)}
                          >
                            <td className="px-4 py-2 font-medium" style={{ color: 'var(--th-primary)' }}>
                              {[lead.first_name, lead.last_name].filter(Boolean).join(' ') || '—'}
                            </td>
                            <td className="px-4 py-2" style={{ color: 'var(--th-text-tertiary)' }}>{lead.company || '—'}</td>
                            <td className="px-4 py-2 font-mono text-xs" style={{ color: 'var(--th-primary)' }}>{lead.email || '—'}</td>
                            <td className="px-4 py-2 font-mono text-xs" style={{ color: 'var(--th-text-tertiary)' }}>{lead.hit_score ?? 0}</td>
                            <td className="px-4 py-2">
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                                style={lead.is_hit ? { background: 'var(--th-success-soft)', color: 'var(--th-success)' } : { background: 'var(--th-glass-inset)', color: 'var(--th-text-muted)' }}>
                                {lead.is_hit ? '✓' : '—'}
                              </span>
                            </td>
                            <td className="px-4 py-2">
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                                style={lead.enriched ? { background: 'var(--th-primary-soft)', color: 'var(--th-primary)' } : { background: 'var(--th-glass-inset)', color: 'var(--th-text-ghost)' }}>
                                {lead.enriched ? '✓ Enrichi' : 'En attente'}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {poolLeads.length > 50 && (
                    <p className="text-xs text-center py-2" style={{ color: 'var(--th-text-faint)' }}>
                      ... et {poolLeads.length - 50} autres leads
                    </p>
                  )}
                </div>

                {/* Delete */}
                <div className="p-4 flex justify-end" style={{ borderTop: '1px solid var(--th-border-subtle)' }}>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDelete(pool.pool_id) }}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
                    style={{ color: 'var(--th-error)', background: 'var(--th-error-soft)', border: '1px solid var(--th-error-border)', cursor: 'pointer', fontFamily: 'inherit' }}
                  >
                    <Trash2 className="w-3 h-3" />
                    Supprimer le pool
                  </button>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
