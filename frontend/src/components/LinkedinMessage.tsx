import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Copy, Loader2, MessageSquare, RefreshCw, X } from 'lucide-react'
import { toast } from 'sonner'
import {
  generateLinkedinMessage,
  suggestLinkedinLanguage,
  type LanguageBasis,
  type LinkedinLanguage,
  type LinkedinMessage,
  type LinkedinMessageLead,
} from '@/lib/api'

// Why the generate button is off. The message may only restate sourced facts,
// and the angle is the only place the pipeline puts them together — without
// one there is nothing to say. Shown as readable text, never as an error.
export const NO_ANGLE_REASON =
  "Pas d'angle de conversion pour ce lead : la recherche IA était désactivée ou n'a rien produit. Sans angle, le message n'aurait aucun fait sur lequel s'appuyer."

export function hasAngle(lead: LinkedinMessageLead): boolean {
  return Boolean(lead.conversion_angle?.trim())
}

// Languages offered, in order of weight for the ICP zones (config/icp_rules.json):
// French (Morocco, francophone Africa, France, Belgium, Switzerland, Luxembourg,
// Canada), English (anglophone Africa, Canada), Arabic (Maghreb, North Africa,
// Gulf), Portuguese (lusophone Africa), Dutch (Flanders). Spanish, German and
// Italian stay because the backend deduction can pick them from a country
// outside the zones, and a pre-selected value has to be selectable.
export const LINKEDIN_LANGUAGES: { code: string; label: string }[] = [
  { code: 'fr', label: 'Français' },
  { code: 'en', label: 'Anglais' },
  { code: 'ar', label: 'Arabe' },
  { code: 'pt', label: 'Portugais' },
  { code: 'es', label: 'Espagnol' },
  { code: 'nl', label: 'Néerlandais' },
  { code: 'de', label: 'Allemand' },
  { code: 'it', label: 'Italien' },
]

const BASIS_LABEL: Record<LanguageBasis, string> = {
  pays: "déduite d'après le pays de l'entreprise",
  localisation: "déduite d'après la localisation",
  defaut: 'par défaut : aucun indice de langue dans les données du lead',
  choix: 'choisie par vous',
}

const labelOf = (code: string) => LINKEDIN_LANGUAGES.find(l => l.code === code)?.label ?? code

interface Props {
  lead: LinkedinMessageLead
  onClose: () => void
}

/**
 * The operator picks the language; the deduction (country fact, then declared
 * location, then French) only pre-selects it. Nothing is generated until the
 * button is pressed, so the deduced language is seen before it is used.
 */
