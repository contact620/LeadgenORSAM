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

// ── Status badge ────────────────────────────────────────────────────────────

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full"
      style={ok ? {
        background: 'rgba(52,211,153,0.1)',
        color: '#34d399',
        border: '1px solid rgba(52,211,153,0.2)',
      } : {
        background: 'rgba(248,113,113,0.1)',
        color: '#f87171',
        border: '1px solid rgba(248,113,113,0.2)',
      }}
    >
      {ok ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
      {label}
    </span>
  )
}

// ── Section card ────────────────────────────────────────────────────────────

function SectionCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="glass-card">
      <div
        className="flex items-center gap-2.5 px-6 py-4"
        style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}
      >
        <span style={{ color: '#4d9fff' }}>{icon}</span>
        <h2 className="font-semibold text-sm" style={{ color: '#e2e8f8' }}>{title}</h2>
      </div>
      <div style={{ padding: '20px 24px' }}>{children}</div>
    </div>
  )
}

// ── Cookie panel ────────────────────────────────────────────────────────────

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
        <span className="text-sm font-medium" style={{ color: 'rgba(226,232,248,0.6)' }}>{label}</span>
        <StatusBadge ok={isPresent} label={isPresent ? 'Présent' : 'Absent'} />
      </div>

      {/* Mode tabs */}
      <div className="flex gap-1 p-1 rounded-lg w-fit text-xs" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}>
        {(['drop', 'paste'] as const).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className="px-3 py-1 rounded-md font-medium transition-all"
            style={mode === m ? { background: 'rgba(255,255,255,0.08)', color: '#e2e8f8', border: 'none', cursor: 'pointer', fontFamily: 'inherit' } : { color: 'rgba(226,232,248,0.4)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
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
            border: '2px dashed rgba(77,159,255,0.5)',
            background: 'rgba(77,159,255,0.06)',
          } : {
            border: '2px dashed rgba(255,255,255,0.08)',
            background: 'rgba(255,255,255,0.02)',
          }}
        >
          <Upload className="w-5 h-5" style={{ color: 'rgba(226,232,248,0.25)' }} />
          <p className="text-sm" style={{ color: 'rgba(226,232,248,0.4)' }}>
            Glissez le fichier JSON ou <span style={{ color: '#4d9fff', fontWeight: 500 }}>cliquez pour parcourir</span>
          </p>
          <p className="text-xs" style={{ color: 'rgba(226,232,248,0.2)' }}>Export Cookie Editor (.json)</p>
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
        <div className="flex items-center gap-2 text-sm" style={{ color: '#4d9fff' }}>
          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          Import en cours…
        </div>
      )}

      {status && (
        <div
          className="flex items-center gap-2 text-sm rounded-lg px-3 py-2"
          style={status.type === 'success' ? {
            background: 'rgba(52,211,153,0.08)',
            color: '#34d399',
            border: '1px solid rgba(52,211,153,0.2)',
          } : {
            background: 'rgba(248,113,113,0.08)',
            color: '#f87171',
            border: '1px solid rgba(248,113,113,0.2)',
          }}
        >
          {status.type === 'success' ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <XCircle className="w-4 h-4 shrink-0" />}
          {status.msg}
        </div>
      )}
    </div>
  )
}

// ── Main Settings ───────────────────────────────────────────────────────────

