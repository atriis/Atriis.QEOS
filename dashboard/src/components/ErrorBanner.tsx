import { ApiError } from "../api/http";
import { SsoError } from "../auth/ssoErrors";

/** `message` replaces the text derived from `error` (a widget's own render failure says what failed, not why). */
export default function ErrorBanner({ error, onRetry, message }: { error: unknown; onRetry?: () => void; message?: string }) {
  const detail =
    message ?? (error instanceof ApiError
      ? error.status === 429
        ? "Too many requests — please retry shortly."
        : error.detail
      : error instanceof SsoError
        ? error.message
        : "Something went wrong.");
  return (
    <div className="error-banner" role="alert">
      <span>{detail}</span>
      {onRetry && <button type="button" onClick={onRetry}>Retry</button>}
    </div>
  );
}
