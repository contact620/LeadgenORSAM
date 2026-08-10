import { useState, useEffect, useCallback } from 'react'
import { toast, Toaster } from 'sonner'
import { usePipeline } from '@/hooks/usePipeline'
import { useTheme } from '@/contexts/ThemeContext'
import { ApolloForm } from '@/components/ApolloForm'
import { PipelineProgress } from '@/components/PipelineProgress'
import { StatsBar } from '@/components/StatsBar'
import { ResultsTable } from '@/components/ResultsTable'
import { Settings } from '@/components/Settings'
import { History } from '@/components/History'
import { Templates } from '@/components/Templates'
import { LeadPools } from '@/components/LeadPools'
import { ThemeToggle } from '@/components/ThemeToggle'
import { RotateCcw, Settings2, AlertCircle, Clock, Bookmark, Database } from 'lucide-react'
import { getConfig, type ConfigStatus, type RerunParams } from '@/lib/api'

type Page = 'main' | 'settings' | 'history' | 'templates' | 'pools'

const navBtnBase: React.CSSProperties = {
  cursor: 'pointer',
  fontFamily: 'inherit',
}

const navBtnInactive: React.CSSProperties = {
  ...navBtnBase,
  color: 'var(--th-text-tertiary)',
  border: '1px solid var(--th-border-medium)',
  background: 'var(--th-glass-inset)',
}

const navBtnActive: React.CSSProperties = {
  ...navBtnBase,
  color: 'var(--th-primary)',
  background: 'var(--th-primary-soft)',
  border: '1px solid var(--th-primary-border)',
}

