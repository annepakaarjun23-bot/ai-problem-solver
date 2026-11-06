import { useAutoScroll } from '../hooks/useAutoScroll';
import { useChat } from '../context/ChatContext';
import Composer from './Composer';
import { AlertIcon, ArrowDownIcon, CloseIcon, Spinner } from './Icons';
import Message from './Message';

const STARTERS = [
  'Help me debug an intermittent failure in my build pipeline',
  'Compare two approaches to structuring a database schema',
  'Break a large project into milestones with clear risks',
  'Explain a concept step by step, then quiz me on it',
];

function EmptyState({ onPick, aiConfigured }) {
  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col justify-center px-5 py-10">
      <h1 className="text-[clamp(2.5rem,8vw,4.5rem)] font-black uppercase leading-[0.92] tracking-display text-ink">
        What are we
        <br />
        solving <span className="text-accent-600">today?</span>
      </h1>
      <p className="mt-5 max-w-lg text-zinc-600">Describe the problem in your own words. Add detail as you go.</p>
      {!aiConfigured && (
        <div className="mt-6 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 text-sm text-amber-900" role="status">
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            The AI provider is not configured on this server. Set <code className="font-mono">AI_ROUTER_API_KEY</code> in the .env file and
            restart the backend to enable responses.
          </span>
        </div>
      )}
      <div className="mt-8 grid gap-2 sm:grid-cols-2">
        {STARTERS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            className="rounded-xl border border-zinc-200 px-4 py-3.5 text-left text-sm text-zinc-800 transition-all duration-200 hover:-translate-y-0.5 hover:border-ink hover:shadow-sm"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function ChatView() {
  const chat = useChat();
  const { messages, msgState, generation, activeId, notice, aiConfigured } = chat;

  const lastMessage = messages[messages.length - 1];
  const streamKey = `${messages.length}:${lastMessage?.content.length ?? 0}:${lastMessage?.status}`;
  const { ref, onScroll, showJump, scrollToBottom } = useAutoScroll([streamKey], activeId);

  const generating = Boolean(generation);
  const showEmpty = messages.length === 0 && (!activeId || (!msgState.loading && !msgState.error));

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {notice && (
        <div className="flex items-start gap-2 border-b border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-800" role="alert">
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="flex-1">{notice}</span>
          <button type="button" onClick={chat.dismissNotice} className="shrink-0 rounded p-0.5 hover:bg-red-100" aria-label="Dismiss">
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        <div ref={ref} onScroll={onScroll} className="h-full overflow-y-auto overscroll-contain" aria-live="off">
          {msgState.loading && (
            <div className="flex h-full items-center justify-center text-accent-600">
              <Spinner className="h-6 w-6" />
            </div>
          )}

          {msgState.error && (
            <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center px-5 text-center">
              <p className="text-zinc-700">{msgState.error}</p>
              <div className="mt-4 flex gap-2">
                <button type="button" className="btn-ink btn-pill" onClick={chat.retryLoad}>
                  Try again
                </button>
              </div>
            </div>
          )}

          {showEmpty && !msgState.loading && !msgState.error && (
            <EmptyState aiConfigured={aiConfigured} onPick={(text) => chat.send(text)} />
          )}

          {!msgState.loading && !msgState.error && messages.length > 0 && (
            <div className="mx-auto max-w-3xl space-y-8 px-4 py-8 sm:px-6">
              {msgState.hasMore && (
                <div className="text-center">
                  <button type="button" className="btn-secondary btn-pill" onClick={chat.loadEarlierMessages} disabled={msgState.loadingMore}>
                    {msgState.loadingMore ? 'Loading...' : 'Load earlier messages'}
                  </button>
                </div>
              )}
              {messages.map((m, i) => (
                <Message
                  key={m.id}
                  message={m}
                  isLast={i === messages.length - 1}
                  isGenerating={generating && i === messages.length - 1}
                  statusText={generation?.statusText}
                  canRegenerate={!generating && m.role === 'assistant'}
                  onRegenerate={chat.regenerate}
                />
              ))}
            </div>
          )}
        </div>

        {showJump && (
          <button
            type="button"
            onClick={() => scrollToBottom(true)}
            className="absolute bottom-4 left-1/2 flex h-10 w-10 -translate-x-1/2 items-center justify-center rounded-full border border-zinc-300 bg-white shadow-md transition-transform hover:-translate-y-0.5"
            aria-label="Scroll to latest message"
          >
            <ArrowDownIcon />
          </button>
        )}
      </div>

      <Composer
        onSend={chat.send}
        onStop={chat.stop}
        generating={generating}
        stopping={Boolean(generation?.stopping)}
        resetKey={activeId}
      />
    </div>
  );
}
