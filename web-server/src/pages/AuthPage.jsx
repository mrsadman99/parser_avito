export default function AuthPage({ authMode, setAuthMode, auth, setAuth, handleAuth, error }) {
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
