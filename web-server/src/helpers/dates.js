function isoDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function daysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d
}

export const DATE_PRESETS = [
  { label: 'Всё время', value: () => ({ from: '', to: '' }) },
  { label: 'Сегодня', value: () => ({ from: isoDate(new Date()), to: isoDate(new Date()) }) },
  { label: 'Вчера', value: () => ({ from: isoDate(daysAgo(1)), to: isoDate(daysAgo(1)) }) },
  { label: 'Последние 7 дней', value: () => ({ from: isoDate(daysAgo(6)), to: isoDate(new Date()) }) },
  { label: 'Последние 30 дней', value: () => ({ from: isoDate(daysAgo(29)), to: isoDate(new Date()) }) },
  {
    label: 'Этот месяц',
    value: () => {
      const d = new Date()
      return { from: isoDate(new Date(d.getFullYear(), d.getMonth(), 1)), to: isoDate(d) }
    },
  },
  {
    label: 'Прошлый месяц',
    value: () => {
      const d = new Date()
      return {
        from: isoDate(new Date(d.getFullYear(), d.getMonth() - 1, 1)),
        to: isoDate(new Date(d.getFullYear(), d.getMonth(), 0)),
      }
    },
  },
]

export function rangeBounds({ dateFrom, dateTo }) {
  const from = dateFrom ? new Date(`${dateFrom}T00:00:00`).getTime() : 0
  const to = dateTo ? new Date(`${dateTo}T23:59:59.999`).getTime() : 0
  return { from, to }
}

