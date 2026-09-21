import { useEffect, useRef, useState } from 'react'
import { api } from './api'

const RUSSIAN_CITIES = [
  'Москва', 'Санкт-Петербург', 'Новосибирск', 'Екатеринбург', 'Казань',
  'Нижний Новгород', 'Челябинск', 'Самара', 'Омск', 'Ростов-на-Дону',
  'Уфа', 'Красноярск', 'Воронеж', 'Пермь', 'Волгоград', 'Краснодар',
  'Саратов', 'Тюмень', 'Тольятти', 'Ижевск', 'Барнаул', 'Ульяновск',
  'Иркутск', 'Хабаровск', 'Ярославль', 'Владивосток', 'Махачкала',
  'Томск', 'Оренбург', 'Кемерово', 'Новокузнецк', 'Рязань', 'Астрахань',
  'Набережные Челны', 'Пенза', 'Липецк', 'Киров', 'Чебоксары', 'Тула',
  'Калининград', 'Курск', 'Севастополь', 'Сочи', 'Ставрополь', 'Улан-Удэ',
  'Тверь', 'Магнитогорск', 'Иваново', 'Брянск', 'Белгород', 'Сургут',
  'Владимир', 'Нижний Тагил', 'Архангельск', 'Чита', 'Симферополь', 'Калуга',
  'Смоленск', 'Волжский', 'Якутск', 'Саранск', 'Череповец', 'Курган', 'Орёл',
  'Вологда', 'Владикавказ', 'Подольск', 'Грозный', 'Мурманск', 'Тамбов',
  'Стерлитамак', 'Петрозаводск', 'Кострома', 'Нижневартовск', 'Новороссийск',
  'Йошкар-Ола', 'Таганрог', 'Комсомольск-на-Амуре', 'Сыктывкар', 'Нальчик',
  'Шахты', 'Братск', 'Дзержинск', 'Орск', 'Ангарск', 'Благовещенск', 'Химки',
  'Старый Оскол', 'Великий Новгород', 'Энгельс', 'Псков', 'Бийск',
]

const EMPTY = { url: '', min_price: '', max_price: '', white_list: [], black_list: [], geo: '', start_date: '', ignore_reserv: true, ignore_promotion: false, username: '' }

const SORT_FIELDS = {
  price: { label: 'Цена', key: (a) => a.price ?? 0 },
  scanned_at: { label: 'Время парсинга', key: (a) => a.scanned_at ?? '' },
  sort_time: { label: 'Публикация', key: (a) => a.sort_time ?? 0 },
  seller_reviews: { label: 'Оценок', key: (a) => a.seller_reviews ?? 0 },
  seller_rating: { label: 'Рейтинг', key: (a) => a.seller_rating ?? 0 },
  has_delivery: { label: 'Доставка', key: (a) => a.has_delivery ?? 0 },
  city: { label: 'Расположение', key: (a) => a.city ?? '' },
}

const ADS_FILTERS_EMPTY = { deliveryOnly: false, city: '', dateFrom: '', dateTo: '' }

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

