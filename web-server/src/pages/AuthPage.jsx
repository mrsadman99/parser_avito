import { useRef, useState } from 'react'

export default function AuthPage({ authenticate, sessionError }) {
  const [mode, setMode] = useState('login')
  const [credentials, setCredentials] = useState({ username: '', password: '' })
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const lock = useRef(false)

  async function submit(event) {
    event.preventDefault()
    if (lock.current) return
    lock.current = true
    setPending(true)
    setError('')
    try { await authenticate(mode, credentials) }
    catch (err) { setError(err.message) }
    finally { lock.current = false; setPending(false) }
  }

  return (
    <main className="auth">
      <h1>Avito Parser</h1>
      <div className="tabs">
        {['login', 'register'].map((value) => (
          <button key={value} type="button" disabled={pending} className={mode === value ? 'active' : ''}
            onClick={() => { setMode(value); setError('') }}>
            {value === 'login' ? 'Вход' : 'Регистрация'}
          </button>
        ))}
      </div>
      <form onSubmit={submit}>
        <fieldset disabled={pending}>
          <label>Логин<input required maxLength={64} autoComplete="username" value={credentials.username}
            onChange={(e) => setCredentials({ ...credentials, username: e.target.value })} /></label>
          <label>Пароль<input required maxLength={128} type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={credentials.password}
            onChange={(e) => setCredentials({ ...credentials, password: e.target.value })} /></label>
          <button type="submit">{pending ? 'Подождите…' : mode === 'login' ? 'Войти' : 'Зарегистрироваться'}</button>
        </fieldset>
      </form>
      {mode === 'login' && <p className="hint">Логин «admin» — вход в админку</p>}
      {(error || sessionError) && <div className="error" role="alert">{error || sessionError}</div>}
    </main>
  )
}
