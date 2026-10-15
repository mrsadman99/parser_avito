import LinkForm from '../components/LinkForm'
import { linkLabel } from '../helpers/links'

export default function LinksPage({ editingId, showAddForm, isAdmin, links, setShowAddForm, logout, error, handleSubmit, form, setForm, setEditingId, openAds, startEdit, handleDelete }) {
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
        <LinkForm {...{ handleSubmit, editingId, isAdmin, form, setForm, setEditingId, showAddForm, setShowAddForm }} />
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
