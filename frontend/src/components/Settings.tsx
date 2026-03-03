import { useState, useEffect, useRef, useCallback } from 'react'
import {
  KeyRound, CheckCircle2, XCircle, Eye, EyeOff,
  Upload, Save, RefreshCw, Cookie, SlidersHorizontal,
  ArrowLeft, AlertCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { getConfig, saveConfig, uploadCookies, type ConfigStatus } from '@/lib/api'

interface Props {
  onBack: () => void
  onConfigChange?: (config: ConfigStatus) => void
}

// ── Small reusable bits ────────────────────────────────────────────────────────

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full',
        ok
          ? 'bg-green-100 text-green-700'
          : 'bg-red-100 text-red-600',
      )}
    >
      {ok ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
      {label}
    </span>
  )
}

function SectionCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm">
      <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-100">
        <span className="text-blue-600">{icon}</span>
        <h2 className="font-semibold text-gray-900 text-sm">{title}</h2>
      </div>
      <div className="p-6">{children}</div>
    </div>
  )
}

// ── Cookie upload panel (shared for Apollo & LinkedIn) ─────────────────────────

interface CookiePanelProps {
  service: 'apollo' | 'linkedin'
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
    setLoading(true)
    setStatus(null)
    try {
      const res = await uploadCookies(service, json)
      setStatus({ type: 'success', msg: `${res.count} cookies importés` })
      onUploaded()
    } catch (e: unknown) {
      setStatus({ type: 'error', msg: e instanceof Error ? e.message : 'Erreur inconnue' })
    } finally {
      setLoading(false)
    }
  }, [service, onUploaded])

  const handleFile = useCallback((file: File) => {
    const reader = new FileReader()
    reader.onload = e => submit(e.target?.result as string)
    reader.readAsText(file)
  }, [submit])

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        <StatusBadge ok={isPresent} label={isPresent ? 'Présent' : 'Absent'} />
      </div>

      {/* Mode tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit text-xs">
        {(['drop', 'paste'] as const).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cn(
              'px-3 py-1 rounded-md font-medium transition-colors',
              mode === m ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700',
            )}
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
          className={cn(
            'relative flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6',
            'cursor-pointer transition-colors text-center',
            dragging
              ? 'border-blue-400 bg-blue-50'
              : 'border-gray-200 bg-gray-50 hover:border-blue-300 hover:bg-blue-50/40',
          )}
        >
          <Upload className="w-6 h-6 text-gray-400" />
          <p className="text-sm text-gray-500">
            Glissez le fichier JSON ou <span className="text-blue-600 font-medium">cliquez pour parcourir</span>
          </p>
          <p className="text-xs text-gray-400">Export Cookie Editor (.json)</p>
          <input
            ref={fileRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
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
            className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-xs font-mono resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder:text-gray-400"
          />
          <button
            onClick={() => submit(text.trim())}
            disabled={loading || !text.trim()}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium',
              'bg-blue-600 text-white hover:bg-blue-700 transition-colors',
              (loading || !text.trim()) && 'opacity-50 cursor-not-allowed hover:bg-blue-600',
            )}
          >
            {loading
              ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              : <Save className="w-3.5 h-3.5" />}
            Valider
          </button>
        </div>
      )}

      {loading && mode === 'drop' && (
        <div className="flex items-center gap-2 text-sm text-blue-600">
          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          Import en cours…
        </div>
      )}

      {status && (
        <div className={cn(
          'flex items-center gap-2 text-sm rounded-lg px-3 py-2',
          status.type === 'success'
            ? 'bg-green-50 text-green-700 border border-green-200'
            : 'bg-red-50 text-red-600 border border-red-200',
        )}>
          {status.type === 'success'
            ? <CheckCircle2 className="w-4 h-4 shrink-0" />
            : <XCircle className="w-4 h-4 shrink-0" />}
          {status.msg}
        </div>
      )}
    </div>
  )
}

// ── Main Settings component ────────────────────────────────────────────────────

export function Settings({ onBack, onConfigChange }: Props) {
  const [config, setConfig] = useState<ConfigStatus | null>(null)

  // API keys state
  const [keys, setKeys] = useState({ serper: '', dropcontact: '', anthropic: '' })
  const [showKey, setShowKey] = useState({ serper: false, dropcontact: false, anthropic: false })
  const [savingKeys, setSavingKeys] = useState(false)
  const [keysStatus, setKeysStatus] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)

  // Pipeline params state
  const [pipeline, setPipeline] = useState({ hitThreshold: 50 })
  const [savingPipeline, setSavingPipeline] = useState(false)
  const [pipelineStatus, setPipelineStatus] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)

  const refreshConfig = useCallback(() => {
    getConfig()
      .then(c => {
        setConfig(c)
        setPipeline({ hitThreshold: c.hit_threshold })
        onConfigChange?.(c)
      })
      .catch(() => null)
  }, [onConfigChange])

  useEffect(() => { refreshConfig() }, [refreshConfig])

  const handleSaveKeys = async () => {
    setSavingKeys(true)
    setKeysStatus(null)
    try {
      await saveConfig({
        serper_api_key: keys.serper || undefined,
        dropcontact_api_key: keys.dropcontact || undefined,
        anthropic_api_key: keys.anthropic || undefined,
      })
      setKeysStatus({ type: 'success', msg: 'Clés sauvegardées' })
      setKeys({ serper: '', dropcontact: '', anthropic: '' })
      refreshConfig()
    } catch (e: unknown) {
      setKeysStatus({ type: 'error', msg: e instanceof Error ? e.message : 'Erreur' })
    } finally {
      setSavingKeys(false)
    }
  }

  const handleSavePipeline = async () => {
    setSavingPipeline(true)
    setPipelineStatus(null)
    try {
      await saveConfig({ hit_threshold: pipeline.hitThreshold })
      setPipelineStatus({ type: 'success', msg: 'Paramètres sauvegardés' })
      refreshConfig()
    } catch (e: unknown) {
      setPipelineStatus({ type: 'error', msg: e instanceof Error ? e.message : 'Erreur' })
    } finally {
      setSavingPipeline(false)
    }
  }

  const keyFields: { id: keyof typeof keys; label: string; required: boolean; configKey: keyof ConfigStatus }[] = [
    { id: 'serper', label: 'SERPER_API_KEY', required: true, configKey: 'serper_api_key' },
    { id: 'dropcontact', label: 'DROPCONTACT_API_KEY', required: false, configKey: 'dropcontact_api_key' },
    { id: 'anthropic', label: 'ANTHROPIC_API_KEY', required: true, configKey: 'anthropic_api_key' },
  ]

  return (
    <div className="w-full max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors px-3 py-1.5 rounded-lg hover:bg-gray-100"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Retour
        </button>
        <div>
          <h1 className="text-xl font-bold text-gray-900">Paramètres</h1>
          <p className="text-xs text-gray-500">Configuration de l'app — clés API, cookies, pipeline</p>
        </div>
      </div>

      {/* Global status summary */}
      {config && (
        <div className={cn(
          'rounded-xl border p-4 flex items-start gap-3',
          (!config.serper_api_key || !config.anthropic_api_key || !config.apollo_cookies)
            ? 'bg-amber-50 border-amber-200'
            : 'bg-green-50 border-green-200',
        )}>
          {(!config.serper_api_key || !config.anthropic_api_key || !config.apollo_cookies) ? (
            <>
              <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <div className="text-sm">
                <p className="font-medium text-amber-800">Configuration incomplète</p>
                <p className="text-amber-700 text-xs mt-0.5">
                  Complétez les champs requis ci-dessous pour activer le pipeline.
                </p>
              </div>
            </>
          ) : (
            <>
              <CheckCircle2 className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />
              <p className="text-sm font-medium text-green-700">Configuration complète — pipeline prêt</p>
            </>
          )}
        </div>
      )}

      {/* ── API Keys ─────────────────────────────────────────────────────────── */}
      <SectionCard title="Clés API" icon={<KeyRound className="w-4 h-4" />}>
        <div className="space-y-4">
          {keyFields.map(({ id, label, required, configKey }) => (
            <div key={id}>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-medium text-gray-600">
                  {label}
                  {required && <span className="ml-1 text-red-500">*</span>}
                </label>
                {config && (
                  <StatusBadge
                    ok={Boolean(config[configKey])}
                    label={Boolean(config[configKey]) ? 'Configuré' : 'Manquant'}
                  />
                )}
              </div>
              <div className="relative">
                <input
                  type={showKey[id] ? 'text' : 'password'}
                  value={keys[id]}
                  onChange={e => setKeys(prev => ({ ...prev, [id]: e.target.value }))}
                  placeholder={config?.[configKey] ? '••••••••••••••••  (déjà configuré)' : 'Entrez la clé…'}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder:text-gray-400"
                />
                <button
                  type="button"
                  onClick={() => setShowKey(prev => ({ ...prev, [id]: !prev[id] }))}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  {showKey[id] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
              {!required && (
                <p className="mt-1 text-xs text-gray-400">Optionnel — email/téléphone ignorés si absent</p>
              )}
            </div>
          ))}

          {keysStatus && (
            <div className={cn(
              'flex items-center gap-2 text-sm rounded-lg px-3 py-2',
              keysStatus.type === 'success'
                ? 'bg-green-50 text-green-700 border border-green-200'
                : 'bg-red-50 text-red-600 border border-red-200',
            )}>
              {keysStatus.type === 'success'
                ? <CheckCircle2 className="w-4 h-4 shrink-0" />
                : <XCircle className="w-4 h-4 shrink-0" />}
              {keysStatus.msg}
            </div>
          )}

          <button
            onClick={handleSaveKeys}
            disabled={savingKeys || (!keys.serper && !keys.dropcontact && !keys.anthropic)}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium',
              'bg-blue-600 text-white hover:bg-blue-700 transition-colors',
              (savingKeys || (!keys.serper && !keys.dropcontact && !keys.anthropic)) &&
                'opacity-50 cursor-not-allowed hover:bg-blue-600',
            )}
          >
            {savingKeys ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Sauvegarder les clés
          </button>
        </div>
      </SectionCard>

      {/* ── Cookies ──────────────────────────────────────────────────────────── */}
      <SectionCard title="Cookies de session" icon={<Cookie className="w-4 h-4" />}>
        <div className="space-y-6">
          <p className="text-xs text-gray-500">
            Exportez vos cookies depuis l'extension <strong>Cookie Editor</strong> sur Apollo.io et LinkedIn,
            puis importez-les ici.
          </p>
          <div className="grid gap-6 sm:grid-cols-2">
            <CookiePanel
              service="apollo"
              label="Apollo.io"
              isPresent={config?.apollo_cookies ?? false}
              onUploaded={refreshConfig}
            />
            <CookiePanel
              service="linkedin"
              label="LinkedIn"
              isPresent={config?.linkedin_cookies ?? false}
              onUploaded={refreshConfig}
            />
          </div>
        </div>
      </SectionCard>

      {/* ── Pipeline params ───────────────────────────────────────────────────── */}
      <SectionCard title="Paramètres du pipeline" icon={<SlidersHorizontal className="w-4 h-4" />}>
        <div className="space-y-4">
          <div className="max-w-xs">
            <label className="block text-xs font-medium text-gray-600 mb-1.5">
              HIT_THRESHOLD
              <span className="ml-1 font-normal text-gray-400">(score minimum pour être un lead "hit")</span>
            </label>
            <input
              type="number"
              min={0}
              max={100}
              value={pipeline.hitThreshold}
              onChange={e => setPipeline(prev => ({ ...prev, hitThreshold: Number(e.target.value) }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="mt-1 text-xs text-gray-400">0–100 · email=40pts, linkedin=30pts, phone=20pts, website=10pts</p>
          </div>
          <p className="text-xs text-gray-400">
            Le nombre de leads par run se configure dans les paramètres avancés du formulaire de lancement.
          </p>

          {pipelineStatus && (
            <div className={cn(
              'flex items-center gap-2 text-sm rounded-lg px-3 py-2',
              pipelineStatus.type === 'success'
                ? 'bg-green-50 text-green-700 border border-green-200'
                : 'bg-red-50 text-red-600 border border-red-200',
            )}>
              {pipelineStatus.type === 'success'
                ? <CheckCircle2 className="w-4 h-4 shrink-0" />
                : <XCircle className="w-4 h-4 shrink-0" />}
              {pipelineStatus.msg}
            </div>
          )}

          <button
            onClick={handleSavePipeline}
            disabled={savingPipeline}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium',
              'bg-blue-600 text-white hover:bg-blue-700 transition-colors',
              savingPipeline && 'opacity-50 cursor-not-allowed hover:bg-blue-600',
            )}
          >
            {savingPipeline ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Sauvegarder
          </button>
        </div>
      </SectionCard>
    </div>
  )
}
