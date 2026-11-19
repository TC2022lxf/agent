import { Sidebar } from './components/Sidebar'
import { useAuth } from './state/auth'
import { useNav } from './state/nav'
import { AccountView } from './views/AccountView'
import { AdminUsersView } from './views/AdminUsersView'
import { AuthView } from './views/AuthView'
import { CanvasHome } from './views/CanvasHome'
import { CanvasView } from './views/CanvasView'
import { ChatView } from './views/ChatView'
import { ConsoleView } from './views/ConsoleView'
import { ImageHome } from './views/ImageHome'
import { ImageStudioView } from './views/ImageStudioView'
import { ProductsView } from './views/ProductsView'
import { SkillsView, ToolsView } from './views/RegistryViews'
import { ArtifactsView, HistoryView, HomeView, LaterView } from './views/SimpleViews'

/** Shell from the prototype: sidebar + one active view. No router: the nav state is the route. */
export function App() {
  const { nav } = useNav()
  const { status, loading } = useAuth()
  const v = nav.view
  const studio = v === 'image' && nav.imageTaskId !== null
  // The canvas workspace is its own stage. The project list stays in the normal shell.
  const canvasStudio = v === 'canvas' && nav.canvasTaskId !== null

  if (loading) {
    return (
      <div className="auth-shell">
        <p className="x-ghost">正在确认登录状态…</p>
      </div>
    )
  }
  // Not signed in: the workbench is unreachable. The backend would answer 401 anyway; this
  // just avoids rendering a shell full of failed requests.
  if (!status?.authenticated) return <AuthView />

  return (
    <div className={`app${studio ? ' imgpage' : ''}${canvasStudio ? ' canvas-app' : ''}`}>
      <Sidebar />
      {studio ? <ImageStudioView /> : canvasStudio ? <CanvasView /> : (
        <div className="main-shell">
          {v === 'home' && <HomeView />}
          {v === 'chat' && <ChatView />}
          {v === 'history' && <HistoryView />}
          {v === 'artifacts' && <ArtifactsView />}
          {v === 'products' && <ProductsView />}
          {v === 'tools' && <ToolsView />}
          {v === 'skills' && <SkillsView />}
          {v === 'console' && <ConsoleView />}
          {v === 'account' && <AccountView />}
          {v === 'admin' && <AdminUsersView />}
          {v === 'image' && <ImageHome />}
          {v === 'canvas' && <CanvasHome />}
          {v === 'automation' && <LaterView />}
        </div>
      )}
    </div>
  )
}
