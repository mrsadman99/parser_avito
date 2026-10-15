import { useEffect, useState } from 'react'
import { api } from './api'
import { EMPTY, ADS_FILTERS_EMPTY, SORT_FIELDS } from './helpers/constants'
import { parseForm, toLinkForm } from './helpers/links'
import { rangeBounds } from './helpers/dates'
import AuthPage from './pages/AuthPage'
import AdsPage from './pages/AdsPage'
import LinksPage from './pages/LinksPage'

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '')
  const [isAdmin, setIsAdmin] = useState(localStorage.getItem('is_admin') === '1')
  const [links, setLinks] = useState([])
  const [view, setView] = useState('links')
  const [selectedLink, setSelectedLink] = useState(null)
  const [ads, setAds] = useState([])
  const [adsFilters, setAdsFilters] = useState(ADS_FILTERS_EMPTY)
  const [sortKey, setSortKey] = useState('refreshed_at')
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

  useEffect(() => {
    if (view !== 'ads' || !selectedLink || !token) return
    let cancelled = false
    let timer
    const query = selectedLink.id != null
      ? `link_id=${selectedLink.id}`
      : `url=${encodeURIComponent(selectedLink.url)}`
    async function refreshAds() {
      try {
        const rows = await api(`/api/ads?${query}`, { token })
        if (!cancelled) setAds(rows)
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) timer = setTimeout(refreshAds, 10000)
      }
    }
    refreshAds()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [view, selectedLink, token])

  function openAds(link) {
    setError('')
    setAds([])
    setSelectedLink(link)
    setView('ads')
    setAdsFilters(ADS_FILTERS_EMPTY)
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

  if (!token) return <AuthPage {...{ authMode, setAuthMode, auth, setAuth, handleAuth, error }} />
  if (view === 'ads') return <AdsPage {...{ backToLinks, selectedLink, error, ads, adsFilters, setAdsFilters, sortedAds, toggleSort, arrow }} />
  return <LinksPage {...{ editingId, showAddForm, isAdmin, links, setShowAddForm, logout, error, handleSubmit, form, setForm, setEditingId, openAds, startEdit, handleDelete }} />
}
