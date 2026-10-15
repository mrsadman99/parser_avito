import { SORT_FIELDS } from '../helpers/constants'
import { fmtScan, fmtMs } from '../helpers/links'

export default function AdsTable({ ads, sort, onSort }) {
  function heading(key) {
    const selected = sort.key === key
    return <th aria-sort={selected ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => onSort(key)}>
        {SORT_FIELDS[key].label}{selected ? (sort.direction === 'desc' ? ' ▼' : ' ▲') : ''}
      </button>
    </th>
  }

  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label="Результаты парсинга">
      <table className="ads-table">
        <thead><tr>
          <th>Фото</th><th>Название</th>{heading('price')}{heading('has_delivery')}{heading('city')}
          <th>Ссылка</th>{heading('scanned_at')}{heading('refreshed_at')}{heading('sort_time')}
          {heading('seller_rating')}{heading('seller_reviews')}
        </tr></thead>
        <tbody>{ads.map((ad) => (
          <tr key={`${ad.source_key}:${ad.id}:${ad.price}`}>
            <td>{ad.photo_url && <img className="ad-thumb" src={ad.photo_url} alt="" loading="lazy" />}</td>
            <td>{ad.title}{Boolean(ad.is_reserved) && <span className="reserved-badge">Забронировано</span>}</td>
            <td>{ad.price}</td><td>{ad.has_delivery ? 'Да' : '—'}</td><td>{ad.city || '—'}</td>
            <td><a href={ad.ad_url} target="_blank" rel="noreferrer">открыть</a></td>
            <td>{fmtScan(ad.scanned_at)}</td><td>{ad.refreshed_at ? fmtScan(ad.refreshed_at) : '—'}</td>
            <td>{fmtMs(ad.sort_time)}</td><td>{ad.seller_rating ?? ''}</td><td>{ad.seller_reviews ?? ''}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  )
}
