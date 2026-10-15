import { useState } from 'react'
import useSession from './hooks/useSession'
import AuthPage from './pages/AuthPage'
import AdsPage from './pages/AdsPage'
import LinksPage from './pages/LinksPage'

function Workspace({ session }) {
  const [selectedLink, setSelectedLink] = useState(null)
  return (
    <>
      {session.error && <div className="app"><div className="error" role="alert">{session.error}</div></div>}
      {selectedLink
        ? <AdsPage request={session.request} link={selectedLink} onBack={() => setSelectedLink(null)} />
        : <LinksPage request={session.request} isAdmin={session.actor.is_admin}
            logout={session.logout} loggingOut={session.loggingOut} openAds={setSelectedLink} />}
    </>
  )
}

export default function App() {
  const session = useSession()
  if (!session.token) return <AuthPage authenticate={session.authenticate} sessionError={session.error} />
  if (session.checking) return <main className="app" role="status">Проверяем сессию…</main>
  if (!session.actor) return (
    <main className="app">
      <div className="error" role="alert">{session.error}</div>
      <button onClick={session.retry}>Повторить проверку</button>
      <button onClick={session.logout} disabled={session.loggingOut}>Выйти</button>
    </main>
  )
  return <Workspace key={session.token} session={session} />
}