const DATE_PRESETS = [
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

function rangeBounds({ dateFrom, dateTo }) {
  const from = dateFrom ? new Date(`${dateFrom}T00:00:00`).getTime() : 0
  const to = dateTo ? new Date(`${dateTo}T23:59:59.999`).getTime() : 0
  return { from, to }
}

function DateRangePicker({ from, to, onChange }) {
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

function toLinkForm(link) {
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

function parseForm(form) {
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

function fmtScan(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('ru-RU', { hour12: false })
}

function fmtMs(ms) {
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

function linkLabel(link) {
  return searchQuery(link.url) || link.url
}

function TagInput({ value, onChange, placeholder }) {
  const [text, setText] = useState('')
  const [editingIndex, setEditingIndex] = useState(null)
  const [editText, setEditText] = useState('')
  const skipBlurRef = useRef(false)
  const tags = Array.isArray(value) ? value : []

  function addMany(words) {
    const next = [...tags]
    for (const word of words) {
      const w = word.trim()
      if (w && !next.includes(w)) next.push(w)
    }
    if (next.length !== tags.length) onChange(next)
  }

  function commit() {
    addMany([text])
    setText('')
  }

  function handleChange(e) {
    const raw = e.target.value
    if (raw.includes(',')) {
      const parts = raw.split(',')
      const last = parts.pop()
      addMany(parts)
      setText(last)
    } else {
      setText(raw)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter') {
      e.preventDefault()
      commit()
    } else if (e.key === 'Backspace' && text === '' && tags.length > 0) {
      onChange(tags.slice(0, -1))
    }
  }

  function startEdit(index) {
    skipBlurRef.current = false
    setEditingIndex(index)
    setEditText(tags[index])
  }

  function cancelEdit() {
    skipBlurRef.current = true
    setEditingIndex(null)
    setEditText('')
  }

  function commitEdit() {
    if (skipBlurRef.current) {
      skipBlurRef.current = false
      return
    }
    if (editingIndex === null) return
    const word = editText.trim()
    const next = [...tags]
    if (!word || next.some((t, i) => i !== editingIndex && t === word)) {
      next.splice(editingIndex, 1)
    } else {
      next[editingIndex] = word
    }
    onChange(next)
    cancelEdit()
  }

  function handleEditKeyDown(e) {
    if (e.key === 'Enter') {
      e.preventDefault()
      commitEdit()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      cancelEdit()
    }
  }

  return (
    <div className="tag-input">
      <div className="tags">
        {tags.map((tag, index) => (
          editingIndex === index ? (
            <input
              key={`edit-${index}`}
              className="tag-edit"
              value={editText}
              autoFocus
              onChange={(e) => setEditText(e.target.value)}
              onKeyDown={handleEditKeyDown}
              onBlur={commitEdit}
            />
          ) : (
            <span
              className="tag"
              key={tag}
              title="Нажмите, чтобы изменить"
              onClick={() => startEdit(index)}
            >
              {tag}
              <button
                type="button"
                className="tag-remove"
                onClick={(e) => {
                  e.stopPropagation()
                  onChange(tags.filter((t) => t !== tag))
                }}
              >×</button>
            </span>
          )
        ))}
        <input
          className="tag-field"
          value={text}
          placeholder={tags.length === 0 ? placeholder : ''}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onBlur={commit}
        />
      </div>
    </div>
  )
}

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '')
  const [isAdmin, setIsAdmin] = useState(localStorage.getItem('is_admin') === '1')
  const [links, setLinks] = useState([])
  const [view, setView] = useState('links')
  const [selectedLink, setSelectedLink] = useState(null)
  const [ads, setAds] = useState([])
  const [adsFilters, setAdsFilters] = useState(ADS_FILTERS_EMPTY)
  const [sortKey, setSortKey] = useState('scanned_at')
  const [sortDesc, setSortDesc] = useState(true)
  const [showAddForm, setShowAddForm] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [editingId, setEditingId] = useState(null)
  const [error, setError] = useState('')
  const [authMode, setAuthMode] = useState('login')
  const [auth, setAuth] = useState({ username: '', password: '' })

  async function loadLinks() {
    try {
      setLinks(await api('/api/links', { token }))
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    if (token) loadLinks()
  }, [token])

  async function handleAuth(e) {
    e.preventDefault()
    setError('')
    try {
      const res = await api(`/api/${authMode}`, { method: 'POST', body: auth })
      localStorage.setItem('token', res.token)
      if (res.is_admin) localStorage.setItem('is_admin', '1')
      else localStorage.removeItem('is_admin')
      setToken(res.token)
      setIsAdmin(Boolean(res.is_admin))
    } catch (err) {
      setError(err.message)
    }
  }

  function logout() {
    localStorage.removeItem('token')
    localStorage.removeItem('is_admin')
    setToken('')
    setIsAdmin(false)
    setLinks([])
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    const payload = parseForm(form)
    if (!payload.url) {
      setError('Укажите ссылку')
      return
    }
    if (isAdmin && editingId === null && !payload.username) {
      setError('Укажите логин владельца')
      return
    }
    try {
      if (editingId) {
        await api(`/api/links/${editingId}`, { method: 'PUT', body: payload, token })
      } else {
        await api('/api/links', { method: 'POST', body: payload, token })
      }
      setForm(EMPTY)
      setEditingId(null)
      setShowAddForm(false)
      await loadLinks()
    } catch (err) {
      setError(err.message)
    }
  }

  function startEdit(link) {
    setEditingId(link.id)
    setForm(toLinkForm(link))
  }

  async function handleDelete(id) {
    try {
      await api(`/api/links/${id}`, { method: 'DELETE', token })
      if (editingId === id) {
        setEditingId(null)
        setForm(EMPTY)
      }
      await loadLinks()
    } catch (err) {
      setError(err.message)
    }
  }

  async function openAds(link) {
    setError('')
    setSelectedLink(link)
    setView('ads')
    setAdsFilters(ADS_FILTERS_EMPTY)
    try {
      setAds(await api(`/api/ads?url=${encodeURIComponent(link.url)}`, { token }))
    } catch (err) {
      setError(err.message)
    }
  }

  function backToLinks() {
    setView('links')
    setSelectedLink(null)
    setAds([])
    setAdsFilters(ADS_FILTERS_EMPTY)
  }

  function toggleSort(key) {
    if (sortKey === key) setSortDesc(!sortDesc)
    else {
      setSortKey(key)
      setSortDesc(true)
    }
  }

  const { from: dateFromTs, to: dateToTs } = rangeBounds(adsFilters)
  const filteredAds = ads.filter((ad) => {
    if (adsFilters.deliveryOnly && !ad.has_delivery) return false
    if (adsFilters.city && !String(ad.city || '').toLowerCase().includes(adsFilters.city.toLowerCase())) return false
    if (dateFromTs && !(ad.sort_time && ad.sort_time >= dateFromTs)) return false
    if (dateToTs && !(ad.sort_time && ad.sort_time <= dateToTs)) return false
    return true
  })

  const sortedAds = [...filteredAds].sort((a, b) => {
    const f = SORT_FIELDS[sortKey].key
    const va = f(a)
    const vb = f(b)
    let cmp = 0
    if (typeof va === 'number' && typeof vb === 'number') cmp = va - vb
    else cmp = String(va).localeCompare(String(vb))
    return sortDesc ? -cmp : cmp
  })

  const arrow = (key) => (sortKey === key ? (sortDesc ? ' ▼' : ' ▲') : '')

  if (!token) {
    return (
      <div className="auth">
        <h1>Avito Parser</h1>
        <div className="tabs">
          <button type="button" className={authMode === 'login' ? 'active' : ''} onClick={() => setAuthMode('login')}>Вход</button>
          <button type="button" className={authMode === 'register' ? 'active' : ''} onClick={() => setAuthMode('register')}>Регистрация</button>
        </div>
        <form onSubmit={handleAuth}>
          <input placeholder="Логин" value={auth.username} onChange={(e) => setAuth({ ...auth, username: e.target.value })} />
          <input type="password" placeholder="Пароль" value={auth.password} onChange={(e) => setAuth({ ...auth, password: e.target.value })} />
          <button type="submit">{authMode === 'login' ? 'Войти' : 'Зарегистрироваться'}</button>
        </form>
        {authMode === 'login' && <p className="hint">Логин «admin» — вход в админку</p>}
        {error && <div className="error">{error}</div>}
      </div>
    )
  }

  if (view === 'ads') {
    return (
      <div className="app">
        <header>
          <div className="header-actions">
            <button type="button" onClick={backToLinks}>← Назад</button>
          </div>
          <h1>Объявления</h1>
        </header>
        <div className="link-name" title={selectedLink ? selectedLink.url : ''}>
          {selectedLink ? linkLabel(selectedLink) : ''}
        </div>
        {error && <div className="error">{error}</div>}

        {ads.length === 0 ? (
          <p className="hint">По этой ссылке пока нет запарсенных объявлений.</p>
        ) : (
          <>
            <div className="ads-filters">
              <label className="check">
                <input
                  type="checkbox"
                  checked={adsFilters.deliveryOnly}
                  onChange={(e) => setAdsFilters({ ...adsFilters, deliveryOnly: e.target.checked })}
                />
                Только с доставкой
              </label>
              <select
                value={adsFilters.city}
                onChange={(e) => setAdsFilters({ ...adsFilters, city: e.target.value })}
              >
                <option value="">Локация: все</option>
                {RUSSIAN_CITIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <DateRangePicker
                from={adsFilters.dateFrom}
                to={adsFilters.dateTo}
                onChange={(r) => setAdsFilters({ ...adsFilters, dateFrom: r.from, dateTo: r.to })}
              />
              <button type="button" onClick={() => setAdsFilters(ADS_FILTERS_EMPTY)}>Сбросить</button>
            </div>

            {sortedAds.length === 0 ? (
              <p className="hint">Нет объявлений по заданным фильтрам.</p>
            ) : (
              <table className="ads-table">
                <thead>
                  <tr>
                    <th>Фото</th>
                    <th>Название</th>
                    <th className="sortable" onClick={() => toggleSort('price')}>Цена{arrow('price')}</th>
                    <th className="sortable" onClick={() => toggleSort('has_delivery')}>Доставка{arrow('has_delivery')}</th>
                    <th className="sortable" onClick={() => toggleSort('city')}>Расположение{arrow('city')}</th>
                    <th>Ссылка</th>
                    <th className="sortable" onClick={() => toggleSort('scanned_at')}>Время парсинга{arrow('scanned_at')}</th>
                    <th className="sortable" onClick={() => toggleSort('sort_time')}>Публикация{arrow('sort_time')}</th>
                    <th className="sortable" onClick={() => toggleSort('seller_rating')}>Рейтинг{arrow('seller_rating')}</th>
                    <th className="sortable" onClick={() => toggleSort('seller_reviews')}>Оценок{arrow('seller_reviews')}</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedAds.map((ad) => (
                    <tr key={`${ad.id}:${ad.price}`}>
                      <td>{ad.photo_url ? <img className="ad-thumb" src={ad.photo_url} alt="" /> : ''}</td>
                      <td>{ad.title}</td>
                      <td>{ad.price}</td>
                      <td>{ad.has_delivery ? 'Да' : '—'}</td>
                      <td>{ad.city || '—'}</td>
                      <td><a href={ad.ad_url} target="_blank" rel="noreferrer">открыть</a></td>
                      <td>{fmtScan(ad.scanned_at)}</td>
                      <td>{fmtMs(ad.sort_time)}</td>
                      <td>{ad.seller_rating ?? ''}</td>
                      <td>{ad.seller_reviews ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
    )
  }

  const showForm = editingId !== null || showAddForm || (!isAdmin && links.length === 0)

  return (
    <div className="app">
      <header>
        <h1>{isAdmin ? 'Все ссылки (админ)' : 'Мои ссылки для парсинга'}</h1>
        <div className="header-actions">
          {!showForm && (
            <button type="button" onClick={() => setShowAddForm(true)}>＋ Добавить ссылку</button>
          )}
          <button type="button" onClick={logout}>Выйти</button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      {showForm && (
        <form className="link-form" onSubmit={handleSubmit}>
          <h2>{editingId ? 'Изменить ссылку' : 'Добавить ссылку'}</h2>
          {isAdmin && editingId === null && (
            <input placeholder="Владелец (логин)" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          )}
          <input placeholder="Ссылка Avito" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          <div className="row">
            <input type="number" placeholder="Мин. цена" value={form.min_price} onChange={(e) => setForm({ ...form, min_price: e.target.value })} />
            <input type="number" placeholder="Макс. цена" value={form.max_price} onChange={(e) => setForm({ ...form, max_price: e.target.value })} />
          </div>
          <TagInput
            value={form.white_list}
            onChange={(v) => setForm({ ...form, white_list: v })}
            placeholder="Ключевые слова — введите и нажмите Enter"
          />
          <TagInput
            value={form.black_list}
            onChange={(v) => setForm({ ...form, black_list: v })}
            placeholder="Стоп-слова — введите и нажмите Enter"
          />
          <div className="row">
            <select value={form.geo} onChange={(e) => setForm({ ...form, geo: e.target.value })}>
              <option value="">Город (без ограничения)</option>
              {RUSSIAN_CITIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <input type="date" title="Искать объявления с этой даты" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
          </div>
          <div className="row checkboxes">
            <label><input type="checkbox" checked={form.ignore_reserv} onChange={(e) => setForm({ ...form, ignore_reserv: e.target.checked })} /> Пропускать «Зарезервировано»</label>
            <label><input type="checkbox" checked={form.ignore_promotion} onChange={(e) => setForm({ ...form, ignore_promotion: e.target.checked })} /> Пропускать продвигаемые</label>
          </div>
          <div className="row">
            <button type="submit">{editingId ? 'Сохранить' : 'Добавить'}</button>
            {editingId !== null && (
              <button type="button" onClick={() => { setEditingId(null); setForm(EMPTY) }}>Отмена</button>
            )}
            {editingId === null && showAddForm && (
              <button type="button" onClick={() => setShowAddForm(false)}>Отмена</button>
            )}
          </div>
        </form>
      )}

      <ul className="links">
        {links.map((link) => (
          <li key={link.id ?? link.url}>
            {isAdmin && (link.readonly
              ? <div className="owner">📄 из config.toml</div>
              : <div className="owner">👤 {link.username}</div>)}
            <button type="button" className="link-url-btn" onClick={() => openAds(link)} title={link.url}>
              {linkLabel(link)}
            </button>
            <div className="link-meta">
              {link.min_price != null && <span>мин {link.min_price}</span>}
              {link.max_price != null && <span>макс {link.max_price}</span>}
              {link.geo && <span>город: {link.geo}</span>}
              {link.start_date && <span>с {link.start_date}</span>}
              {link.white_list.length > 0 && <span>white: {link.white_list.join(', ')}</span>}
              {link.black_list.length > 0 && <span>black: {link.black_list.join(', ')}</span>}
              {link.ignore_reserv === false && <span>включая резервы</span>}
              {link.ignore_promotion && <span>без продвигаемых</span>}
            </div>
            <div className="link-actions">
              {!link.readonly && (
                <>
                  <button type="button" onClick={() => startEdit(link)}>Изменить</button>
                  <button type="button" className="danger" onClick={() => handleDelete(link.id)}>Удалить</button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
