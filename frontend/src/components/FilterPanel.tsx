import { useState, useRef, type KeyboardEvent } from 'react'
import { X } from 'lucide-react'
import type { ApolloFilters } from '@/lib/api'

interface FilterPanelProps {
  value: ApolloFilters
  onChange: (filters: ApolloFilters) => void
  disabled?: boolean
}

// ── Mappings ────────────────────────────────────────────────────────────────

const SENIORITY_OPTIONS: { label: string; value: string }[] = [
  { label: 'Owner', value: 'owner' },
  { label: 'Founder', value: 'founder' },
  { label: 'C-Suite', value: 'c_suite' },
  { label: 'Partner', value: 'partner' },
  { label: 'VP', value: 'vp' },
  { label: 'Head', value: 'head' },
  { label: 'Director', value: 'director' },
  { label: 'Manager', value: 'manager' },
  { label: 'Senior', value: 'senior' },
  { label: 'Entry', value: 'entry' },
]

const EMPLOYEE_RANGE_OPTIONS: { label: string; value: string }[] = [
  { label: '1-10', value: '1,10' },
  { label: '11-20', value: '11,20' },
  { label: '21-50', value: '21,50' },
  { label: '51-100', value: '51,100' },
  { label: '101-200', value: '101,200' },
  { label: '201-500', value: '201,500' },
  { label: '501-1K', value: '501,1000' },
  { label: '1K-5K', value: '1001,5000' },
  { label: '5K-10K', value: '5001,10000' },
  { label: '10K+', value: '10001,1000000' },
]

const EMAIL_STATUS_OPTIONS: { label: string; value: string }[] = [
  { label: 'Verified', value: 'verified' },
  { label: 'Guessed', value: 'guessed' },
  { label: 'Unavailable', value: 'unavailable' },
]

// ── TagInput ────────────────────────────────────────────────────────────────

function TagInput({
  label,
  placeholder,
  tags,
  onAdd,
  onRemove,
  disabled,
}: {
  label: string
  placeholder: string
  tags: string[]
  onAdd: (tag: string) => void
  onRemove: (index: number) => void
  disabled?: boolean
}) {
  const [input, setInput] = useState('')
  const ref = useRef<HTMLInputElement>(null)

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && input.trim()) {
      e.preventDefault()
      onAdd(input.trim())
      setInput('')
    }
    if (e.key === 'Backspace' && !input && tags.length > 0) {
      onRemove(tags.length - 1)
    }
  }

  return (
    <div className="mb-4">
      <label className="block text-xs font-medium mb-2" style={{ color: 'rgba(226,232,248,0.5)' }}>
        {label}
      </label>
      <div
        className="surface-input flex flex-wrap items-center gap-1.5 cursor-text"
        style={{ padding: '8px 10px', minHeight: 40, borderRadius: 10 }}
        onClick={() => ref.current?.focus()}
      >
        {tags.map((tag, i) => (
          <span
            key={`${tag}-${i}`}
            className="inline-flex items-center gap-1 text-xs font-medium rounded-md"
            style={{
              background: 'rgba(77,159,255,0.12)',
              border: '1px solid rgba(77,159,255,0.25)',
              color: '#8bb8ff',
              padding: '3px 8px',
            }}
          >
            {tag}
            {!disabled && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onRemove(i) }}
                className="hover:opacity-80"
                style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'flex' }}
              >
                <X size={12} style={{ color: '#8bb8ff' }} />
              </button>
            )}
          </span>
        ))}
        <input
          ref={ref}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={tags.length === 0 ? placeholder : ''}
          disabled={disabled}
          className="flex-1 min-w-[100px] bg-transparent border-none outline-none text-sm"
          style={{ color: '#e2e8f8', fontFamily: 'inherit', padding: '2px 0' }}
        />
      </div>
    </div>
  )
}

// ── CheckboxGroup ───────────────────────────────────────────────────────────

function CheckboxGroup({
  label,
  options,
  selected,
  onChange,
  disabled,
  columns = 5,
}: {
  label: string
  options: { label: string; value: string }[]
  selected: string[]
  onChange: (values: string[]) => void
  disabled?: boolean
  columns?: number
}) {
  const toggle = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter((v) => v !== value))
    } else {
      onChange([...selected, value])
    }
  }

  return (
    <div className="mb-4">
      <label className="block text-xs font-medium mb-2" style={{ color: 'rgba(226,232,248,0.5)' }}>
        {label}
      </label>
      <div
        className="grid gap-2"
        style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
      >
        {options.map((opt) => {
          const checked = selected.includes(opt.value)
          return (
            <button
              key={opt.value}
              type="button"
              disabled={disabled}
              onClick={() => toggle(opt.value)}
              className="text-xs font-medium rounded-lg transition-all duration-150 text-center"
              style={{
                padding: '7px 6px',
                background: checked ? 'rgba(77,159,255,0.12)' : 'rgba(255,255,255,0.03)',
                border: `1px solid ${checked ? 'rgba(77,159,255,0.3)' : 'rgba(255,255,255,0.08)'}`,
                color: checked ? '#8bb8ff' : 'rgba(226,232,248,0.4)',
                cursor: disabled ? 'not-allowed' : 'pointer',
                opacity: disabled ? 0.4 : 1,
              }}
            >
              {opt.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── FilterPanel ─────────────────────────────────────────────────────────────

export function FilterPanel({ value, onChange, disabled }: FilterPanelProps) {
  const update = <K extends keyof ApolloFilters>(key: K, val: ApolloFilters[K]) => {
    onChange({ ...value, [key]: val })
  }

  return (
    <div>
      <TagInput
        label="Titres de poste"
        placeholder="Ex: CEO, Directeur Commercial, CTO..."
        tags={value.person_titles}
        onAdd={(tag) => update('person_titles', [...value.person_titles, tag])}
        onRemove={(i) => update('person_titles', value.person_titles.filter((_, idx) => idx !== i))}
        disabled={disabled}
      />

      <TagInput
        label="Localisations"
        placeholder="Ex: France, Paris, United States..."
        tags={value.locations}
        onAdd={(tag) => update('locations', [...value.locations, tag])}
        onRemove={(i) => update('locations', value.locations.filter((_, idx) => idx !== i))}
        disabled={disabled}
      />

      <TagInput
        label="Industries"
        placeholder="Ex: technology, real estate, saas..."
        tags={value.industries}
        onAdd={(tag) => update('industries', [...value.industries, tag])}
        onRemove={(i) => update('industries', value.industries.filter((_, idx) => idx !== i))}
        disabled={disabled}
      />

      <TagInput
        label="Mots-cles"
        placeholder="Ex: marketing, growth, B2B..."
        tags={value.keywords}
        onAdd={(tag) => update('keywords', [...value.keywords, tag])}
        onRemove={(i) => update('keywords', value.keywords.filter((_, idx) => idx !== i))}
        disabled={disabled}
      />

      <CheckboxGroup
        label="Taille de l'entreprise"
        options={EMPLOYEE_RANGE_OPTIONS}
        selected={value.employee_ranges}
        onChange={(vals) => update('employee_ranges', vals)}
        disabled={disabled}
        columns={5}
      />

      <CheckboxGroup
        label="Niveau hierarchique"
        options={SENIORITY_OPTIONS}
        selected={value.seniority}
        onChange={(vals) => update('seniority', vals)}
        disabled={disabled}
        columns={5}
      />

      <CheckboxGroup
        label="Statut email"
        options={EMAIL_STATUS_OPTIONS}
        selected={value.email_status}
        onChange={(vals) => update('email_status', vals)}
        disabled={disabled}
        columns={3}
      />
    </div>
  )
}
