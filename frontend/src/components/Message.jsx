import { memo } from 'react';
import { useCopy } from '../hooks/useCopy';
import { AlertIcon, CheckIcon, CopyIcon, RefreshIcon } from './Icons';
import Markdown from './Markdown';

function StatusDots() {
  return (
    <span className="inline-flex items-center gap-1" aria-hidden="true">
      <span className="dot" />
      <span className="dot" />
      <span className="dot" />
    </span>
  );
}

function UserMessage({ message }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-zinc-100 px-4 py-2.5 text-[15px] leading-7 text-zinc-900">
        {message.content}
      </div>
    </div>
  );
}

function AssistantMessage({ message, isGenerating, statusText, isLast, canRegenerate, onRegenerate }) {
  const { copied, copy } = useCopy();
  const failed = message.status === 'failed' || message.status === 'interrupted';
  const cancelled = message.status === 'cancelled';
  const hasText = message.content.length > 0;
  const showStatus = isGenerating && message.status === 'streaming';

  return (
    <div className="group">
      <div className="mb-1 text-xs font-medium text-zinc-500">AI Problem Solver</div>

      {hasText && <Markdown content={message.content} />}

      {showStatus && (
        <div className={`flex items-center gap-2 text-sm text-zinc-500 ${hasText ? 'mt-3' : ''}`} role="status" aria-live="polite">
          <StatusDots />
          <span>{statusText}</span>
        </div>
      )}

      {failed && (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-800" role="alert">
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{message.error_message || 'The response could not be completed.'}</span>
        </div>
      )}

      {cancelled && (
        <p className="mt-2 text-sm italic text-zinc-500">{hasText ? 'Generation stopped.' : 'Generation stopped before any text was produced.'}</p>
      )}

      {!showStatus && message.status !== 'streaming' && (
        <div className="mt-2 flex items-center gap-1 text-zinc-500">
          {hasText && (
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs hover:bg-zinc-100 hover:text-zinc-800"
              onClick={() => copy(message.content)}
            >
              {copied ? <CheckIcon className="h-3.5 w-3.5" /> : <CopyIcon className="h-3.5 w-3.5" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
          )}
          {isLast && canRegenerate && (
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs hover:bg-zinc-100 hover:text-zinc-800"
              onClick={onRegenerate}
            >
              <RefreshIcon className="h-3.5 w-3.5" />
              {failed ? 'Try again' : 'Regenerate'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default memo(function Message(props) {
  return props.message.role === 'user' ? <UserMessage {...props} /> : <AssistantMessage {...props} />;
});
