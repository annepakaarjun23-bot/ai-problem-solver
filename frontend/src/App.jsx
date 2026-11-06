import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import AppShell from './components/AppShell';
import AuthPage from './components/AuthPage';
import { Spinner } from './components/Icons';
import Landing from './components/Landing';
import { ChatProvider } from './context/ChatContext';
import { useAuth } from './context/AuthContext';

function Splash() {
  return (
    <div className="flex h-full items-center justify-center bg-white text-accent-600">
      <Spinner className="h-6 w-6" />
    </div>
  );
}

/** Keeps signed-in users away from the login/signup screens. */
function GuestOnly({ children }) {
  const { status } = useAuth();
  if (status === 'loading') return <Splash />;
  if (status === 'authenticated') return <Navigate to="/" replace />;
  return children;
}

/**
 * "/" shows the landing page to visitors and the chat application to signed-in users, so
 * authenticated users never have to see the landing page again. "/c/:id" is chat-only.
 * Both render the same ChatProvider element, so chat state survives navigation between them.
 */
function Home() {
  const { status } = useAuth();
  const { pathname } = useLocation();
  if (status === 'loading') return <Splash />;
  if (status === 'authenticated') {
    return (
      <ChatProvider>
        <AppShell />
      </ChatProvider>
    );
  }
  return pathname === '/' ? <Landing /> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <GuestOnly>
            <AuthPage mode="login" />
          </GuestOnly>
        }
      />
      <Route
        path="/signup"
        element={
          <GuestOnly>
            <AuthPage mode="signup" />
          </GuestOnly>
        }
      />
      <Route path="/*" element={<Home />} />
    </Routes>
  );
}
