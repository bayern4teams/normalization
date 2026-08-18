import type { ReactNode } from "react";

interface QueryStateProps {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  isEmpty?: boolean;
  emptyMessage?: string;
  children: ReactNode;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Unknown error";
}

export function QueryState({
  isLoading,
  isError,
  error,
  isEmpty,
  emptyMessage = "Nothing here yet.",
  children,
}: QueryStateProps) {
  if (isLoading) {
    return <p className="state-message">Loading…</p>;
  }
  if (isError) {
    return <p className="state-message state-message--error">Request failed: {errorMessage(error)}</p>;
  }
  if (isEmpty) {
    return <p className="state-message">{emptyMessage}</p>;
  }
  return <>{children}</>;
}
