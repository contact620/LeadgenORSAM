import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { Rocket, AlertCircle, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getHealth, type HealthCheck } from '@/lib/api'

interface Props {
  onSubmit: (url: string, maxLeads: number, skipGpt: boolean) => void
  disabled?: boolean
  configReady?: boolean
  defaultMaxLeads?: number
  onOpenSettings?: () => void
}

export function ApolloForm({ onSubmit, disabled, configReady, defaultMaxLeads, onOpenSettings }: Props) {
  const [url, setUrl] = useState('')
  const [maxLeads, setMaxLeads] = useState(defaultMaxLeads ?? 200)
  const [skipGpt, setSkipGpt] = useState(false)
  const [showConfig, setShowConfig] = useState(true)
  const [health, setHealth] = useState<HealthCheck | null>(null)

  useEffect(() => {
    getHealth().then(setHealth).catch(() => {
      toast.error('Backend inaccessible', {
        description: 'Vérifiez que le serveur est lancé sur le port 8000.',
      })
    })
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return
    onSubmit(url.trim(), maxLeads, skipGpt)
  }

  const missingKeys = health?.missing_keys ?? []
  const hasIssues = missingKeys.length > 0 || !health?.apollo_cookies

  return (
    <div className="w-full max-w-2xl mx-auto">
      {/* ── Hero ──────────────────────────────────────────────────────── */}
      <div className="text-center mb-12">
        <div
          className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-xs font-semibold mb-6"
          style={{ background: 'rgba(77,159,255,0.08)', border: '1px solid rgba(77,159,255,0.2)', color: '#63a0ff', letterSpacing: '0.08em', textTransform: 'uppercase' }}
        >
          <span
            className="pulse-dot flex-shrink-0"
            style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#63a0ff', boxShadow: '0 0 8px #63a0ff' }}
          />
          Pipeline B2B Actif
        </div>

        <h1
          className="grad-text-primary font-bold mb-4"
          style={{ fontSize: 44, lineHeight: 1.1, letterSpacing: '-0.03em' }}
        >
          Lead Generation<br />Pipeline
        </h1>
        <p className="text-base font-light" style={{ color: 'rgba(226,232,248,0.5)', lineHeight: 1.6 }}>
          Apollo → <strong style={{ color: 'rgba(226,232,248,0.8)', fontWeight: 500 }}>Google CSE</strong> → Dropcontact → <strong style={{ color: 'rgba(226,232,248,0.8)', fontWeight: 500 }}>Claude AI</strong>
          <br />Extrayez, enrichissez et qualifiez vos leads B2B en 5 étapes.
        </p>
      </div>

      {/* ── Config alerts ────────────────────────────────────────────── */}
      {health && hasIssues && (
        <div className="mb-6 rounded-xl p-4 flex gap-3" style={{ background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.18)' }}>
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" style={{ color: '#fbbf24' }} />
          <div className="text-sm flex-1">
            <p className="font-medium mb-1" style={{ color: 'rgba(251,191,36,0.9)' }}>Configuration incomplète</p>
            {missingKeys.length > 0 && (
              <p style={{ color: 'rgba(251,191,36,0.7)' }}>
                Clés API manquantes : <span className="font-mono" style={{ color: '#fbbf24' }}>{missingKeys.join(', ')}</span>
              </p>
            )}
            {!health.apollo_cookies && <p style={{ color: 'rgba(251,191,36,0.7)' }}>Cookies Apollo introuvables</p>}
            {onOpenSettings && (
              <button type="button" onClick={onOpenSettings} className="mt-2 text-xs font-semibold underline" style={{ color: '#fbbf24', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}>
                Ouvrir les Paramètres →
              </button>
            )}
          </div>
        </div>
      )}

      {(health && !hasIssues || configReady) && (
        <div className="mb-6 rounded-xl p-3 flex items-center gap-2.5" style={{ background: 'rgba(52,211,153,0.06)', border: '1px solid rgba(52,211,153,0.18)' }}>
          <span className="pulse-dot-slow flex-shrink-0" style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: '#34d399', boxShadow: '0 0 8px #34d399' }} />
          <span className="text-sm font-medium" style={{ color: 'rgba(52,211,153,0.9)' }}>
            Système opérationnel — backend connecté · API health OK
          </span>
        </div>
      )}

      {/* ── Form card ────────────────────────────────────────────────── */}
      <form onSubmit={handleSubmit} className="glass-card">
        <div style={{ padding: '28px 32px 0' }}>
          <p className="text-xs font-semibold mb-1" style={{ color: 'rgba(226,232,248,0.25)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Nouvelle session</p>
          <p className="text-lg font-semibold" style={{ color: '#e2e8f8', letterSpacing: '-0.02em' }}>Lancer le pipeline</p>
        </div>

        <div style={{ padding: '24px 32px 32px' }}>
          {/* URL input */}
          <div className="mb-6">
            <div className="flex items-center justify-between mb-2.5">
              <label className="text-sm font-medium" style={{ color: 'rgba(226,232,248,0.5)' }}>URL Apollo.io</label>
              <span className="text-xs font-semibold px-2 py-0.5 rounded" style={{ background: 'rgba(77,159,255,0.1)', color: '#4d9fff', border: '1px solid rgba(77,159,255,0.2)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                Requis
              </span>
            </div>
            <textarea
              value={url}
              onChange={e => setUrl(e.target.value)}
              placeholder="https://app.apollo.io/#/people?contactEmailStatus[]=verified&..."
              rows={3}
              disabled={disabled}
              className="surface-input w-full"
              style={{ padding: '13px 15px', fontSize: '12.5px', lineHeight: 1.7, resize: 'none', minHeight: 88, opacity: disabled ? 0.4 : 1 }}
            />
            <p className="mt-2 text-xs" style={{ color: 'rgba(226,232,248,0.25)', lineHeight: 1.5 }}>
              Effectuez votre recherche sur Apollo.io, puis copiez-collez l'URL complète.
            </p>
          </div>

          <div style={{ height: 1, background: 'rgba(255,255,255,0.07)', marginBottom: 20 }} />

          {/* Advanced toggle */}
          <button
            type="button"
            onClick={() => setShowConfig(!showConfig)}
            className="flex items-center gap-2 text-sm font-medium"
            style={{ color: 'rgba(226,232,248,0.25)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', padding: 0 }}
          >
            <span style={{ width: 16, height: 16, border: '1px solid rgba(255,255,255,0.1)', borderRadius: 4, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 9 }}>
              {showConfig ? '▴' : '▾'}
            </span>
            <Settings className="w-3.5 h-3.5" style={{ opacity: 0.5 }} />
            Paramètres avancés
          </button>

          {showConfig && (
            <div className="mt-4 grid grid-cols-2 gap-4 surface-dark" style={{ padding: 20 }}>
              <div>
                <label className="block text-xs font-medium mb-1.5" style={{ color: 'rgba(226,232,248,0.5)' }}>Leads max</label>
                <input
                  type="number" min={1} max={5000} value={maxLeads}
                  onChange={e => setMaxLeads(Number(e.target.value))}
                  disabled={disabled}
                  className="surface-input w-full"
                  style={{ padding: '8px 12px', fontSize: 14, borderRadius: 8, opacity: disabled ? 0.4 : 1 }}
                />
                <p className="mt-1 text-xs" style={{ color: 'rgba(226,232,248,0.25)' }}>Apollo scraping limit</p>
              </div>

              <div>
                <label className="block text-xs font-medium mb-1.5" style={{ color: 'rgba(226,232,248,0.5)' }}>Skip enrichissement IA</label>
                <div className="flex items-center gap-2" style={{ height: 36 }}>
                  <div
                    role="switch" aria-checked={skipGpt}
                    onClick={() => !disabled && setSkipGpt(!skipGpt)}
                    className={cn('toggle-track', skipGpt && 'on')}
                    style={{ opacity: disabled ? 0.4 : 1 }}
                  >
                    <div className="toggle-knob" />
                  </div>
                  <span className="text-xs" style={{ color: 'rgba(226,232,248,0.4)' }}>
                    {skipGpt ? 'Désactivé (plus rapide)' : 'Activé'}
                  </span>
                </div>
                <p className="mt-1 text-xs" style={{ color: 'rgba(226,232,248,0.25)' }}>Saute GPT-4o-mini (étape 5)</p>
              </div>
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={disabled || !url.trim()}
            className="btn-grad w-full flex items-center justify-center gap-2.5 rounded-xl text-white font-semibold mt-7"
            style={{ padding: '15px 24px', fontSize: 15, letterSpacing: '-0.01em', opacity: (disabled || !url.trim()) ? 0.4 : 1, cursor: (disabled || !url.trim()) ? 'not-allowed' : 'pointer', border: 'none', fontFamily: 'inherit' }}
          >
            <span style={{ width: 18, height: 18, background: 'rgba(255,255,255,0.2)', borderRadius: 4, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, flexShrink: 0 }}>▶</span>
            <Rocket className="w-4 h-4" />
            Lancer le pipeline
          </button>
        </div>
      </form>

      {/* ── Pipeline steps ───────────────────────────────────────────── */}
      <div className="mt-10">
        <p className="text-xs font-semibold mb-4" style={{ color: 'rgba(226,232,248,0.25)', letterSpacing: '0.12em', textTransform: 'uppercase' }}>
          5 étapes automatisées
        </p>
        <div className="grid grid-cols-5 gap-2">
          {[
            { num: '01', icon: '🔍', name: 'Scraping Apollo',   tool: 'Playwright' },
            { num: '02', icon: '🔗', name: 'LinkedIn URL',      tool: 'Google CSE' },
            { num: '03', icon: '📧', name: 'Email + Tel',       tool: 'Dropcontact' },
            { num: '04', icon: '📊', name: 'Score & Filtre',    tool: '0–100 pts' },
            { num: '05', icon: '🤖', name: 'Enrichissement IA', tool: 'Claude AI' },
          ].map(step => (
            <div
              key={step.num}
              className="rounded-xl text-center transition-all duration-200 hover:-translate-y-0.5"
              style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.06)', padding: '16px 12px' }}
            >
              <p className="font-mono text-xs mb-2" style={{ color: 'rgba(226,232,248,0.25)', fontWeight: 600 }}>{step.num}</p>
              <p className="text-xl mb-2">{step.icon}</p>
              <p className="text-xs font-semibold leading-snug" style={{ color: 'rgba(226,232,248,0.5)' }}>{step.name}</p>
              <p className="text-xs mt-1" style={{ color: 'rgba(226,232,248,0.25)' }}>{step.tool}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
