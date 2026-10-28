import { Alert, Loader, Text } from "@mantine/core";
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
    return <Loader size="sm" aria-label="Loading" />;
  }
  if (isError) {
    return (
      <Alert color="red" title="Request failed">
        {errorMessage(error)}
      </Alert>
    );
  }
  if (isEmpty) {
    return <Text c="dimmed">{emptyMessage}</Text>;
  }
  return <>{children}</>;
}
