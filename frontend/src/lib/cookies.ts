export function readCookie(name: string, cookieString: string): string | null {
  const prefix = `${name}=`;
  for (const pair of cookieString.split(";")) {
    const cookie = pair.trim();
    if (cookie.startsWith(prefix)) {
      return cookie.slice(prefix.length);
    }
  }
  return null;
}
