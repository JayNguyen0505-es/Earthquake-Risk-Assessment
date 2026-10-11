const key = "vasteq.accessToken";

export function token() {
  try { return sessionStorage.getItem(key); }
  catch { return null; }
}

export function save(value) {
  try { sessionStorage.setItem(key, value); }
  catch { throw new Error("Your browser couldn't save this session. Allow site storage and try again."); }
}

export function clear() {
  try { sessionStorage.removeItem(key); }
  catch {}
}

export function logout() {
  clear();
  location.replace("login.html");
}
