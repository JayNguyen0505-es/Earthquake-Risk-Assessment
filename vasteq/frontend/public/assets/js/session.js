const TOKEN_KEY = "vasteq.accessToken";

export function getToken() {
  try {
    const token = sessionStorage.getItem(TOKEN_KEY);
    return token && token !== "undefined" && token !== "null" ? token : null;
  } catch {
    return null;
  }
}

export function saveToken(token) {
  // Let the page report storage failures rather than redirect without a session.
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearSession() {
  try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* Storage may be unavailable. */ }
}
