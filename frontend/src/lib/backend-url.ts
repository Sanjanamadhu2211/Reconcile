export function getBackendUrl(env: string | undefined): string {
  const url = env?.trim() || "http://localhost:8000";
  return url.endsWith("/") ? url.slice(0, -1) : url;
}
