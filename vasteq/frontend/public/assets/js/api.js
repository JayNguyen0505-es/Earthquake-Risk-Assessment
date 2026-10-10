/** Shared Fetch API client, based on templates/api.js. */
import { getToken } from "./session.js";

export class ApiError extends Error {
  constructor(message, status = 0, code = "network_error", body = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

export class Api {
  constructor(server = "", endpoint = "", expectJson = true) {
    this.server = server;
    this.endpoint = endpoint;
    this.expectJson = expectJson;
  }

  async ajax(param) {
    const { url, authenticated = true, timeoutMs = 15000, ...options } = param;
    const headers = new Headers(options.headers);
    if (authenticated) {
      const token = getToken();
      if (token) headers.set("Authorization", `Bearer ${token}`);
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, { ...options, headers, signal: controller.signal });
      if (response.ok && (response.status === 204 || response.status === 205)) return null;
      if (response.ok && !this.expectJson) return await response.blob();
      const text = await response.text();
      let data = null;
      if (text && response.headers.get("Content-Type")?.includes("json")) {
        try { data = JSON.parse(text); } catch {
          if (response.ok) throw new ApiError("The server returned an invalid response.", response.status, "invalid_response");
        }
      }
      if (!response.ok) {
        throw new ApiError(data?.message || "The request could not be completed.", response.status,
          data?.code || "http_error", data);
      }
      if (text && data === null) throw new ApiError("The server returned an invalid response.", response.status, "invalid_response");
      return data;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (error.name === "AbortError") throw new ApiError("The request timed out. Please try again.", 0, "timeout");
      throw new ApiError("Unable to reach the server. Please try again.");
    } finally {
      clearTimeout(timeout);
    }
  }

  async call(path = "", method = "GET", body, headers = {}, options = {}) {
    const request = { url: this.server + this.endpoint + path, method, headers: new Headers(headers), ...options };
    if (body !== undefined && body !== null) {
      if (typeof body === "string" || body instanceof FormData || body instanceof Blob) request.body = body;
      else {
        request.body = JSON.stringify(body);
        if (!request.headers.has("Content-Type")) request.headers.set("Content-Type", "application/json");
      }
    }
    return this.ajax(request);
  }

  get(path = "") { return this.call(path); }
  post(path, body, headers, options) { return this.call(path, "POST", body, headers, options); }
  put(path, body, headers) { return this.call(path, "PUT", body, headers); }
  patch(path, body, headers) { return this.call(path, "PATCH", body, headers); }
  delete(path) { return this.call(path, "DELETE"); }
}

export class UserApi extends Api {
  constructor(server = "") { super(server, "/api/v1/user"); }
  register(account) { return this.post("/register", account, {}, { authenticated: false }); }
  login(email, password) { return this.post("/login", { email, password }, {}, { authenticated: false }); }
  me() { return this.get("/me"); }
}

export const userApi = new UserApi();

export class StationApi extends Api {
  constructor(server = "") { super(server, "/api/v1/station"); }
  list(filters = {}) {
    const query = new URLSearchParams(filters).toString();
    return this.get(query ? `?${query}` : "");
  }
}

export const stationApi = new StationApi();
