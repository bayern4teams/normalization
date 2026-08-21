// Lightweight API-key auth (M11 backend, M12 UI catch-up). The key is
// never sent anywhere except this app's own API_BASE (see client.ts's
// `request()`), and lives only in the browser's localStorage — there is
// no server-side session, matching the backend's own "one shared
// secret, no user-management system" scope.
const STORAGE_KEY = "norm-api-key";

export function getApiKey(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

export function setApiKey(key: string): void {
  localStorage.setItem(STORAGE_KEY, key);
}

export function clearApiKey(): void {
  localStorage.removeItem(STORAGE_KEY);
}
