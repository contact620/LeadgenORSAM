import { usePipeline } from '@/hooks/usePipeline'
import { ApolloForm } from '@/components/ApolloForm'
import { PipelineProgress } from '@/components/PipelineProgress'
import { StatsBar } from '@/components/StatsBar'
import { ResultsTable } from '@/components/ResultsTable'
import { RotateCcw } from 'lucide-react'

export default function App() {
  const { state, startPipeline, reset } = usePipeline()
  const { status, jobId, events, latestEvent, result, error } = state

  const handleSubmit = (url: string, maxLeads: number, skipGpt: boolean) => {
    startPipeline({ url, max_leads: maxLeads, skip_gpt: skipGpt })
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top nav */}
      <header className="sticky top-0 z-10 bg-white border-b border-gray-200 px-4">
        <div className="max-w-7xl mx-auto h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-blue-600 flex items-center justify-center">
              <span className="text-white text-xs font-bold">O</span>
            </div>
            <span className="font-semibold text-gray-900">ORSAM</span>
            <span className="text-gray-400 text-sm hidden sm:inline">/ Lead Generation</span>
          </div>

          {status !== 'idle' && (
            <button
              onClick={reset}
              className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors px-3 py-1.5 rounded-lg hover:bg-gray-100"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Nouveau pipeline
            </button>
          )}
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-10 space-y-10">
        {status === 'idle' && (
          <ApolloForm onSubmit={handleSubmit} disabled={false} />
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
