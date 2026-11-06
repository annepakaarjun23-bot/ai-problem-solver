import { useEffect, useState } from 'react';
import { useChat } from '../context/ChatContext';
import ChatView from './ChatView';
import { MenuIcon, PlusIcon } from './Icons';
import Sidebar from './Sidebar';
import { useNavigate } from 'react-router-dom';

export default function AppShell() {
  const [open, setOpen] = useState(false);
  const { activeConversation, activeId } = useChat();
  const navigate = useNavigate();

  // Close the mobile drawer with Escape and lock page scroll while it is open.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const title = activeId ? activeConversation?.title || 'Conversation' : 'New chat';

  return (
    <div className="flex h-full min-h-0 bg-white" style={{ height: '100dvh' }}>
      <aside className="hidden w-72 shrink-0 md:block" aria-label="Sidebar">
        <Sidebar />
      </aside>

      {/* Mobile drawer: mounted only while open, so there is a single sidebar in the page otherwise. */}
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Conversations">
          <div className="drawer-backdrop absolute inset-0 bg-black/50" onClick={() => setOpen(false)} />
          <aside className="drawer-panel absolute inset-y-0 left-0 w-[86%] max-w-xs">
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-zinc-200 px-3 md:px-6">
          <button type="button" className="icon-btn !h-10 !w-10 md:hidden" onClick={() => setOpen(true)} aria-label="Open conversations">
            <MenuIcon className="h-5 w-5" />
          </button>
          <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-ink" title={title}>
            {title}
          </h2>
          <button type="button" className="icon-btn !h-10 !w-10 md:hidden" onClick={() => navigate('/')} aria-label="New chat">
            <PlusIcon className="h-5 w-5" />
          </button>
        </header>
        <ChatView />
      </div>
    </div>
  );
}
