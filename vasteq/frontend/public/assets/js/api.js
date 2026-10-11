import { token } from "./session.js";

class ApiError extends Error {
  constructor(msg, status = 0, code = "") {
    super(msg);
    this.status = status;
    this.code = code;
  }
}

class Api {
  constructor(path) { this.path = path; }

  async req(path = "", method = "GET", data, auth = true) {
    const headers = {};
    if (auth && token()) headers.Authorization = `Bearer ${token()}`;
    if (data) headers["Content-Type"] = "application/json";
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 15000);
    try {
      const res = await fetch(this.path + path, {
        method, headers, body: JSON.stringify(data), signal: ctrl.signal
      });
      if (res.status === 204) return null;
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new ApiError(err.message || "The request could not be completed.", res.status, err.code);
      }
      return await res.json();
    } catch (err) {
      if (err instanceof ApiError) throw err;
      if (err.name === "SyntaxError") throw new ApiError("The server returned an invalid response.");
      throw new ApiError(err.name === "AbortError"
        ? "The request timed out. Please try again."
        : "Unable to reach the server. Please try again.");
    } finally { clearTimeout(timer); }
  }

  list(params = {}) { return this.req(`?${new URLSearchParams(params)}`); }
  add(data) { return this.req("", "POST", data); }
  edit(id, data) { return this.req(`/${id}`, "PATCH", data); }
  del(id) { return this.req(`/${id}`, "DELETE"); }
}

class User extends Api {
  register(data) { return this.req("/register", "POST", data, false); }
  login(email, password) { return this.req("/login", "POST", { email, password }, false); }
  me() { return this.req("/me"); }
}

export const user = new User("/api/v1/user");
export const station = new Api("/api/v1/station");
