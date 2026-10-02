import { useState, useEffect, useRef, useCallback } from 'react'
import { toast } from 'sonner'
import {
  KeyRound, CheckCircle2, XCircle, Eye, EyeOff,
  Upload, Save, RefreshCw, Cookie, SlidersHorizontal,
  ArrowLeft, AlertCircle, Gauge, ShieldOff, Trash2, FileUp,
} from 'lucide-react'
import {
  getConfig, saveConfig, uploadCookies, validateApiKey, type ConfigStatus,
  getSuppressionList, importSuppressionCsv, deleteSuppressionEntry, type SuppressionEntry,
} from '@/lib/api'

interface Props {
  onBack: () => void
  onConfigChange?: (config: ConfigStatus) => void
}

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full"
      style={ok ? {
        background: 'var(--th-success-soft)',
        color: 'var(--th-success)',
        border: '1px solid var(--th-success-border)',
      } : {
        background: 'var(--th-error-soft)',
        color: 'var(--th-error)',
        border: '1px solid var(--th-error-border)',
      }}
    >
      {ok ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
      {label}
    </span>
  )
}

function SectionCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="glass-card">
      <div
        className="flex items-center gap-2.5 px-6 py-4"
        style={{ borderBottom: '1px solid var(--th-border-default)' }}
      >
        <span style={{ color: 'var(--th-primary)' }}>{icon}</span>
        <h2 className="font-semibold text-sm" style={{ color: 'var(--th-text-primary)' }}>{title}</h2>
      </div>
      <div style={{ padding: '20px 24px' }}>{children}</div>
    </div>
  )
}

const PROVIDER_QUOTA_LABEL: Record<string, string> = {
  prospeo: 'Prospeo',
  hunter: 'Hunter.io',
  getprospect: 'GetProspect (recherche)',
  getprospect_verify: 'GetProspect (vérification)',
}

function QuotaBar({ label, quota }: { label: string; quota: ConfigStatus['quotas'][string] }) {
  const pct = quota.allocation > 0 ? Math.min(100, Math.round((quota.remaining / quota.allocation) * 100)) : 0
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span style={{ color: 'var(--th-text-tertiary)' }}>{label}</span>
        <span className="font-mono text-xs" style={{ color: 'var(--th-text-muted)' }}>
          {Math.round(quota.remaining)} / {Math.round(quota.allocation)}
        </span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--th-border-default)' }}>
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: pct > 20 ? 'var(--th-success)' : 'var(--th-error)' }} />
      </div>
      {quota.reset_date && (
        <p className="text-xs" style={{ color: 'var(--th-text-faint)' }}>Réinitialisation : {quota.reset_date}</p>
      )}
    </div>
  )
}

interface CookiePanelProps {
  service: 'apollo'
  label: string
  isPresent: boolean
  onUploaded: () => void
}

