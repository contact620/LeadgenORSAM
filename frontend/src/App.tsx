import { useState, useEffect, useCallback } from 'react'
import { usePipeline } from '@/hooks/usePipeline'
import { ApolloForm } from '@/components/ApolloForm'
import { PipelineProgress } from '@/components/PipelineProgress'
import { StatsBar } from '@/components/StatsBar'
import { ResultsTable } from '@/components/ResultsTable'
import { Settings } from '@/components/Settings'
import { RotateCcw, Settings2, AlertCircle } from 'lucide-react'
import { getConfig, type ConfigStatus } from '@/lib/api'

type Page = 'main' | 'settings'

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
    <div className="min-h-screen bg-gray-50">
      {/* Top nav */}
      <header className="sticky top-0 z-10 bg-white border-b border-gray-200 px-4">
        <div className="max-w-7xl mx-auto h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-blue-600 flex items-center justify-center">
              <span className="text-white text-xs font-bold">O</span>
            </div>
            <button
              onClick={() => { setPage('main'); reset() }}
              className="font-semibold text-gray-900 hover:text-blue-600 transition-colors"
            >
              ORSAM
            </button>
            <span className="text-gray-400 text-sm hidden sm:inline">/ Lead Generation</span>
          </div>

          <div className="flex items-center gap-2">
            {page === 'main' && status !== 'idle' && (
              <button
                onClick={reset}
                className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors px-3 py-1.5 rounded-lg hover:bg-gray-100"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Nouveau pipeline
              </button>
            )}
            <button
              onClick={() => setPage(page === 'settings' ? 'main' : 'settings')}
              className={`flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-colors ${
                page === 'settings'
                  ? 'bg-blue-50 text-blue-600'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
              }`}
            >
              <Settings2 className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Paramètres</span>
            </button>
          </div>
        </div>
      </header>

      {/* Incomplete config banner */}
      {showBanner && page === 'main' && (
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-2.5">
          <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-sm text-amber-800">
              <AlertCircle className="w-4 h-4 text-amber-600 shrink-0" />
              <span>
                Configuration incomplète —{' '}
                {!config.serper_api_key && <span className="font-mono font-medium">SERPER_API_KEY </span>}
                {!config.anthropic_api_key && <span className="font-mono font-medium">ANTHROPIC_API_KEY </span>}
                {!config.apollo_cookies && <span className="font-mono font-medium">Apollo cookies </span>}
                manquant(s).
              </span>
            </div>
            <button
              onClick={() => setPage('settings')}
              className="shrink-0 text-xs font-medium text-amber-700 underline hover:text-amber-900 transition-colors"
            >
              Configurer →
            </button>
          </div>
        </div>
      )}

      <main className="max-w-7xl mx-auto px-4 py-10 space-y-10">
        {page === 'settings' ? (
          <Settings
            onBack={() => setPage('main')}
            onConfigChange={setConfig}
          />
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

      <footer className="border-t border-gray-200 bg-white mt-20 py-4 px-4">
        <div className="max-w-7xl mx-auto flex justify-between items-center text-xs text-gray-400">
          <span>ORSAM — Lead Gen Pipeline v1.0</span>
          <span>Confidentiel · Fév. 2026</span>
        </div>
      </footer>
    </div>
  )
}
