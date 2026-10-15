export function toLinkForm(link) {
  return {
    url: link.url,
    min_price: link.min_price == null ? '' : String(link.min_price),
    max_price: link.max_price == null ? '' : String(link.max_price),
    white_list: [...(link.white_list || [])],
    black_list: [...(link.black_list || [])],
    geo: link.geo || '',
    start_date: link.start_date || '',
    ignore_reserv: link.ignore_reserv == null ? true : Boolean(link.ignore_reserv),
    ignore_promotion: Boolean(link.ignore_promotion),
    username: link.username || '',
  }
}

export function parseForm(form) {
  return {
    url: form.url.trim(),
    min_price: form.min_price === '' ? null : Number(form.min_price),
    max_price: form.max_price === '' ? null : Number(form.max_price),
    white_list: form.white_list,
    black_list: form.black_list,
    geo: form.geo.trim() || null,
    start_date: form.start_date.trim() || null,
    ignore_reserv: Boolean(form.ignore_reserv),
    ignore_promotion: Boolean(form.ignore_promotion),
    username: form.username.trim(),
  }
}

export function fmtScan(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('ru-RU', { hour12: false })
}

export function fmtMs(ms) {
  if (ms == null || ms === '') return ''
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('ru-RU', { hour12: false })
}

function searchQuery(url) {
  try {
    const qs = (url || '').split('?')[1]
    if (!qs) return ''
    const q = new URLSearchParams(qs.split('#')[0]).get('q')
    return q ? q.trim() : ''
  } catch {
    return ''
  }
}

export function linkLabel(link) {
  return searchQuery(link.url) || link.url
}

