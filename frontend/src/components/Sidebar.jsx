import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useChat } from '../context/ChatContext';
import { AlertIcon, CheckIcon, CloseIcon, LogoutIcon, Logo, PencilIcon, PlusIcon, Spinner, TrashIcon } from './Icons';

function ConversationItem({ conversation, active, busy, onNavigate }) {
  const { renameConversation, deleteConversation } = useChat();
  const [mode, setMode] = useState('view'); // view | rename | confirm-delete
  const [title, setTitle] = useState(conversation.title);
  const input = useRef(null);

  useEffect(() => {
    if (mode === 'rename') input.current?.select();
  }, [mode]);

  const saveRename = async () => {
    const next = title.trim();
    if (next && next !== conversation.title) await renameConversation(conversation.id, next);
    setMode('view');
  };

  if (mode === 'rename') {
    return (
      <div className="flex items-center gap-1 px-2 py-1">
        <input
          ref={input}
          value={title}
          maxLength={200}
          aria-label="Conversation title"
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') saveRename();
            if (e.key === 'Escape') {
              setTitle(conversation.title);
              setMode('view');
            }
          }}
          className="min-w-0 flex-1 rounded-md border border-white/30 bg-white/10 px-2 py-1.5 text-sm text-white focus:border-accent-500 focus:outline-none"
        />
        <button type="button" className="icon-btn !text-white/70 hover:!bg-white/10 hover:!text-white" onClick={saveRename} aria-label="Save title">
          <CheckIcon />
        </button>
        <button
          type="button"
          className="icon-btn !text-white/70 hover:!bg-white/10 hover:!text-white"
          onClick={() => {
            setTitle(conversation.title);
            setMode('view');
          }}
          aria-label="Cancel rename"
        >
          <CloseIcon />
        </button>
      </div>
    );
  }

  if (mode === 'confirm-delete') {
    return (
      <div className="mx-2 rounded-lg bg-white/10 p-3 text-sm text-white">
        <p className="truncate">Delete "{conversation.title}"?</p>
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            className="btn-danger !px-3 !py-1.5 !text-xs"
            onClick={async () => {
              const ok = await deleteConversation(conversation.id);
              if (!ok) setMode('view');
            }}
          >
            Delete
          </button>
          <button type="button" className="btn !px-3 !py-1.5 !text-xs text-white hover:bg-white/10" onClick={() => setMode('view')}>
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`group relative mx-2 flex items-center rounded-lg transition-colors duration-150 ${
        active ? 'bg-white/15' : 'hover:bg-white/10'
      }`}
    >
      <Link
        to={`/c/${conversation.id}`}
        onClick={onNavigate}
        className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2.5 text-sm text-white/90"
        aria-current={active ? 'page' : undefined}
        title={conversation.title}
      >
        <span className="truncate">{conversation.title}</span>
        {busy && <Spinner className="h-3 w-3 shrink-0 text-accent-500" />}
      </Link>
      <div className="flex shrink-0 pr-1 opacity-100 transition-opacity md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100">
        <button
          type="button"
          className="icon-btn !text-white/60 hover:!bg-white/10 hover:!text-white"
          onClick={() => setMode('rename')}
          aria-label={`Rename ${conversation.title}`}
        >
          <PencilIcon />
        </button>
        <button
          type="button"
          className="icon-btn !text-white/60 hover:!bg-white/10 hover:!text-white"
          onClick={() => setMode('confirm-delete')}
          aria-label={`Delete ${conversation.title}`}
        >
          <TrashIcon />
        </button>
      </div>
    </div>
  );
}

export default function Sidebar({ onNavigate }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { conversations, listState, activeId, generation, loadMoreConversations } = useChat();

  return (
    <div className="flex h-full flex-col bg-ink text-white">
      <div className="flex items-center justify-between px-4 pb-3 pt-4">
        <Link to="/" onClick={onNavigate} className="flex items-center gap-2.5" aria-label="AI Problem Solver">
          <Logo className="h-7 w-7" />
          <span className="text-[13px] font-bold uppercase tracking-[0.12em]">Problem Solver</span>
        </Link>
      </div>

      <div className="px-4 pb-3">
        <button
          type="button"
          className="btn-light w-full justify-start rounded-full px-4"
          onClick={() => {
            navigate('/');
            onNavigate?.();
          }}
        >
          <PlusIcon /> New chat
        </button>
      </div>

      <p className="px-5 pb-2 pt-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-white/40">Conversations</p>
      <nav className="min-h-0 flex-1 overflow-y-auto pb-3" aria-label="Conversations">
        {listState.loading && (
          <div className="flex items-center gap-2 px-5 py-3 text-sm text-white/50">
            <Spinner /> Loading
          </div>
        )}
        {listState.error && (
          <div className="mx-4 flex items-start gap-2 rounded-lg bg-red-500/15 px-3 py-2 text-sm text-red-200" role="alert">
            <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{listState.error}</span>
          </div>
        )}
        {!listState.loading && !listState.error && conversations.length === 0 && (
          <p className="px-5 py-3 text-sm leading-6 text-white/50">No conversations yet. Start one with a message.</p>
        )}
        {conversations.map((c) => (
          <ConversationItem
            key={c.id}
            conversation={c}
            active={c.id === activeId}
            busy={generation?.conversationId === c.id}
            onNavigate={onNavigate}
          />
        ))}
        {listState.hasMore && (
          <button
            type="button"
            onClick={loadMoreConversations}
            disabled={listState.loadingMore}
            className="mx-2 mt-2 w-[calc(100%-1rem)] rounded-lg px-3 py-2 text-left text-sm text-white/60 hover:bg-white/10 hover:text-white disabled:opacity-50"
          >
            {listState.loadingMore ? 'Loading...' : 'Show more'}
          </button>
        )}
      </nav>

      <div className="flex items-center gap-3 border-t border-white/10 p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-sm font-bold uppercase text-ink" aria-hidden="true">
          {user?.email?.[0] ?? '?'}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={user?.email}>
            {user?.email}
          </p>
        </div>
        <button
          type="button"
          onClick={logout}
          className="icon-btn !h-9 !w-9 !text-white/70 hover:!bg-white/10 hover:!text-white"
          aria-label="Log out"
          title="Log out"
        >
          <LogoutIcon className="h-[18px] w-[18px]" />
        </button>
      </div>
    </div>
  );
}
