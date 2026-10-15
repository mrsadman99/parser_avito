import { useState } from 'react'
import LinkForm from '../components/LinkForm'
import { linkLabel, parseForm, toLinkForm } from '../helpers/links'
import { EMPTY } from '../helpers/constants'
import useLinks from '../hooks/useLinks'

export default function LinksPage({ request, isAdmin, logout, loggingOut, openAds }) {
  const { links, loading, loaded, error, pending, save, remove, retry } = useLinks(request)
  const [editingId, setEditingId] = useState(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const busy = Boolean(pending)
  const showForm = loaded && !loading && (editingId !== null || showAddForm || (!isAdmin && links.length === 0))

  function cancelEdit() {
    setEditingId(null)
    setShowAddForm(false)
    setForm(EMPTY)
  }

  function startEdit(link) {
    setEditingId(link.id)
    setForm(toLinkForm(link))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (await save(editingId, parseForm(form))) cancelEdit()
  }

  async function handleDelete(id) {
    if (await remove(id) && editingId === id) cancelEdit()
  }

  return (
    <div className="app">
      <header>
        <h1>{isAdmin ? 'Все ссылки (админ)' : 'Мои ссылки для парсинга'}</h1>
        <div className="header-actions">
          {!showForm && !loading && loaded && (
            <button type="button" disabled={busy || loggingOut} onClick={() => setShowAddForm(true)}>＋ Добавить ссылку</button>
          )}
          <button type="button" onClick={logout} disabled={busy || loggingOut}>{loggingOut ? 'Выходим…' : 'Выйти'}</button>
        </div>
      </header>

      {error && <div className="error" role="alert">{error}
        <button type="button" onClick={retry} disabled={busy || loading}>Повторить загрузку</button>
      </div>}
      {loading && <p role="status">Загружаем подписки…</p>}

      {showForm && (
        <LinkForm {...{ handleSubmit, editingId, isAdmin, form, setForm }} pending={busy || loggingOut} onCancel={cancelEdit} />
      )}

      <ul className="links">
        {links.map((link) => (
          <li key={link.id ?? link.url}>
            {isAdmin && (link.readonly
              ? <div className="owner">📄 из config.toml</div>
              : <div className="owner">👤 {link.username}</div>)}
            <button type="button" className="link-url-btn" disabled={busy || loggingOut} onClick={() => openAds(link)} title={link.url}>
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
                  <button type="button" disabled={busy || loading || loggingOut} onClick={() => startEdit(link)}>Изменить</button>
                  <button type="button" className="danger" disabled={busy || loading || loggingOut} onClick={() => handleDelete(link.id)}>{pending === `delete:${link.id}` ? 'Удаляем…' : 'Удалить'}</button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