function CookiePanel({ service, label, isPresent, onUploaded }: CookiePanelProps) {
  const [mode, setMode] = useState<'drop' | 'paste'>('drop')
  const [text, setText] = useState('')
  const [dragging, setDragging] = useState(false)
  const [status, setStatus] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const submit = useCallback(async (json: string) => {
    setLoading(true); setStatus(null)
    try {
      const res = await uploadCookies(service, json)
      setStatus({ type: 'success', msg: `${res.count} cookies importés` })
      onUploaded()
    } catch (e: unknown) {
      setStatus({ type: 'error', msg: e instanceof Error ? e.message : 'Erreur inconnue' })
    } finally { setLoading(false) }
  }, [service, onUploaded])

  const handleFile = useCallback((file: File) => {
    const reader = new FileReader()
    reader.onload = e => submit(e.target?.result as string)
    reader.readAsText(file)
  }, [submit])

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium" style={{ color: 'var(--th-text-secondary)' }}>{label}</span>
        <StatusBadge ok={isPresent} label={isPresent ? 'Présent' : 'Absent'} />
      </div>

      <div className="flex gap-1 p-1 rounded-lg w-fit text-xs" style={{ background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)' }}>
        {(['drop', 'paste'] as const).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className="px-3 py-1 rounded-md font-medium transition-all"
            style={mode === m ? { background: 'var(--th-border-strong)', color: 'var(--th-text-primary)', border: 'none', cursor: 'pointer', fontFamily: 'inherit' } : { color: 'var(--th-text-quaternary)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
          >
            {m === 'drop' ? 'Upload fichier' : 'Coller JSON'}
          </button>
        ))}
      </div>

      {mode === 'drop' && (
        <div
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
          className="relative flex flex-col items-center justify-center gap-2 rounded-xl p-6 cursor-pointer transition-all text-center"
          style={dragging ? {
            border: '2px dashed var(--th-primary)',
            background: 'var(--th-primary-soft)',
          } : {
            border: '2px dashed var(--th-border-strong)',
            background: 'var(--th-surface-hover)',
          }}
        >
          <Upload className="w-5 h-5" style={{ color: 'var(--th-text-faint)' }} />
          <p className="text-sm" style={{ color: 'var(--th-text-quaternary)' }}>
            Glissez le fichier JSON ou <span style={{ color: 'var(--th-primary)', fontWeight: 500 }}>cliquez pour parcourir</span>
          </p>
          <p className="text-xs" style={{ color: 'var(--th-text-ghost)' }}>Export Cookie Editor (.json)</p>
          <input
            ref={fileRef} type="file" accept=".json,application/json" className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
          />
        </div>
      )}

      {mode === 'paste' && (
        <div className="space-y-2">
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder='[{"name": "cookie_name", "value": "...", ...}]'
            rows={6}
            className="surface-input w-full"
            style={{ padding: '10px 12px', fontSize: 12, resize: 'none' }}
          />
          <button
            onClick={() => submit(text.trim())}
            disabled={loading || !text.trim()}
            className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium btn-grad text-white"
            style={{ opacity: (loading || !text.trim()) ? 0.4 : 1, cursor: (loading || !text.trim()) ? 'not-allowed' : 'pointer', border: 'none', fontFamily: 'inherit' }}
          >
            {loading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Valider
          </button>
        </div>
      )}

      {loading && mode === 'drop' && (
        <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--th-primary)' }}>
          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          Import en cours…
        </div>
      )}

      {status && (
        <div
          className="flex items-center gap-2 text-sm rounded-lg px-3 py-2"
          style={status.type === 'success' ? {
            background: 'var(--th-success-soft)', color: 'var(--th-success)', border: '1px solid var(--th-success-border)',
          } : {
            background: 'var(--th-error-soft)', color: 'var(--th-error)', border: '1px solid var(--th-error-border)',
          }}
        >
          {status.type === 'success' ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <XCircle className="w-4 h-4 shrink-0" />}
          {status.msg}
        </div>
      )}
    </div>
  )
}

