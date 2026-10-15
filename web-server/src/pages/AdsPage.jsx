import DateRangePicker from '../components/DateRangePicker'
import { ADS_FILTERS_EMPTY, RUSSIAN_CITIES } from '../helpers/constants'
import { linkLabel, fmtScan, fmtMs } from '../helpers/links'

export default function AdsPage({ backToLinks, selectedLink, error, ads, adsFilters, setAdsFilters, sortedAds, toggleSort, arrow }) {
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
                    <th className="sortable" onClick={() => toggleSort('refreshed_at')}>Обновлено{arrow('refreshed_at')}</th>
                    <th className="sortable" onClick={() => toggleSort('sort_time')}>Публикация{arrow('sort_time')}</th>
                    <th className="sortable" onClick={() => toggleSort('seller_rating')}>Рейтинг{arrow('seller_rating')}</th>
                    <th className="sortable" onClick={() => toggleSort('seller_reviews')}>Оценок{arrow('seller_reviews')}</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedAds.map((ad) => (
                    <tr key={`${ad.source_key}:${ad.id}:${ad.price}`}>
                      <td>{ad.photo_url ? <img className="ad-thumb" src={ad.photo_url} alt="" /> : ''}</td>
                      <td>{ad.title}{Boolean(ad.is_reserved) && <span className="reserved-badge">Забронировано</span>}</td>
                      <td>{ad.price}</td>
                      <td>{ad.has_delivery ? 'Да' : '—'}</td>
                      <td>{ad.city || '—'}</td>
                      <td><a href={ad.ad_url} target="_blank" rel="noreferrer">открыть</a></td>
                      <td>{fmtScan(ad.scanned_at)}</td>
                      <td>{ad.refreshed_at ? fmtScan(ad.refreshed_at) : '—'}</td>
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