export function LinkedinMessageDialog({ lead, onClose }: Props) {
  const [suggestion, setSuggestion] = useState<LinkedinLanguage | null>(null)
  const [lang, setLang] = useState('fr')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<LinkedinMessage | null>(null)
  const [generatedLang, setGeneratedLang] = useState<string | null>(null)
  const [text, setText] = useState('')
  // Strict Mode mounts effects twice in dev; the guard keeps it to one call.
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    suggestLinkedinLanguage(lead)
      .then(s => { setSuggestion(s); setLang(s.language) })
      // Without a suggestion the French default is shown as such, not hidden.
      .catch(() => setSuggestion({ language: 'fr', language_label: 'français', language_basis: 'defaut' }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const generate = () => {
    const requested = lang
    setLoading(true)
    setError(null)
    generateLinkedinMessage(lead, requested)
      .then(r => { setResult(r); setText(r.message); setGeneratedLang(requested) })
      .catch(e => setError(e instanceof Error ? e.message : 'La génération du message a échoué'))
      .finally(() => setLoading(false))
  }

  // A message written in another language than the selector now shows is stale:
  // it stays visible for reference but cannot be copied as if it matched.
  const stale = result !== null && generatedLang !== lang
  const fullName = [lead.first_name, lead.last_name].filter(Boolean).join(' ')
  const basisNote = suggestion
    ? lang === suggestion.language
      ? `Langue ${BASIS_LABEL[suggestion.language_basis]}.`
      : `Langue ${BASIS_LABEL.choix} (déduite : ${labelOf(suggestion.language).toLowerCase()}).`
    : 'Déduction de la langue en cours…'

  // Portalled to <body>: an ancestor with a transform or filter (page
  // animations, the lead modal's backdrop blur) would otherwise become the
  // containing block of this fixed overlay and offset or clip it.
  return createPortal(
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)' }}
      // Stop here: this dialog can sit inside the lead modal, whose own
      // backdrop would otherwise close it along with this one.
      onClick={e => { e.stopPropagation(); onClose() }}
    >
      <div
        className="w-full max-w-lg rounded-xl p-5"
        style={{ background: 'var(--th-bg)', border: '1px solid var(--th-glass-border)', boxShadow: '0 32px 80px rgba(0,0,0,0.4)' }}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <h3 className="text-base font-semibold" style={{ color: 'var(--th-text-primary)' }}>Message LinkedIn</h3>
            {fullName && <p className="text-xs mt-0.5" style={{ color: 'var(--th-text-muted)' }}>pour {fullName}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Fermer"
            className="p-1.5 rounded-lg"
            style={{ color: 'var(--th-text-muted)', background: 'var(--th-glass-inset)', border: 'none', cursor: 'pointer' }}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Language + generate */}
        <div className="flex items-center gap-2 flex-wrap">
          <label className="text-xs font-semibold" htmlFor="linkedin-lang" style={{ color: 'var(--th-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Langue
          </label>
          <select
            id="linkedin-lang"
            value={lang}
            onChange={e => setLang(e.target.value)}
            disabled={loading || !suggestion}
            className="surface-input text-sm"
            style={{ padding: '7px 10px', borderRadius: 8, fontFamily: 'inherit' }}
          >
            {LINKEDIN_LANGUAGES.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
          <button
            onClick={generate}
            disabled={loading || !suggestion}
            className="btn-grad inline-flex items-center gap-2 rounded-lg text-white font-medium text-sm"
            style={{ padding: '8px 16px', border: 'none', cursor: loading || !suggestion ? 'not-allowed' : 'pointer', opacity: loading || !suggestion ? 0.6 : 1, fontFamily: 'inherit' }}
          >
            {result
              ? <><RefreshCw className="w-4 h-4" /> {stale ? `Générer en ${labelOf(lang).toLowerCase()}` : 'Régénérer'}</>
              : <><MessageSquare className="w-4 h-4" /> Générer le message</>}
          </button>
        </div>
        <p className="text-xs mt-2" style={{ color: 'var(--th-text-faint)' }}>{basisNote}</p>

        {loading && (
          <div className="flex items-center justify-center gap-3 py-8" style={{ color: 'var(--th-text-muted)' }}>
            <Loader2 className="w-5 h-5 animate-spin" />
            <span className="text-sm">Rédaction du message…</span>
          </div>
        )}

        {!loading && error && (
          <p className="text-sm rounded-lg px-3 py-2 mt-3" style={{ background: 'var(--th-warning-soft)', color: 'var(--th-warning-text)' }}>
            {error}
          </p>
        )}

        {!loading && result && (
          <div className="space-y-3 mt-3">
            {stale && (
              <p className="text-xs rounded-lg px-3 py-2" style={{ background: 'var(--th-warning-soft)', color: 'var(--th-warning-text)' }}>
                Ce message est en {labelOf(generatedLang ?? '').toLowerCase()} : la langue a changé, générez-le de nouveau.
              </p>
            )}
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              rows={7}
              dir="auto"
              disabled={stale}
              className="surface-input w-full text-sm leading-relaxed"
              style={{ padding: 12, borderRadius: 8, resize: 'vertical', fontFamily: 'inherit', opacity: stale ? 0.5 : 1 }}
            />
            <p className="text-xs" style={{ color: 'var(--th-text-faint)' }}>
              Le message ne reprend que les faits sourcés du lead : relisez-le avant l'envoi.
            </p>
            <button
              onClick={() => navigator.clipboard.writeText(text).then(() => toast.success('Message copié'))}
              disabled={stale}
              className="inline-flex items-center gap-2 rounded-lg text-sm font-medium"
              style={{ padding: '8px 16px', color: 'var(--th-text-secondary)', background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)', cursor: stale ? 'not-allowed' : 'pointer', opacity: stale ? 0.5 : 1, fontFamily: 'inherit' }}
            >
              <Copy className="w-4 h-4" /> Copier
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
