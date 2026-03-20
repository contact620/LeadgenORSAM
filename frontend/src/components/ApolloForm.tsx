import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { Rocket, AlertCircle, Settings, ChevronDown, ChevronUp, Database } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getHealth, startScrapeJob, type HealthCheck, type RunRequest, type RerunParams, type ConfigStatus } from '@/lib/api'

interface Props {
  onSubmit: (req: RunRequest) => void
  disabled?: boolean
  configReady?: boolean
  defaultMaxLeads?: number
  onOpenSettings?: () => void
  prefill?: RerunParams | null
  services?: string[]
}

export function ApolloForm({ onSubmit, disabled, configReady, defaultMaxLeads, onOpenSettings, prefill, services = [] }: Props) {
  const [url, setUrl] = useState('')
  const [maxLeads, setMaxLeads] = useState(defaultMaxLeads ?? 200)
  const [skipGpt, setSkipGpt] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [health, setHealth] = useState<HealthCheck | null>(null)
  const [selectedServices, setSelectedServices] = useState<string[]>([])
  const [signalInstructions, setSignalInstructions] = useState('')
  const [poolName, setPoolName] = useState('')
  const [scrapeLoading, setScrapeLoading] = useState(false)

  useEffect(() => {
    if (prefill) {
      setUrl(prefill.url)
      setMaxLeads(prefill.max_leads)
      setSkipGpt(prefill.skip_gpt)
    }
  }, [prefill])

  useEffect(() => {
    getHealth().then(setHealth).catch(() => {
      toast.error('Backend inaccessible', {
        description: 'Vérifiez que le serveur est lancé sur le port 8000.',
      })
    })
  }, [])

  const isValidApolloUrl = (u: string) => /apollo\.io/i.test(u)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return
    if (!isValidApolloUrl(url)) {
      toast.error('URL invalide', { description: 'L\'URL doit provenir de app.apollo.io' })
      return
    }
    const parts: string[] = []
    if (selectedServices.length > 0) {
      parts.push(`Services ciblés pour cette campagne : ${selectedServices.join(', ')}.`)
      parts.push(`Évalue chaque lead en fonction de son besoin potentiel pour ces services spécifiques.`)
    }
    if (signalInstructions.trim()) {
      parts.push(`Signaux et déclencheurs à rechercher : ${signalInstructions.trim()}`)
    }

    onSubmit({
      url: url.trim(),
      max_leads: maxLeads,
      skip_gpt: skipGpt,
      enrich_instructions: parts.length > 0 ? parts.join('\n') : undefined,
    })
  }

  const missingKeys = health?.missing_keys ?? []
  const hasIssues = missingKeys.length > 0 || !health?.apollo_cookies
  const isReady = !disabled && url.trim() && isValidApolloUrl(url)

  const pipelineSteps = [
    { icon: '🔍', name: 'Scraping Apollo', tool: 'Playwright' },
    { icon: '🔗', name: 'LinkedIn URL', tool: 'Google CSE' },
    { icon: '📧', name: 'Email + Tel', tool: 'Dropcontact' },
    { icon: '📊', name: 'Score & Filtre', tool: 'Hit Score 0-100' },
    { icon: '🎯', name: 'Scoring ICP', tool: 'Claude AI' },
    { icon: '🤖', name: 'Enrichissement', tool: 'Claude + Perplexity' },
  ]

  return (
    <div className="w-full">
      {/* ── Hero ──────────────────────────────────────────────────────── */}
      <div className="text-center mb-8 animate-fade-in">
        <div
          className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-xs font-semibold mb-4"
          style={{ background: 'var(--th-primary-soft)', border: '1px solid var(--th-primary-border)', color: 'var(--th-primary)', letterSpacing: '0.08em', textTransform: 'uppercase' }}
        >
          <span className="pulse-dot flex-shrink-0" style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: 'var(--th-primary)', boxShadow: '0 0 8px var(--th-primary)' }} />
          Pipeline B2B Actif
        </div>
        <h1 className="grad-text-blue font-bold mb-3" style={{ fontSize: 34, lineHeight: 1.1, letterSpacing: '-0.03em' }}>
          Lead Generation Pipeline
        </h1>
        <p className="text-sm font-light" style={{ color: 'var(--th-text-tertiary)', lineHeight: 1.6 }}>
          Extrayez, enrichissez et qualifiez vos leads B2B en 6 étapes automatisées.
        </p>
      </div>

      {/* ── Config alerts ────────────────────────────────────────────── */}
      {health && hasIssues && (
        <div className="mb-6 rounded-xl p-4 flex gap-3 animate-fade-in" style={{ background: 'var(--th-warning-soft)', border: '1px solid var(--th-warning-border)' }}>
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" style={{ color: 'var(--th-warning)' }} />
          <div className="text-sm flex-1">
            <p className="font-medium mb-1" style={{ color: 'var(--th-warning-text)' }}>Configuration incomplète</p>
            {missingKeys.length > 0 && (
              <p style={{ color: 'var(--th-warning-text)' }}>
                Clés API manquantes : <span className="font-mono" style={{ color: 'var(--th-warning)' }}>{missingKeys.join(', ')}</span>
              </p>
            )}
            {!health.apollo_cookies && <p style={{ color: 'var(--th-warning-text)' }}>Cookies Apollo introuvables</p>}
            {onOpenSettings && (
              <button type="button" onClick={onOpenSettings} className="mt-2 text-xs font-semibold underline" style={{ color: 'var(--th-warning)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}>
                Ouvrir les Paramètres →
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── 2-column layout ──────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 animate-fade-in-d1">

        {/* LEFT: Form (3/5) */}
        <form onSubmit={handleSubmit} className="glass-card lg:col-span-3">
          <div style={{ padding: '24px 28px 0' }}>
            <p className="text-xs font-semibold mb-1" style={{ color: 'var(--th-text-faint)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Nouvelle session</p>
            <p className="text-lg font-semibold" style={{ color: 'var(--th-text-primary)', letterSpacing: '-0.02em' }}>Configuration du pipeline</p>
          </div>

          <div style={{ padding: '20px 28px 28px' }}>
            {/* Section 1: URL */}
            <div className="mb-5">
              <div className="flex items-center gap-3 mb-2">
                <span className="section-number">1</span>
                <label className="text-sm font-semibold" style={{ color: 'var(--th-text-primary)' }}>Source de données</label>
              </div>
              <textarea
                value={url}
                onChange={e => setUrl(e.target.value)}
                placeholder="https://app.apollo.io/#/people?contactEmailStatus[]=verified&..."
                rows={2}
                disabled={disabled}
                className="surface-input w-full"
                style={{ padding: '11px 14px', fontSize: '12.5px', lineHeight: 1.7, resize: 'none', minHeight: 64, opacity: disabled ? 0.4 : 1 }}
              />
            </div>

            {/* Section 2: Services */}
            {services.length > 0 && (
              <div className="mb-5">
                <div className="flex items-center gap-3 mb-2">
                  <span className="section-number">2</span>
                  <label className="text-sm font-semibold" style={{ color: 'var(--th-text-primary)' }}>Services ciblés</label>
                </div>
                <div className="flex flex-wrap gap-2">
                  {services.map(svc => {
                    const isSelected = selectedServices.includes(svc)
                    return (
                      <button
                        key={svc}
                        type="button"
                        onClick={() => setSelectedServices(prev => isSelected ? prev.filter(s => s !== svc) : [...prev, svc])}
                        className="px-3 py-1.5 rounded-lg text-sm font-medium transition-all"
                        style={isSelected ? {
                          background: 'var(--th-primary-soft)', color: 'var(--th-primary)',
                          border: '1px solid var(--th-primary-border)', cursor: 'pointer', fontFamily: 'inherit',
                        } : {
                          background: 'var(--th-glass-inset)', color: 'var(--th-text-quaternary)',
                          border: '1px solid var(--th-glass-sm-border)', cursor: 'pointer', fontFamily: 'inherit',
                        }}
                      >
                        {isSelected ? '✓ ' : ''}{svc}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Section 3: Signals */}
            <div className="mb-5">
              <div className="flex items-center gap-3 mb-2">
                <span className="section-number">{services.length > 0 ? '3' : '2'}</span>
                <label className="text-sm font-semibold" style={{ color: 'var(--th-text-primary)' }}>Signaux à rechercher</label>
              </div>
              <textarea
                value={signalInstructions}
                onChange={e => setSignalInstructions(e.target.value)}
                placeholder="Ex: Site web obsolète, levée de fonds, recrutement marketing..."
                rows={2}
                className="surface-input w-full"
                style={{ padding: '11px 14px', fontSize: '13px', lineHeight: 1.6, resize: 'none', fontFamily: "'DM Sans', sans-serif", fontStyle: 'normal' }}
              />
            </div>

            {/* Advanced toggle */}
            <button
              type="button"
              onClick={() => setShowConfig(!showConfig)}
              className="flex items-center gap-2 text-xs font-medium mb-4"
              style={{ color: 'var(--th-text-muted)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', padding: 0 }}
            >
              {showConfig ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              <Settings className="w-3 h-3" style={{ opacity: 0.5 }} />
              Paramètres avancés
            </button>

            {showConfig && (
              <div className="grid grid-cols-2 gap-4 surface-dark mb-5" style={{ padding: 16 }}>
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Leads max</label>
                  <input
                    type="number" min={1} max={5000} value={maxLeads}
                    onChange={e => setMaxLeads(Number(e.target.value))}
                    disabled={disabled}
                    className="surface-input w-full"
                    style={{ padding: '7px 10px', fontSize: 13, borderRadius: 8, opacity: disabled ? 0.4 : 1 }}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Skip IA</label>
                  <div className="flex items-center gap-2" style={{ height: 34 }}>
                    <div
                      role="switch" aria-checked={skipGpt}
                      onClick={() => !disabled && setSkipGpt(!skipGpt)}
                      className={cn('toggle-track', skipGpt && 'on')}
                      style={{ opacity: disabled ? 0.4 : 1 }}
                    >
                      <div className="toggle-knob" />
                    </div>
                    <span className="text-xs" style={{ color: 'var(--th-text-quaternary)' }}>
                      {skipGpt ? 'Off' : 'On'}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </form>

        {/* RIGHT: Sidebar (2/5) */}
        <div className="lg:col-span-2 space-y-4 lg:sticky lg:top-20 lg:self-start">

          {/* Status */}
          {(health && !hasIssues || configReady) && (
            <div className="rounded-xl p-3 flex items-center gap-2.5" style={{ background: 'var(--th-success-soft)', border: '1px solid var(--th-success-border)' }}>
              <span className="pulse-dot-slow flex-shrink-0" style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: 'var(--th-success)', boxShadow: '0 0 8px var(--th-success)' }} />
              <span className="text-xs font-medium" style={{ color: 'var(--th-success)' }}>
                Système opérationnel
              </span>
            </div>
          )}

          {/* Pipeline steps (vertical) */}
          <div className="glass-card-sm p-4">
            <p className="text-xs font-semibold mb-3" style={{ color: 'var(--th-text-faint)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
              Pipeline · 6 étapes
            </p>
            <div className="space-y-2">
              {pipelineSteps.map((step, i) => (
                <div key={i} className="flex items-center gap-3 p-2 rounded-lg row-hoverable" style={{ transition: 'background 0.15s' }}>
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center text-base" style={{ background: 'var(--th-glass-inset)', border: '1px solid var(--th-border-default)' }}>
                    {step.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold" style={{ color: 'var(--th-text-secondary)' }}>{step.name}</p>
                    <p className="text-xs" style={{ color: 'var(--th-text-faint)' }}>{step.tool}</p>
                  </div>
                  <span className="text-xs font-mono" style={{ color: 'var(--th-text-ghost)' }}>{i + 1}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Launch buttons */}
          <div className="glass-card-sm p-4 space-y-3">
            <button
              type="button"
              onClick={handleSubmit as any}
              disabled={!isReady}
              className="btn-grad w-full flex items-center justify-center gap-2 rounded-xl text-white font-semibold"
              style={{ padding: '14px 20px', fontSize: 14, opacity: isReady ? 1 : 0.4, cursor: isReady ? 'pointer' : 'not-allowed', border: 'none', fontFamily: 'inherit' }}
            >
              <Rocket className="w-4 h-4" />
              Lancer le pipeline
            </button>

            <div className="flex items-center gap-2">
              <input
                type="text"
                value={poolName}
                onChange={e => setPoolName(e.target.value)}
                placeholder="Nom du pool"
                className="surface-input flex-1"
                style={{ padding: '9px 10px', fontSize: 12 }}
              />
              <button
                type="button"
                disabled={!isReady || scrapeLoading}
                onClick={async () => {
                  if (!url.trim() || !isValidApolloUrl(url)) return
                  setScrapeLoading(true)
                  try {
                    await startScrapeJob({ url: url.trim(), max_leads: maxLeads, pool_name: poolName.trim() || 'Pool sans nom' })
                    toast.success('Scraping lancé → Pool')
                  } catch (err) {
                    toast.error('Erreur', { description: err instanceof Error ? err.message : '' })
                  } finally { setScrapeLoading(false) }
                }}
                className="flex items-center gap-1.5 rounded-lg font-medium shrink-0"
                style={{
                  padding: '9px 12px', fontSize: 12,
                  color: 'var(--th-primary)', background: 'var(--th-primary-soft)',
                  border: '1px solid var(--th-primary-border)',
                  opacity: (!isReady || scrapeLoading) ? 0.4 : 1,
                  cursor: (!isReady || scrapeLoading) ? 'not-allowed' : 'pointer',
                  fontFamily: 'inherit',
                }}
              >
                <Database className="w-3.5 h-3.5" />
                Pool
              </button>
            </div>
            <p className="text-xs" style={{ color: 'var(--th-text-ghost)' }}>
              Scrape → Pool : scrapez sans enrichir.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
