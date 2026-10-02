import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Copy, Loader2, RefreshCw, X } from 'lucide-react'
import { toast } from 'sonner'
import {
  generateLinkedinMessage,
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

const BASIS_LABEL: Record<LinkedinMessage['language_basis'], string> = {
  pays: "d'après le pays de l'entreprise",
  localisation: "d'après la localisation",
  defaut: 'par défaut, aucun indice de langue',
}

interface Props {
  lead: LinkedinMessageLead
  onClose: () => void
}

/** Generates the message on open, then lets the operator edit and copy it. */
export function LinkedinMessageDialog({ lead, onClose }: Props) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<LinkedinMessage | null>(null)
  const [text, setText] = useState('')
  // Strict Mode mounts effects twice in dev; the guard keeps it to one paid call.
  const started = useRef(false)

  const run = () => {
    setLoading(true)
    setError(null)
    generateLinkedinMessage(lead)
      .then(r => { setResult(r); setText(r.message) })
      .catch(e => setError(e instanceof Error ? e.message : 'La génération du message a échoué'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (started.current) return
    started.current = true
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fullName = [lead.first_name, lead.last_name].filter(Boolean).join(' ')

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

        {loading && (
          <div className="flex items-center justify-center gap-3 py-10" style={{ color: 'var(--th-text-muted)' }}>
            <Loader2 className="w-5 h-5 animate-spin" />
            <span className="text-sm">Rédaction du message…</span>
          </div>
        )}

        {!loading && error && (
          <div className="space-y-3">
            <p className="text-sm rounded-lg px-3 py-2" style={{ background: 'var(--th-warning-soft)', color: 'var(--th-warning-text)' }}>
              {error}
            </p>
            <button
              onClick={run}
              className="inline-flex items-center gap-2 rounded-lg text-sm font-medium"
              style={{ padding: '8px 14px', color: 'var(--th-text-secondary)', background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)', cursor: 'pointer', fontFamily: 'inherit' }}
            >
              <RefreshCw className="w-4 h-4" /> Réessayer
            </button>
          </div>
        )}

        {!loading && !error && result && (
          <div className="space-y-3">
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              rows={7}
              className="surface-input w-full text-sm leading-relaxed"
              style={{ padding: 12, borderRadius: 8, resize: 'vertical', fontFamily: 'inherit' }}
            />
            <p className="text-xs" style={{ color: 'var(--th-text-faint)' }}>
              Langue : {result.language_label} ({BASIS_LABEL[result.language_basis]}). Le message ne reprend que
              les faits sourcés du lead : relisez-le avant l'envoi.
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => navigator.clipboard.writeText(text).then(() => toast.success('Message copié'))}
                className="btn-grad inline-flex items-center gap-2 rounded-lg text-white font-medium text-sm"
                style={{ padding: '8px 16px', border: 'none', cursor: 'pointer', fontFamily: 'inherit' }}
              >
                <Copy className="w-4 h-4" /> Copier
              </button>
              <button
                onClick={run}
                className="inline-flex items-center gap-2 rounded-lg text-sm font-medium"
                style={{ padding: '8px 14px', color: 'var(--th-text-secondary)', background: 'var(--th-glass-inset)', border: '1px solid var(--th-glass-sm-border)', cursor: 'pointer', fontFamily: 'inherit' }}
              >
                <RefreshCw className="w-4 h-4" /> Régénérer
              </button>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
