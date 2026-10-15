import { useEffect, useState } from 'react'
import DateRangePicker from '../components/DateRangePicker'
import AdsTable from '../components/AdsTable'
import { ADS_FILTERS_EMPTY, RUSSIAN_CITIES } from '../helpers/constants'
import { linkLabel } from '../helpers/links'
import { rangeBounds } from '../helpers/dates'
import useAds from '../hooks/useAds'

export default function AdsPage({ request, link, onBack }) {
  const [filters, setFilters] = useState(ADS_FILTERS_EMPTY)
  const [sort, setSort] = useState({ key: 'refreshed_at', direction: 'desc' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const { from, to } = rangeBounds(filters)
  const params = new URLSearchParams({
    ...(link.id != null ? { link_id: link.id } : { url: link.url }),
    page, page_size: pageSize, sort: sort.key, direction: sort.direction,
    city: filters.city, delivery_only: filters.deliveryOnly,
  })
  if (from) params.set('published_from', from)
  if (to) params.set('published_to', to)
  const { data, loading, error, retry } = useAds(request, params.toString())
  const pages = Math.max(1, Math.ceil((data?.total || 0) / pageSize))
  const currentPage = data?.page ?? page

  useEffect(() => {
    if (data && data.page !== page) setPage(data.page)
  }, [data, page])

  function changeFilters(next) { setFilters(next); setPage(1) }
  function toggleSort(key) {
    setSort({ key, direction: sort.key === key && sort.direction === 'desc' ? 'asc' : 'desc' })
    setPage(1)
  }

  return (
    <main className="app ads-page">
      <header>
        <button type="button" onClick={onBack}>← Назад</button>
        <h1>Объявления</h1>
      </header>
      <div className="link-name" title={link.url}>{linkLabel(link)}</div>
      {error && <div className="error" role="alert">{error} <button onClick={retry}>Повторить</button></div>}
      <div className="ads-filters">
        <label className="check">
          <input type="checkbox" checked={filters.deliveryOnly}
            onChange={(e) => changeFilters({ ...filters, deliveryOnly: e.target.checked })} />Только с доставкой
        </label>
        <select aria-label="Локация" value={filters.city}
          onChange={(e) => changeFilters({ ...filters, city: e.target.value })}>
          <option value="">Локация: все</option>
          {RUSSIAN_CITIES.map((city) => <option key={city} value={city}>{city}</option>)}
        </select>
        <DateRangePicker from={filters.dateFrom} to={filters.dateTo}
          onChange={({ from, to }) => changeFilters({ ...filters, dateFrom: from, dateTo: to })} />
        <button type="button" onClick={() => changeFilters(ADS_FILTERS_EMPTY)}>Сбросить</button>
      </div>
      {loading && <p role="status">Загружаем объявления…</p>}
      {data && <>
        <div className="pagination" aria-label="Страницы объявлений">
          <span role="status">Найдено: {data.total}. Страница {currentPage} из {pages}</span>
          <label>На странице
            <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1) }}>
              {[25, 50, 100, 200].map((size) => <option key={size}>{size}</option>)}
            </select>
          </label>
          <button disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>Предыдущая</button>
          <button disabled={currentPage >= pages} onClick={() => setPage(currentPage + 1)}>Следующая</button>
        </div>
        {data.items.length
          ? <AdsTable ads={data.items} sort={sort} onSort={toggleSort} />
          : <p className="hint">Нет объявлений по заданным условиям.</p>}
      </>}
    </main>
  )
}
