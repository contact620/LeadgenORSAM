import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { ArrowLeft, Bookmark, Rocket, Trash2, Plus, Loader2 } from 'lucide-react'
import { getTemplates, createTemplate, deleteTemplate, runTemplate, type Template } from '@/lib/api'

interface Props {
  onBack: () => void
  onRun?: (jobId: string) => void
}

function truncateUrl(url: string, max = 60): string {
  const clean = url.replace(/^https?:\/\//, '').replace(/#.*$/, '')
  return clean.length > max ? clean.slice(0, max) + '...' : clean
}

export function Templates({ onBack, onRun }: Props) {
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newUrl, setNewUrl] = useState('')
  const [newMaxLeads, setNewMaxLeads] = useState(200)
  const [newSkipGpt, setNewSkipGpt] = useState(false)
  const [creating, setCreating] = useState(false)
  const [runningId, setRunningId] = useState<string | null>(null)

  const fetchTemplates = () => {
    setLoading(true)
    getTemplates()
      .then(setTemplates)
      .catch(() => toast.error('Impossible de charger les templates'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchTemplates() }, [])

  const handleCreate = async () => {
    if (!newName.trim() || !newUrl.trim()) return
    setCreating(true)
    try {
      await createTemplate({ name: newName.trim(), apollo_url: newUrl.trim(), max_leads: newMaxLeads, skip_gpt: newSkipGpt })
      setShowCreate(false)
      setNewName('')
      setNewUrl('')
      setNewMaxLeads(200)
      setNewSkipGpt(false)
      fetchTemplates()
      toast.success('Template créé')
    } catch {
      toast.error('Erreur lors de la création')
    } finally { setCreating(false) }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Supprimer ce template ?')) return
    try {
      await deleteTemplate(id)
      setTemplates(prev => prev.filter(t => t.id !== id))
    } catch {
      toast.error('Erreur lors de la suppression')
    }
  }

  const handleRun = async (id: string) => {
    setRunningId(id)
    try {
      const { job_id } = await runTemplate(id)
      toast.success('Pipeline lancé depuis le template')
      onRun?.(job_id)
    } catch {
      toast.error('Impossible de lancer le pipeline')
    } finally { setRunningId(null) }
  }

  return (
    <div className="w-full max-w-2xl mx-auto space-y-6">
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
            Templates
          </h2>
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-full"
            style={{ color: 'var(--th-text-quaternary)', background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)' }}
          >
            {templates.length}
          </span>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-all"
          style={{ color: 'var(--th-primary)', background: 'var(--th-primary-soft)', border: '1px solid var(--th-primary-border)', cursor: 'pointer', fontFamily: 'inherit' }}
        >
          <Plus className="w-3.5 h-3.5" />
          Créer
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="glass-card" style={{ padding: '20px 24px' }}>
          <p className="text-sm font-semibold mb-4" style={{ color: 'var(--th-text-primary)' }}>Nouveau template</p>
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Nom</label>
              <input
                value={newName} onChange={e => setNewName(e.target.value)}
                placeholder="Ex: Leads SaaS France"
                className="surface-input w-full"
                style={{ padding: '8px 12px', fontSize: 13 }}
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: 'var(--th-text-tertiary)' }}>URL Apollo</label>
              <textarea
                value={newUrl} onChange={e => setNewUrl(e.target.value)}
                placeholder="https://app.apollo.io/#/people?..."
                rows={2}
                className="surface-input w-full"
                style={{ padding: '8px 12px', fontSize: 12, resize: 'none' }}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Leads max</label>
                <input
                  type="number" min={1} max={5000} value={newMaxLeads}
                  onChange={e => setNewMaxLeads(Number(e.target.value))}
                  className="surface-input w-full"
                  style={{ padding: '8px 12px', fontSize: 13 }}
                />
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 text-xs" style={{ color: 'var(--th-text-tertiary)' }}>
                  <input type="checkbox" checked={newSkipGpt} onChange={e => setNewSkipGpt(e.target.checked)} />
                  Skip enrichissement IA
                </label>
              </div>
            </div>
            <button
              onClick={handleCreate}
              disabled={creating || !newName.trim() || !newUrl.trim()}
              className="btn-grad flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white"
              style={{ opacity: (creating || !newName.trim() || !newUrl.trim()) ? 0.4 : 1, cursor: (creating || !newName.trim() || !newUrl.trim()) ? 'not-allowed' : 'pointer', border: 'none', fontFamily: 'inherit' }}
            >
              {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
              Créer le template
            </button>
          </div>
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-16 gap-3" style={{ color: 'var(--th-text-muted)' }}>
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Chargement...</span>
        </div>
      )}

      {!loading && templates.length === 0 && !showCreate && (
        <div className="glass-card p-10 text-center space-y-3">
          <Bookmark className="w-12 h-12 mx-auto" style={{ color: 'var(--th-text-ghost)' }} />
          <p className="text-sm" style={{ color: 'var(--th-text-muted)' }}>Aucun template sauvegardé</p>
          <p className="text-xs" style={{ color: 'var(--th-text-faint)' }}>Créez un template pour relancer facilement vos recherches récurrentes.</p>
          <button
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-2 text-sm font-medium mt-2 px-4 py-2 rounded-lg transition-all"
            style={{ color: 'var(--th-primary)', background: 'var(--th-primary-soft)', border: '1px solid var(--th-primary-border)', cursor: 'pointer', fontFamily: 'inherit' }}
          >
            <Plus className="w-3.5 h-3.5" />
            Créer un template
          </button>
        </div>
      )}

      {/* Templates list */}
      {!loading && templates.length > 0 && (
        <div className="space-y-3">
          {templates.map(tpl => (
            <div key={tpl.id} className="glass-card-sm p-4 flex items-center justify-between gap-4 row-hoverable">
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-sm" style={{ color: 'var(--th-text-primary)' }}>{tpl.name}</p>
                <p className="text-xs font-mono truncate mt-0.5" style={{ color: 'var(--th-text-quaternary)' }}>
                  {truncateUrl(tpl.apollo_url)}
                </p>
                <div className="flex items-center gap-3 mt-1.5">
                  <span className="text-xs" style={{ color: 'var(--th-text-faint)' }}>{tpl.max_leads} leads max</span>
                  <span className="text-xs" style={{ color: 'var(--th-text-faint)' }}>{tpl.run_count} run{tpl.run_count !== 1 ? 's' : ''}</span>
                  {tpl.last_used_at && (
                    <span className="text-xs" style={{ color: 'var(--th-text-ghost)' }}>
                      Dernier : {new Date(tpl.last_used_at).toLocaleDateString('fr-FR')}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => handleRun(tpl.id)}
                  disabled={runningId === tpl.id}
                  className="p-2 rounded-lg transition-colors"
                  style={{ color: 'var(--th-success)', background: 'var(--th-success-soft)', border: 'none', cursor: 'pointer' }}
                  title="Lancer le pipeline"
                >
                  {runningId === tpl.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" />}
                </button>
                <button
                  onClick={() => handleDelete(tpl.id)}
                  className="p-2 rounded-lg transition-colors"
                  style={{ color: 'var(--th-text-ghost)', background: 'none', border: 'none', cursor: 'pointer' }}
                  title="Supprimer"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
