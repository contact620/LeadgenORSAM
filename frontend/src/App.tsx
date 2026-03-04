import { useState, useEffect, useCallback } from 'react'
import { usePipeline } from '@/hooks/usePipeline'
import { ApolloForm } from '@/components/ApolloForm'
import { PipelineProgress } from '@/components/PipelineProgress'
import { StatsBar } from '@/components/StatsBar'
import { ResultsTable } from '@/components/ResultsTable'
import { Settings } from '@/components/Settings'
import { History } from '@/components/History'
import { RotateCcw, Settings2, AlertCircle, Clock } from 'lucide-react'
import { getConfig, type ConfigStatus } from '@/lib/api'

type Page = 'main' | 'settings' | 'history'

export default function App() {
  const { state, startPipeline, reset } = usePipeline()
  const { status, jobId, events, latestEvent, result, error } = state

  const [page, setPage] = useState<Page>('main')
  const [config, setConfig] = useState<ConfigStatus | null>(null)

  const refreshConfig = useCallback(() => {
    getConfig().then(setConfig).catch(() => null)
  }, [])

  useEffect(() => { refreshConfig() }, [refreshConfig])

  const handleSubmit = (url: string, maxLeads: number, skipGpt: boolean) => {
    startPipeline({ url, max_leads: maxLeads, skip_gpt: skipGpt })
  }

  const isConfigReady =
    config !== null &&
    config.serper_api_key &&
    config.anthropic_api_key &&
    config.apollo_cookies

  const showBanner = config !== null && !isConfigReady

  return (
    <div className="min-h-screen" style={{ background: '#080c14' }}>
      {/* Aurora background */}
      <div className="aurora">
        <div className="aurora-orb orb-blue" />
        <div className="aurora-orb orb-violet" />
        <div className="aurora-orb orb-cyan" />
      </div>
      <div className="dot-grid" />

      {/* Top nav */}
      <header
        className="sticky top-0 z-50 nav-glass px-4"
        style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}
      >
        <div className="max-w-4xl mx-auto h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
              style={{
                background: 'linear-gradient(135deg, #4d9fff 0%, #9b6bff 100%)',
                boxShadow: '0 4px 16px rgba(77,159,255,0.3)',
              }}
            >
              OR
            </div>
            <button
              onClick={() => { setPage('main'); reset() }}
              className="font-semibold transition-colors hover:opacity-80"
              style={{ color: '#e2e8f8', fontSize: '15px', letterSpacing: '-0.01em', background: 'none', border: 'none', cursor: 'pointer' }}
            >
              ORSAM
            </button>
            <span
              className="text-xs font-semibold px-2 py-0.5 rounded-full hidden sm:inline"
              style={{
                color: '#4d9fff',
                background: 'rgba(77,159,255,0.12)',
                border: '1px solid rgba(77,159,255,0.2)',
                letterSpacing: '0.05em',
                textTransform: 'uppercase',
              }}
            >
              Lead Gen
            </span>
          </div>

          <div className="flex items-center gap-2">
            {page === 'main' && status !== 'idle' && (
              <button
                onClick={reset}
                className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-all"
                style={{
                  color: 'rgba(226,232,248,0.5)',
                  border: '1px solid rgba(255,255,255,0.07)',
                  background: 'rgba(255,255,255,0.04)',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Nouveau pipeline</span>
              </button>
            )}
            <button
              onClick={() => setPage(page === 'history' ? 'main' : 'history')}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-all"
              style={page === 'history' ? {
                color: '#4d9fff',
                background: 'rgba(77,159,255,0.12)',
                border: '1px solid rgba(77,159,255,0.2)',
                cursor: 'pointer',
                fontFamily: 'inherit',
              } : {
                color: 'rgba(226,232,248,0.5)',
                border: '1px solid rgba(255,255,255,0.07)',
                background: 'rgba(255,255,255,0.04)',
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              <Clock className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Historique</span>
            </button>
            <button
              onClick={() => setPage(page === 'settings' ? 'main' : 'settings')}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-all"
              style={page === 'settings' ? {
                color: '#4d9fff',
                background: 'rgba(77,159,255,0.12)',
                border: '1px solid rgba(77,159,255,0.2)',
                cursor: 'pointer',
                fontFamily: 'inherit',
              } : {
                color: 'rgba(226,232,248,0.5)',
                border: '1px solid rgba(255,255,255,0.07)',
                background: 'rgba(255,255,255,0.04)',
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              <Settings2 className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Paramètres</span>
            </button>
          </div>
        </div>
      </header>

      {/* Incomplete config banner */}
      {showBanner && page === 'main' && (
        <div
          className="relative z-10 px-4 py-2.5"
          style={{
            background: 'rgba(251,191,36,0.06)',
            borderBottom: '1px solid rgba(251,191,36,0.18)',
          }}
        >
          <div className="max-w-4xl mx-auto flex items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-sm" style={{ color: 'rgba(251,191,36,0.8)' }}>
              <AlertCircle className="w-4 h-4 shrink-0" style={{ color: '#fbbf24' }} />
              <span>
                Configuration incomplète —{' '}
                {!config.serper_api_key && (
                  <span className="font-mono font-medium" style={{ color: '#fbbf24' }}>SERPER_API_KEY </span>
                )}
                {!config.anthropic_api_key && (
                  <span className="font-mono font-medium" style={{ color: '#fbbf24' }}>ANTHROPIC_API_KEY </span>
                )}
                {!config.apollo_cookies && (
                  <span className="font-mono font-medium" style={{ color: '#fbbf24' }}>Apollo cookies </span>
                )}
                manquant(s).
              </span>
            </div>
            <button
              onClick={() => setPage('settings')}
              className="shrink-0 text-xs font-semibold"
              style={{ color: '#fbbf24', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
            >
              Configurer →
            </button>
          </div>
        </div>
      )}

      <main className="relative z-10 max-w-4xl mx-auto px-4 py-10 space-y-10">
        {page === 'settings' ? (
          <Settings onBack={() => setPage('main')} onConfigChange={setConfig} />
        ) : page === 'history' ? (
          <History onBack={() => setPage('main')} />
        ) : (
          <>
            {status === 'idle' && (
              <ApolloForm
                onSubmit={handleSubmit}
                disabled={!isConfigReady}
                configReady={isConfigReady ?? false}
                defaultMaxLeads={config?.max_leads}
                onOpenSettings={() => setPage('settings')}
              />
            )}
            {(status === 'running' || status === 'error') && (
              <PipelineProgress
                status={status}
                latestEvent={latestEvent}
                events={events}
                jobId={jobId}
                error={error}
              />
            )}
            {status === 'done' && result && (
              <>
                <StatsBar result={result} />
                {result.leads.length > 0 && jobId && (
                  <ResultsTable leads={result.leads} jobId={jobId} />
                )}
              </>
            )}
          </>
        )}
      </main>

      <footer
        className="relative z-10 mt-20 py-5 px-4"
        style={{ borderTop: '1px solid rgba(255,255,255,0.07)' }}
      >
        <div className="max-w-4xl mx-auto flex justify-between items-center text-xs" style={{ color: 'rgba(226,232,248,0.25)' }}>
          <div className="flex items-center gap-2 font-medium" style={{ color: 'rgba(226,232,248,0.4)' }}>
            ORSAM
            <span style={{ width: 3, height: 3, borderRadius: '50%', background: 'rgba(226,232,248,0.25)', display: 'inline-block' }} />
            Lead Gen Pipeline v1.0
          </div>
          <span>Confidentiel · 2026</span>
        </div>
      </footer>
    </div>
  )
}