export function Settings({ onBack, onConfigChange }: Props) {
  const [config, setConfig] = useState<ConfigStatus | null>(null)
  const [keys, setKeys] = useState({ serper: '', dropcontact: '', anthropic: '' })
  const [showKey, setShowKey] = useState({ serper: false, dropcontact: false, anthropic: false })
  const [savingKeys, setSavingKeys] = useState(false)
  const [keysStatus, setKeysStatus] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [pipeline, setPipeline] = useState({ hitThreshold: 50 })
  const [savingPipeline, setSavingPipeline] = useState(false)
  const [pipelineStatus, setPipelineStatus] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)

  const refreshConfig = useCallback(() => {
    getConfig().then(c => { setConfig(c); setPipeline({ hitThreshold: c.hit_threshold }); onConfigChange?.(c) }).catch(() => null)
  }, [onConfigChange])

  useEffect(() => { refreshConfig() }, [refreshConfig])

  const handleSaveKeys = async () => {
    setSavingKeys(true); setKeysStatus(null)
    try {
      await saveConfig({ serper_api_key: keys.serper || undefined, dropcontact_api_key: keys.dropcontact || undefined, anthropic_api_key: keys.anthropic || undefined })
      setKeysStatus({ type: 'success', msg: 'Clés sauvegardées' })
      setKeys({ serper: '', dropcontact: '', anthropic: '' })
      refreshConfig()
    } catch (e: unknown) {
      setKeysStatus({ type: 'error', msg: e instanceof Error ? e.message : 'Erreur' })
    } finally { setSavingKeys(false) }
  }

  const handleSavePipeline = async () => {
    setSavingPipeline(true); setPipelineStatus(null)
    try {
      await saveConfig({ hit_threshold: pipeline.hitThreshold })
      setPipelineStatus({ type: 'success', msg: 'Paramètres sauvegardés' })
      refreshConfig()
    } catch (e: unknown) {
      setPipelineStatus({ type: 'error', msg: e instanceof Error ? e.message : 'Erreur' })
    } finally { setSavingPipeline(false) }
  }

  const keyFields: { id: keyof typeof keys; label: string; required: boolean; configKey: keyof ConfigStatus }[] = [
    { id: 'serper',      label: 'SERPER_API_KEY',      required: true,  configKey: 'serper_api_key' },
    { id: 'dropcontact', label: 'DROPCONTACT_API_KEY', required: false, configKey: 'dropcontact_api_key' },
    { id: 'anthropic',   label: 'ANTHROPIC_API_KEY',   required: true,  configKey: 'anthropic_api_key' },
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
          style={{ color: 'rgba(226,232,248,0.4)', border: '1px solid rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.04)', cursor: 'pointer', fontFamily: 'inherit' }}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Retour
        </button>
        <div>
          <h1 className="text-xl font-bold" style={{ color: '#e2e8f8', letterSpacing: '-0.02em' }}>Paramètres</h1>
          <p className="text-xs" style={{ color: 'rgba(226,232,248,0.3)' }}>Configuration — clés API, cookies, pipeline</p>
        </div>
      </div>

      {/* Global status */}
      {config && (
        <div
          className="rounded-xl p-4 flex items-start gap-3"
          style={(!config.serper_api_key || !config.anthropic_api_key || !config.apollo_cookies) ? {
            background: 'rgba(251,191,36,0.06)',
            border: '1px solid rgba(251,191,36,0.18)',
          } : {
            background: 'rgba(52,211,153,0.06)',
            border: '1px solid rgba(52,211,153,0.18)',
          }}
        >
          {(!config.serper_api_key || !config.anthropic_api_key || !config.apollo_cookies) ? (
            <>
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" style={{ color: '#fbbf24' }} />
              <div className="text-sm">
                <p className="font-medium mb-0.5" style={{ color: 'rgba(251,191,36,0.9)' }}>Configuration incomplète</p>
                <p className="text-xs" style={{ color: 'rgba(251,191,36,0.6)' }}>Complétez les champs requis ci-dessous pour activer le pipeline.</p>
              </div>
            </>
          ) : (
            <>
              <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" style={{ color: '#34d399' }} />
              <p className="text-sm font-medium" style={{ color: 'rgba(52,211,153,0.9)' }}>Configuration complète — pipeline prêt</p>
            </>
          )}
        </div>
      )}

      {/* API Keys */}
      <SectionCard title="Clés API" icon={<KeyRound className="w-4 h-4" />}>
        <div className="space-y-5">
          {keyFields.map(({ id, label, required, configKey }) => (
            <div key={id}>
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-medium" style={{ color: 'rgba(226,232,248,0.5)' }}>
                  {label}
                  {required && <span className="ml-1" style={{ color: '#f87171' }}>*</span>}
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
                  style={{ color: 'rgba(226,232,248,0.3)', background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  {showKey[id] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
              {!required && <p className="mt-1 text-xs" style={{ color: 'rgba(226,232,248,0.25)' }}>Optionnel — email/téléphone ignorés si absent</p>}
            </div>
          ))}

          {keysStatus && (
            <div
              className="flex items-center gap-2 text-sm rounded-lg px-3 py-2"
              style={keysStatus.type === 'success' ? {
                background: 'rgba(52,211,153,0.08)', color: '#34d399', border: '1px solid rgba(52,211,153,0.2)',
              } : {
                background: 'rgba(248,113,113,0.08)', color: '#f87171', border: '1px solid rgba(248,113,113,0.2)',
              }}
            >
              {keysStatus.type === 'success' ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <XCircle className="w-4 h-4 shrink-0" />}
              {keysStatus.msg}
            </div>
          )}

          <button
            onClick={handleSaveKeys}
            disabled={savingKeys || (!keys.serper && !keys.dropcontact && !keys.anthropic)}
            className="btn-grad flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium text-white"
            style={actionBtnStyle(savingKeys || (!keys.serper && !keys.dropcontact && !keys.anthropic))}
          >
            {savingKeys ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Sauvegarder les clés
          </button>
        </div>
      </SectionCard>

      {/* Cookies */}
      <SectionCard title="Cookies de session" icon={<Cookie className="w-4 h-4" />}>
        <div className="space-y-6">
          <p className="text-xs" style={{ color: 'rgba(226,232,248,0.3)' }}>
            Exportez vos cookies depuis l'extension <strong style={{ color: 'rgba(226,232,248,0.5)' }}>Cookie Editor</strong> sur Apollo.io et LinkedIn, puis importez-les ici.
          </p>
          <div className="grid gap-6 sm:grid-cols-2">
            <CookiePanel service="apollo" label="Apollo.io" isPresent={config?.apollo_cookies ?? false} onUploaded={refreshConfig} />
            <CookiePanel service="linkedin" label="LinkedIn" isPresent={config?.linkedin_cookies ?? false} onUploaded={refreshConfig} />
          </div>
        </div>
      </SectionCard>

      {/* Pipeline params */}
      <SectionCard title="Paramètres du pipeline" icon={<SlidersHorizontal className="w-4 h-4" />}>
        <div className="space-y-4">
          <div className="max-w-xs">
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'rgba(226,232,248,0.5)' }}>
              HIT_THRESHOLD
              <span className="ml-1 font-normal" style={{ color: 'rgba(226,232,248,0.25)' }}>(score minimum pour être un lead "hit")</span>
            </label>
            <input
              type="number" min={0} max={100}
              value={pipeline.hitThreshold}
              onChange={e => setPipeline(prev => ({ ...prev, hitThreshold: Number(e.target.value) }))}
              className="surface-input w-full"
              style={{ padding: '9px 12px', fontSize: 14 }}
            />
            <p className="mt-1 text-xs" style={{ color: 'rgba(226,232,248,0.25)' }}>0–100 · email=40pts, linkedin=30pts, phone=20pts, website=10pts</p>
          </div>
          <p className="text-xs" style={{ color: 'rgba(226,232,248,0.25)' }}>
            Le nombre de leads par run se configure dans les paramètres avancés du formulaire de lancement.
          </p>

          {pipelineStatus && (
            <div
              className="flex items-center gap-2 text-sm rounded-lg px-3 py-2"
              style={pipelineStatus.type === 'success' ? {
                background: 'rgba(52,211,153,0.08)', color: '#34d399', border: '1px solid rgba(52,211,153,0.2)',
              } : {
                background: 'rgba(248,113,113,0.08)', color: '#f87171', border: '1px solid rgba(248,113,113,0.2)',
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
