import TagInput from './TagInput'
import { EMPTY, RUSSIAN_CITIES } from '../helpers/constants'

export default function LinkForm({ handleSubmit, editingId, isAdmin, form, setForm, setEditingId, showAddForm, setShowAddForm }) {
  return (
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
  )
}
