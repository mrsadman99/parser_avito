import { useEffect, useRef, useState } from 'react'
import { DATE_PRESETS } from '../helpers/dates'

export default function DateRangePicker({ from, to, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    function onDocClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  const label = from || to ? `${from || '…'} — ${to || '…'}` : 'Публикация: любая дата'

  return (
    <div className="drp" ref={ref}>
      <button type="button" className="drp-toggle" onClick={() => setOpen((v) => !v)}>
        {label} ▾
      </button>
      {open && (
        <div className="drp-panel">
          <div className="drp-presets">
            {DATE_PRESETS.map((p) => (
              <button
                type="button"
                key={p.label}
                onClick={() => { onChange(p.value()); setOpen(false) }}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="drp-dates">
            <label>С
              <input
                type="date"
                value={from}
                max={to || undefined}
                onChange={(e) => onChange({ from: e.target.value, to })}
              />
            </label>
            <label>По
              <input
                type="date"
                value={to}
                min={from || undefined}
                onChange={(e) => onChange({ from, to: e.target.value })}
              />
            </label>
          </div>
          <div className="drp-actions">
            <button type="button" onClick={() => { onChange({ from: '', to: '' }); setOpen(false) }}>Сбросить</button>
            <button type="button" onClick={() => setOpen(false)}>Готово</button>
          </div>
        </div>
      )}
    </div>
  )
}