export function Settings({ onBack, onConfigChange }: Props) {
  const [config, setConfig] = useState<ConfigStatus | null>(null)
  const [keys, setKeys] = useState({ serper: '', anthropic: '', perplexity: '', hunter: '', prospeo: '', getprospect: '' })
  const [showKey, setShowKey] = useState({ serper: false, anthropic: false, perplexity: false, hunter: false, prospeo: false, getprospect: false })
  const [savingKeys, setSavingKeys] = useState(false)
  const [keysStatus, setKeysStatus] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [testingKey, setTestingKey] = useState(false)
  const [keyTest, setKeyTest] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [pipeline, setPipeline] = useState({ hitThreshold: 50, services: [] as string[] })
  const [newService, setNewService] = useState('')
  const [savingPipeline, setSavingPipeline] = useState(false)
  const [pipelineStatus, setPipelineStatus] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [suppression, setSuppression] = useState<SuppressionEntry[]>([])
  const [importingSuppression, setImportingSuppression] = useState(false)
  const suppressionFileRef = useRef<HTMLInputElement>(null)

  const refreshConfig = useCallback(() => {
    getConfig().then(c => { setConfig(c); setPipeline({ hitThreshold: c.hit_threshold, services: c.services || [] }); onConfigChange?.(c) }).catch(() => {
      toast.error('Impossible de rafraîchir la configuration')
    })
  }, [onConfigChange])

  const refreshSuppression = useCallback(() => {
    getSuppressionList().then(setSuppression).catch(() => {
      toast.error('Impossible de charger la liste de suppression')
    })
  }, [])

  useEffect(() => { refreshConfig() }, [refreshConfig])
  useEffect(() => { refreshSuppression() }, [refreshSuppression])

  const handleImportSuppression = async (file: File) => {
    setImportingSuppression(true)
    try {
      const report = await importSuppressionCsv(file)
      toast.success(`${report.imported} entrée(s) importée(s)${report.skipped ? `, ${report.skipped} ignorée(s)` : ''}`)
      refreshSuppression()
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Échec de l'import")
    } finally { setImportingSuppression(false) }
  }

  const handleDeleteSuppression = async (id: number) => {
    try {
      await deleteSuppressionEntry(id)
      setSuppression(prev => prev.filter(entry => entry.id !== id))
    } catch {
      toast.error("Échec de la suppression de l'entrée")
    }
  }

  const handleSaveKeys = async () => {
    setSavingKeys(true); setKeysStatus(null)
    try {
      await saveConfig({
        serper_api_key: keys.serper || undefined,
        anthropic_api_key: keys.anthropic || undefined,
        perplexity_api_key: keys.perplexity || undefined,
        hunter_api_key: keys.hunter || undefined,
        prospeo_api_key: keys.prospeo || undefined,
        getprospect_api_key: keys.getprospect || undefined,
      })
      setKeysStatus({ type: 'success', msg: 'Clés sauvegardées' })
      setKeys({ serper: '', anthropic: '', perplexity: '', hunter: '', prospeo: '', getprospect: '' })
      refreshConfig()
    } catch (e: unknown) {
      setKeysStatus({ type: 'error', msg: e instanceof Error ? e.message : 'Erreur' })
    } finally { setSavingKeys(false) }
  }

  const handleTestKey = async (type: string, value: string) => {
    setTestingKey(true); setKeyTest(null)
    try {
      const res = await validateApiKey(type, value)
      setKeyTest(res.valid
        ? { type: 'success', msg: 'Clé acceptée — appel de test réussi' }
        : { type: 'error', msg: res.error ?? 'Clé refusée' })
    } catch (e: unknown) {
      setKeyTest({ type: 'error', msg: e instanceof Error ? e.message : 'Erreur' })
    } finally { setTestingKey(false) }
  }

  const handleSavePipeline = async () => {
    setSavingPipeline(true); setPipelineStatus(null)
    try {
      await saveConfig({ hit_threshold: pipeline.hitThreshold, services: pipeline.services })
      setPipelineStatus({ type: 'success', msg: 'Paramètres sauvegardés' })
      refreshConfig()
    } catch (e: unknown) {
      setPipelineStatus({ type: 'error', msg: e instanceof Error ? e.message : 'Erreur' })
    } finally { setSavingPipeline(false) }
  }

  const keyFields: { id: keyof typeof keys; label: string; required: boolean; configKey: keyof ConfigStatus; hint?: string }[] = [
    { id: 'serper',      label: 'SERPER_API_KEY',      required: true,  configKey: 'serper_api_key' },
    { id: 'anthropic',   label: 'ANTHROPIC_API_KEY',   required: true,  configKey: 'anthropic_api_key' },
    { id: 'perplexity',  label: 'PERPLEXITY_API_KEY',  required: false, configKey: 'perplexity_api_key', hint: 'Optionnel — enrichissement Perplexity Sonar ignoré si absent' },
    { id: 'hunter',      label: 'HUNTER_API_KEY',      required: false, configKey: 'hunter_api_key',    hint: 'Optionnel — vérification email Hunter.io ignorée si absent (~$0.01/vérif)' },
    { id: 'prospeo',     label: 'PROSPEO_API_KEY',     required: false, configKey: 'prospeo_api_key',     hint: 'Optionnel — 100 recherches/mois en plan gratuit' },
    { id: 'getprospect', label: 'GETPROSPECT_API_KEY', required: false, configKey: 'getprospect_api_key', hint: 'Optionnel — 50 emails + 100 vérifications/mois' },
  ]

  const actionBtnStyle = (disabled: boolean) => ({
    opacity: disabled ? 0.4 : 1,
    cursor: disabled ? 'not-allowed' as const : 'pointer' as const,
    border: 'none' as const,
    fontFamily: 'inherit',
  })

  return (
    <div className="w-full max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-all"
          style={{ color: 'var(--th-text-quaternary)', border: '1px solid var(--th-border-medium)', background: 'var(--th-glass-inset)', cursor: 'pointer', fontFamily: 'inherit' }}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Retour
        </button>
        <div>
          <h1 className="text-xl font-bold" style={{ color: 'var(--th-text-primary)', letterSpacing: '-0.02em' }}>Paramètres</h1>
          <p className="text-xs" style={{ color: 'var(--th-text-muted)' }}>Configuration — clés API, cookies, pipeline</p>
        </div>
      </div>

      {/* Global status */}
      {config && (
        <div
          className="rounded-xl p-4 flex items-start gap-3"
          style={(!config.serper_api_key || !config.anthropic_api_key || !config.apollo_cookies) ? {
            background: 'var(--th-warning-soft)',
            border: '1px solid var(--th-warning-border)',
          } : {
            background: 'var(--th-success-soft)',
            border: '1px solid var(--th-success-border)',
          }}
        >
          {(!config.serper_api_key || !config.anthropic_api_key || !config.apollo_cookies) ? (
            <>
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" style={{ color: 'var(--th-warning)' }} />
              <div className="text-sm">
                <p className="font-medium mb-0.5" style={{ color: 'var(--th-warning-text)' }}>Configuration incomplète</p>
                <p className="text-xs" style={{ color: 'var(--th-warning-text)' }}>Complétez les champs requis ci-dessous pour activer le pipeline.</p>
              </div>
            </>
          ) : (
            <>
              <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" style={{ color: 'var(--th-success)' }} />
              <p className="text-sm font-medium" style={{ color: 'var(--th-success)' }}>Configuration complète — pipeline prêt</p>
            </>
          )}
        </div>
      )}

      {/* API Keys */}
      <SectionCard title="Clés API" icon={<KeyRound className="w-4 h-4" />}>
        <div className="space-y-5">
          {keyFields.map(({ id, label, required, configKey, hint }) => (
            <div key={id}>
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-medium" style={{ color: 'var(--th-text-tertiary)' }}>
                  {label}
                  {required && <span className="ml-1" style={{ color: 'var(--th-error)' }}>*</span>}
                </label>
                {config && <StatusBadge ok={Boolean(config[configKey])} label={Boolean(config[configKey]) ? 'Configuré' : 'Manquant'} />}
              </div>
              <div className="relative">
                <input
                  type={showKey[id] ? 'text' : 'password'}
                  value={keys[id]}
                  onChange={e => setKeys(prev => ({ ...prev, [id]: e.target.value }))}
                  placeholder={config?.[configKey] ? '••••••••••••••••  (déjà configuré)' : 'Entrez la clé…'}
                  className="surface-input w-full pr-10"
                  style={{ padding: '9px 12px', paddingRight: 40, fontSize: 13 }}
                />
                <button
                  type="button"
                  onClick={() => setShowKey(prev => ({ ...prev, [id]: !prev[id] }))}
                  className="absolute right-3 top-1/2 -translate-y-1/2"
                  style={{ color: 'var(--th-text-muted)', background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  {showKey[id] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
              {hint && <p className="mt-1 text-xs" style={{ color: 'var(--th-text-faint)' }}>{hint}</p>}

              {/* The Quotas panel below counts email-finder credits only;
                  nothing there says whether the AI key still works. The
                  Anthropic API publishes no credit-balance endpoint, so the
                  only honest answer is a real call — which is what
                  /api/config/validate-key already makes. */}
              {id === 'anthropic' && (
                <div className="mt-2 flex items-center gap-2 flex-wrap">
                  <button
                    type="button"
                    onClick={() => handleTestKey('anthropic', keys.anthropic)}
                    disabled={testingKey || !keys.anthropic}
                    title={keys.anthropic
                      ? 'Envoie un appel minimal à Claude avec cette clé'
                      : 'Collez la clé à tester dans le champ ci-dessus'}
                    className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium"
                    style={{
                      color: 'var(--th-primary)', background: 'var(--th-primary-soft)',
                      border: '1px solid var(--th-primary-border)', fontFamily: 'inherit',
                      opacity: (testingKey || !keys.anthropic) ? 0.4 : 1,
                      cursor: (testingKey || !keys.anthropic) ? 'not-allowed' : 'pointer',
                    }}
                  >
                    {testingKey ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Gauge className="w-3 h-3" />}
                    Tester la clé
                  </button>
                  {keyTest && (
                    <span
                      className="inline-flex items-center gap-1.5 text-xs"
                      style={{ color: keyTest.type === 'success' ? 'var(--th-success)' : 'var(--th-error)' }}
                    >
                      {keyTest.type === 'success'
                        ? <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                        : <XCircle className="w-3.5 h-3.5 shrink-0" />}
                      {keyTest.msg}
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}

          {keysStatus && (
            <div
              className="flex items-center gap-2 text-sm rounded-lg px-3 py-2"
              style={keysStatus.type === 'success' ? {
                background: 'var(--th-success-soft)', color: 'var(--th-success)', border: '1px solid var(--th-success-border)',
              } : {
                background: 'var(--th-error-soft)', color: 'var(--th-error)', border: '1px solid var(--th-error-border)',
              }}
            >
              {keysStatus.type === 'success' ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <XCircle className="w-4 h-4 shrink-0" />}
              {keysStatus.msg}
            </div>
          )}

          <button
            onClick={handleSaveKeys}
            disabled={savingKeys || Object.values(keys).every(v => !v)}
            className="btn-grad flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white"
            style={actionBtnStyle(savingKeys || Object.values(keys).every(v => !v))}
          >
            {savingKeys ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Sauvegarder les clés
          </button>
        </div>
      </SectionCard>

      {/* Quotas */}
      {config && config.quotas && Object.keys(config.quotas).length > 0 && (
        <SectionCard title="Quotas des outils email gratuits" icon={<Gauge className="w-4 h-4" />}>
          <div className="space-y-4">
            <p className="text-xs" style={{ color: 'var(--th-text-muted)' }}>
              Crédits restants sur l'allocation mensuelle de chaque fournisseur de la cascade email.
              Ces compteurs ne disent rien de la clé Anthropic : utilisez « Tester la clé » ci-dessus.
            </p>
            {Object.entries(config.quotas).map(([provider, quota]) => (
              <QuotaBar key={provider} label={PROVIDER_QUOTA_LABEL[provider] ?? provider} quota={quota} />
            ))}
          </div>
        </SectionCard>
      )}

      {/* Suppression list */}
      <SectionCard title="Liste de suppression" icon={<ShieldOff className="w-4 h-4" />}>
        <div className="space-y-4">
          <p className="text-xs" style={{ color: 'var(--th-text-muted)' }}>
            Clients existants et opt-out : ces leads ne sont jamais contactés, gratuit ou payant. Colonnes CSV : email, linkedin_url, domaine, motif.
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={() => suppressionFileRef.current?.click()}
              disabled={importingSuppression}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium"
              style={{
                color: 'var(--th-primary)', background: 'var(--th-primary-soft)', border: '1px solid var(--th-primary-border)',
                cursor: importingSuppression ? 'not-allowed' : 'pointer', fontFamily: 'inherit', opacity: importingSuppression ? 0.5 : 1,
              }}
            >
              {importingSuppression ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <FileUp className="w-3.5 h-3.5" />}
              Importer un CSV
            </button>
            <input
              ref={suppressionFileRef} type="file" accept=".csv,text/csv" className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) handleImportSuppression(f); e.target.value = '' }}
            />
            <span className="text-sm" style={{ color: 'var(--th-text-tertiary)' }}>
              {suppression.length} entrée{suppression.length !== 1 ? 's' : ''}
            </span>
          </div>

          {suppression.length > 0 && (
            <div className="max-h-64 overflow-y-auto rounded-lg" style={{ border: '1px solid var(--th-border-subtle)' }}>
              <table className="w-full text-xs">
                <tbody>
                  {suppression.map(entry => (
                    <tr key={entry.id} style={{ borderBottom: '1px solid var(--th-border-subtle)' }}>
                      <td className="px-3 py-2" style={{ color: 'var(--th-text-tertiary)' }}>
                        {entry.email || entry.linkedin_url || entry.domaine || '—'}
                      </td>
                      <td className="px-3 py-2" style={{ color: 'var(--th-text-muted)' }}>{entry.motif}</td>
                      <td className="px-3 py-2 text-right">
                        <button
                          onClick={() => handleDeleteSuppression(entry.id)}
                          style={{ color: 'var(--th-error)', background: 'none', border: 'none', cursor: 'pointer' }}
                          title="Supprimer"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </SectionCard>

      {/* Cookies */}
      <SectionCard title="Cookies de session" icon={<Cookie className="w-4 h-4" />}>
        <div className="space-y-6">
          <p className="text-xs" style={{ color: 'var(--th-text-muted)' }}>
            Exportez vos cookies depuis l'extension <strong style={{ color: 'var(--th-text-tertiary)' }}>Cookie Editor</strong> sur Apollo.io, puis importez-les ici.
          </p>
          <CookiePanel service="apollo" label="Apollo.io" isPresent={config?.apollo_cookies ?? false} onUploaded={refreshConfig} />
        </div>
      </SectionCard>

      {/* Services */}
      <SectionCard title="Services proposés" icon={<SlidersHorizontal className="w-4 h-4" />}>
        <div className="space-y-4">
          <p className="text-xs" style={{ color: 'var(--th-text-muted)' }}>
            Ajoutez les services que vous vendez. Lors du lancement d'un pipeline, vous pourrez cocher ceux pour lesquels vous cherchez des leads.
          </p>

          <div className="flex flex-wrap gap-2">
            {pipeline.services.map((svc, i) => (
              <span key={i} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm"
                style={{ background: 'var(--th-primary-soft)', color: 'var(--th-primary)', border: '1px solid var(--th-primary-border)' }}>
                {svc}
                <button
                  onClick={() => setPipeline(prev => ({ ...prev, services: prev.services.filter((_, j) => j !== i) }))}
                  style={{ color: 'var(--th-primary)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, lineHeight: 1 }}
                >×</button>
              </span>
            ))}
          </div>

          <div className="flex gap-2">
            <input
              type="text"
              value={newService}
              onChange={e => setNewService(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && newService.trim()) {
                  e.preventDefault()
                  setPipeline(prev => ({ ...prev, services: [...prev.services, newService.trim()] }))
                  setNewService('')
                }
              }}
              placeholder="Ex: Développement Web, SEO, Branding..."
              className="surface-input flex-1"
              style={{ padding: '8px 12px', fontSize: 13 }}
            />
            <button
              onClick={() => {
                if (newService.trim()) {
                  setPipeline(prev => ({ ...prev, services: [...prev.services, newService.trim()] }))
                  setNewService('')
                }
              }}
              className="px-3 py-1.5 rounded-lg text-sm font-medium"
              style={{ color: 'var(--th-primary)', background: 'var(--th-primary-soft)', border: '1px solid var(--th-primary-border)', cursor: 'pointer', fontFamily: 'inherit' }}
            >
              Ajouter
            </button>
          </div>

          <button
            onClick={handleSavePipeline}
            disabled={savingPipeline}
            className="btn-grad flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white mt-2"
            style={actionBtnStyle(savingPipeline)}
          >
            {savingPipeline ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Sauvegarder les services
          </button>
        </div>
      </SectionCard>

      {/* Pipeline params */}
      <SectionCard title="Paramètres du pipeline" icon={<SlidersHorizontal className="w-4 h-4" />}>
        <div className="space-y-4">
          <div className="max-w-xs">
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--th-text-tertiary)' }}>
              HIT_THRESHOLD
              <span className="ml-1 font-normal" style={{ color: 'var(--th-text-faint)' }}>(score minimum pour être un lead "hit")</span>
            </label>
            <input
              type="number" min={0} max={100}
              value={pipeline.hitThreshold}
              onChange={e => setPipeline(prev => ({ ...prev, hitThreshold: Number(e.target.value) }))}
              className="surface-input w-full"
              style={{ padding: '9px 12px', fontSize: 14 }}
            />
            <p className="mt-1 text-xs" style={{ color: 'var(--th-text-faint)' }}>0–100 · email=40pts, linkedin=30pts, phone=20pts, website=10pts</p>
          </div>
          <p className="text-xs" style={{ color: 'var(--th-text-faint)' }}>
            Le nombre de leads par run se configure dans les paramètres avancés du formulaire de lancement.
          </p>

          {pipelineStatus && (
            <div
              className="flex items-center gap-2 text-sm rounded-lg px-3 py-2"
              style={pipelineStatus.type === 'success' ? {
                background: 'var(--th-success-soft)', color: 'var(--th-success)', border: '1px solid var(--th-success-border)',
              } : {
                background: 'var(--th-error-soft)', color: 'var(--th-error)', border: '1px solid var(--th-error-border)',
              }}
            >
              {pipelineStatus.type === 'success' ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <XCircle className="w-4 h-4 shrink-0" />}
              {pipelineStatus.msg}
            </div>
          )}

          <button
            onClick={handleSavePipeline}
            disabled={savingPipeline}
            className="btn-grad flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white"
            style={actionBtnStyle(savingPipeline)}
          >
            {savingPipeline ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Sauvegarder
          </button>
        </div>
      </SectionCard>
    </div>
  )
}
