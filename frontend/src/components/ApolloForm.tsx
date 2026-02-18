import { useState, useEffect } from 'react'
import { Rocket, AlertCircle, CheckCircle2, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getHealth, type HealthCheck } from '@/lib/api'

interface Props {
  onSubmit: (url: string, maxLeads: number, skipGpt: boolean) => void
  disabled?: boolean
}

export function ApolloForm({ onSubmit, disabled }: Props) {
  const [url, setUrl] = useState('')
  const [maxLeads, setMaxLeads] = useState(200)
  const [skipGpt, setSkipGpt] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [health, setHealth] = useState<HealthCheck | null>(null)

  useEffect(() => {
    getHealth().then(setHealth).catch(() => null)
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
      {/* Header */}
      <div className="mb-8 text-center">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-600 mb-4">
          <Rocket className="w-7 h-7 text-white" />
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-gray-900">ORSAM Lead Gen</h1>
        <p className="mt-2 text-gray-500">Pipeline B2B en 5 étapes — Apollo → Enrichissement → IA</p>
      </div>

      {/* Config warnings */}
      {health && hasIssues && (
        <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="flex gap-3">
            <AlertCircle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-medium text-amber-800 mb-1">Configuration incomplète</p>
              {missingKeys.length > 0 && (
                <p className="text-amber-700">Clés API manquantes : <span className="font-mono">{missingKeys.join(', ')}</span></p>
              )}
              {!health.apollo_cookies && (
                <p className="text-amber-700">Cookies Apollo introuvables — créez <span className="font-mono">apollo_cookies.json</span></p>
              )}
            </div>
          </div>
        </div>
      )}

      {health && !hasIssues && (
        <div className="mb-6 rounded-xl border border-green-200 bg-green-50 p-3 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-green-600" />
          <span className="text-sm text-green-700 font-medium">Configuration OK — prêt à lancer</span>
        </div>
      )}

      {/* Main form */}
      <form onSubmit={handleSubmit} className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 space-y-5">
        {/* URL input */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            URL Apollo.io (résultats de recherche)
          </label>
          <textarea
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://app.apollo.io/#/people?..."
            rows={3}
            disabled={disabled}
            className={cn(
              'w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm font-mono',
              'placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
              'resize-none transition-colors',
              disabled && 'opacity-50 cursor-not-allowed bg-gray-50'
            )}
          />
          <p className="mt-1.5 text-xs text-gray-500">
            Effectuez votre recherche sur Apollo.io puis copiez-collez l'URL complète ici.
          </p>
        </div>

        {/* Advanced settings toggle */}
        <div>
          <button
            type="button"
            onClick={() => setShowConfig(!showConfig)}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors"
          >
            <Settings className="w-3.5 h-3.5" />
            Paramètres avancés
            <span className="text-xs">{showConfig ? '▲' : '▼'}</span>
          </button>

          {showConfig && (
            <div className="mt-4 grid grid-cols-2 gap-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
              {/* Max leads */}
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                  Leads max
                </label>
                <input
                  type="number"
                  min={10}
                  max={5000}
                  value={maxLeads}
                  onChange={e => setMaxLeads(Number(e.target.value))}
                  disabled={disabled}
                  className={cn(
                    'w-full rounded-md border border-gray-300 px-3 py-2 text-sm',
                    'focus:outline-none focus:ring-2 focus:ring-blue-500',
                    disabled && 'opacity-50'
                  )}
                />
                <p className="mt-1 text-xs text-gray-400">Apollo scraping limit</p>
              </div>

              {/* Skip GPT */}
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                  Skip enrichissement IA
                </label>
                <div className="flex items-center gap-2 h-9">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={skipGpt}
                    onClick={() => setSkipGpt(!skipGpt)}
                    disabled={disabled}
                    className={cn(
                      'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent',
                      'transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500',
                      skipGpt ? 'bg-blue-600' : 'bg-gray-200',
                      disabled && 'opacity-50 cursor-not-allowed'
                    )}
                  >
                    <span
                      className={cn(
                        'pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform',
                        skipGpt ? 'translate-x-4' : 'translate-x-0'
                      )}
                    />
                  </button>
                  <span className="text-xs text-gray-500">{skipGpt ? 'Désactivé (plus rapide)' : 'Activé'}</span>
                </div>
                <p className="mt-1 text-xs text-gray-400">Saute GPT-4o-mini (étape 5)</p>
              </div>
            </div>
          )}
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={disabled || !url.trim()}
          className={cn(
            'w-full flex items-center justify-center gap-2 rounded-lg px-4 py-3',
            'bg-blue-600 text-white text-sm font-semibold',
            'hover:bg-blue-700 active:bg-blue-800 transition-colors',
            'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2',
            (disabled || !url.trim()) && 'opacity-50 cursor-not-allowed hover:bg-blue-600'
          )}
        >
          <Rocket className="w-4 h-4" />
          Lancer le pipeline
        </button>
      </form>
    </div>
  )
}
