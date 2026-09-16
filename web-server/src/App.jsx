import { useEffect, useState } from 'react'
import { api } from './api'

const EMPTY = { url: '', min_price: '', max_price: '', white_list: '', black_list: '', username: '' }

const SORT_FIELDS = {
  price: { label: 'Цена', key: (a) => a.price ?? 0 },
  scanned_at: { label: 'Время парсинга', key: (a) => a.scanned_at ?? '' },
  sort_time: { label: 'Публикация', key: (a) => a.sort_time ?? 0 },
  seller_reviews: { label: 'Оценок', key: (a) => a.seller_reviews ?? 0 },
  seller_rating: { label: 'Рейтинг', key: (a) => a.seller_rating ?? 0 },
}

function toLinkForm(link) {
  return {
    url: link.url,
    min_price: link.min_price == null ? '' : String(link.min_price),
    max_price: link.max_price == null ? '' : String(link.max_price),
    white_list: (link.white_list || []).join('\n'),
    black_list: (link.black_list || []).join('\n'),
    username: link.username || '',
  }
}

function parseForm(form) {
  const split = (s) => s.split('\n').map((x) => x.trim()).filter(Boolean)
  return {
    url: form.url.trim(),
    min_price: form.min_price === '' ? null : Number(form.min_price),
    max_price: form.max_price === '' ? null : Number(form.max_price),
    white_list: split(form.white_list),
    black_list: split(form.black_list),
    username: form.username.trim(),
  }
}

function fmtScan(iso) {
  if (!iso) return ''
  return String(iso).replace('T', ' ').slice(0, 19)
}

function fmtMs(ms) {
  if (ms == null) return ''
  return new Date(ms).toLocaleString('ru-RU', { hour12: false })
}

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '')
  const [isAdmin, setIsAdmin] = useState(localStorage.getItem('is_admin') === '1')
  const [links, setLinks] = useState([])
  const [view, setView] = useState('links')
  const [selectedLink, setSelectedLink] = useState(null)
  const [ads, setAds] = useState([])
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
  }

  function toggleSort(key) {
    if (sortKey === key) setSortDesc(!sortDesc)
    else {
      setSortKey(key)
      setSortDesc(true)
    }
  }

  const sortedAds = [...ads].sort((a, b) => {
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
        <div className="link-subtitle">{selectedLink && selectedLink.url}</div>
        {error && <div className="error">{error}</div>}

        {sortedAds.length === 0 ? (
          <p className="hint">По этой ссылке пока нет запарсенных объявлений.</p>
        ) : (
          <table className="ads-table">
            <thead>
              <tr>
                <th>Фото</th>
                <th>Название</th>
                <th className="sortable" onClick={() => toggleSort('price')}>Цена{arrow('price')}</th>
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
          <textarea placeholder="Ключевые слова для поиска (по одному на строку)" value={form.white_list} onChange={(e) => setForm({ ...form, white_list: e.target.value })} />
          <textarea placeholder="Слова чёрного списка (по одному на строку)" value={form.black_list} onChange={(e) => setForm({ ...form, black_list: e.target.value })} />
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
            <button type="button" className="link-url-btn" onClick={() => openAds(link)}>
              {link.url}
            </button>
            <div className="link-meta">
              {link.min_price != null && <span>мин {link.min_price}</span>}
              {link.max_price != null && <span>макс {link.max_price}</span>}
              {link.white_list.length > 0 && <span>white: {link.white_list.join(', ')}</span>}
              {link.black_list.length > 0 && <span>black: {link.black_list.join(', ')}</span>}
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