export default function App() {
  const { state, startPipeline, cancelPipeline, reset } = usePipeline()
  const { status, jobId, events, latestEvent, result, error } = state
  const { theme } = useTheme()

  const [page, setPage] = useState<Page>('main')
  const [config, setConfig] = useState<ConfigStatus | null>(null)
  const [prefill, setPrefill] = useState<RerunParams | null>(null)

  const refreshConfig = useCallback(() => {
    getConfig().then(setConfig).catch((err) => {
      toast.error('Impossible de charger la configuration', {
        description: err instanceof Error ? err.message : 'Le backend est-il lancé ?',
      })
    })
  }, [])

  useEffect(() => { refreshConfig() }, [refreshConfig])

  const handleSubmit = (req: import('@/lib/api').RunRequest) => {
    setPrefill(null)
    startPipeline(req)
  }

  const handleRerun = (params: RerunParams) => {
    setPrefill(params)
    setPage('main')
    reset()
    toast.info('Paramètres pré-remplis depuis l\'historique')
  }

  const handleTemplateRun = () => {
    // Template was launched via API, need to connect SSE
    setPage('main')
  }

  const isConfigReady =
    config !== null &&
    config.serper_api_key &&
    config.anthropic_api_key &&
    config.apollo_cookies

  const showBanner = config !== null && !isConfigReady

  return (
    <div className="min-h-screen" style={{ background: 'var(--th-bg)' }}>
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
        style={{ borderBottom: '1px solid var(--th-border-medium)', background: 'linear-gradient(90deg, var(--th-nav-bg), var(--th-nav-bg))' }}
      >
        <div className="max-w-5xl mx-auto h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center text-white text-sm font-bold flex-shrink-0"
              style={{
                background: 'linear-gradient(135deg, #4d9fff 0%, #9b6bff 100%)',
                boxShadow: '0 4px 16px var(--th-primary-glow)',
              }}
            >
              BC
            </div>
            <button
              onClick={() => { setPage('main'); reset() }}
              className="font-semibold transition-colors hover:opacity-80"
              style={{ color: 'var(--th-text-primary)', fontSize: '15px', letterSpacing: '-0.01em', background: 'none', border: 'none', cursor: 'pointer' }}
            >
              Boxcom
            </button>
            <span
              className="text-xs font-semibold px-2 py-0.5 rounded-full hidden sm:inline"
              style={{
                color: 'var(--th-primary)',
                background: 'var(--th-primary-soft)',
                border: '1px solid var(--th-primary-border)',
                letterSpacing: '0.05em',
                textTransform: 'uppercase',
              }}
            >
              Lead Gen
            </span>
          </div>

          <div className="flex items-center gap-2">
            <ThemeToggle />
            {page === 'main' && status !== 'idle' && (
              <button
                onClick={reset}
                className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-all"
                style={navBtnInactive}
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Nouveau</span>
              </button>
            )}
            <button
              onClick={() => setPage(page === 'pools' ? 'main' : 'pools')}
              className={`flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-all ${page === 'pools' ? 'nav-btn-active-line' : ''}`}
              style={page === 'pools' ? navBtnActive : navBtnInactive}
            >
              <Database className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Pools</span>
            </button>
            <button
              onClick={() => setPage(page === 'templates' ? 'main' : 'templates')}
              className={`flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-all ${page === 'templates' ? 'nav-btn-active-line' : ''}`}
              style={page === 'templates' ? navBtnActive : navBtnInactive}
            >
              <Bookmark className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Templates</span>
            </button>
            <button
              onClick={() => setPage(page === 'history' ? 'main' : 'history')}
              className={`flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-all ${page === 'history' ? 'nav-btn-active-line' : ''}`}
              style={page === 'history' ? navBtnActive : navBtnInactive}
            >
              <Clock className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Historique</span>
            </button>
            <button
              onClick={() => setPage(page === 'settings' ? 'main' : 'settings')}
              className={`flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-all ${page === 'settings' ? 'nav-btn-active-line' : ''}`}
              style={page === 'settings' ? navBtnActive : navBtnInactive}
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
            background: 'var(--th-warning-soft)',
            borderBottom: '1px solid var(--th-warning-border)',
          }}
        >
          <div className="max-w-4xl mx-auto flex items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--th-warning-text)' }}>
              <AlertCircle className="w-4 h-4 shrink-0" style={{ color: 'var(--th-warning)' }} />
              <span>
                Configuration incomplète —{' '}
                {!config.serper_api_key && (
                  <span className="font-mono font-medium" style={{ color: 'var(--th-warning)' }}>SERPER_API_KEY </span>
                )}
                {!config.anthropic_api_key && (
                  <span className="font-mono font-medium" style={{ color: 'var(--th-warning)' }}>ANTHROPIC_API_KEY </span>
                )}
                {!config.apollo_cookies && (
                  <span className="font-mono font-medium" style={{ color: 'var(--th-warning)' }}>Apollo cookies </span>
                )}
                manquant(s).
              </span>
            </div>
            <button
              onClick={() => setPage('settings')}
              className="shrink-0 text-xs font-semibold"
              style={{ color: 'var(--th-warning)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
            >
              Configurer →
            </button>
          </div>
        </div>
      )}

      <main className="relative z-10 max-w-6xl mx-auto px-4 py-10 space-y-10 animate-fade-in">
        {page === 'settings' ? (
          <Settings onBack={() => setPage('main')} onConfigChange={setConfig} />
        ) : page === 'history' ? (
          <History onBack={() => setPage('main')} onRerun={handleRerun} />
        ) : page === 'templates' ? (
          <Templates onBack={() => setPage('main')} onRun={handleTemplateRun} />
        ) : page === 'pools' ? (
          <LeadPools onBack={() => setPage('main')} onEnrichStarted={() => setPage('main')} />
        ) : (
          <>
            {status === 'idle' && (
              <ApolloForm
                onSubmit={handleSubmit}
                disabled={!isConfigReady}
                configReady={isConfigReady ?? false}
                defaultMaxLeads={config?.max_leads}
                onOpenSettings={() => setPage('settings')}
                prefill={prefill}
                services={config?.services ?? []}
              />
            )}
            {(status === 'running' || status === 'error') && (
              <PipelineProgress
                status={status}
                latestEvent={latestEvent}
                events={events}
                jobId={jobId}
                error={error}
                startedAt={state.startedAt}
                onCancel={cancelPipeline}
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
        style={{ borderTop: '1px solid var(--th-border-medium)' }}
      >
        <div className="max-w-4xl mx-auto flex justify-between items-center text-xs" style={{ color: 'var(--th-text-faint)' }}>
          <div className="flex items-center gap-2 font-medium" style={{ color: 'var(--th-text-quaternary)' }}>
            Boxcom
            <span style={{ width: 3, height: 3, borderRadius: '50%', background: 'var(--th-text-faint)', display: 'inline-block' }} />
            Lead Gen Pipeline v1.0
          </div>
          <span>Confidentiel · 2026</span>
        </div>
      </footer>

      <Toaster
        theme={theme}
        position="bottom-right"
        toastOptions={{
          style: {
            background: 'var(--th-toast-bg)',
            border: '1px solid var(--th-toast-border)',
            color: 'var(--th-text-primary)',
          },
        }}
      />
    </div>
  )
}
