import { userApi, stationApi } from "./api.js";
import { getToken, clearSession } from "./session.js";

const sessionNotice = document.querySelector("#session-notice");
const stationStatus = document.querySelector("#station-status");
const stationPreview = document.querySelector("#station-preview");
const stationError = document.querySelector("#station-error");
const stationRetry = document.querySelector("#station-retry");
let viewer = null;
let sessionRequest = 0;
let stationRequest = 0;

function renderViewer(user) {
  viewer = user;
  for (const node of document.querySelectorAll("[data-auth-public]")) node.hidden = Boolean(user);
  for (const node of document.querySelectorAll("[data-auth-private]")) node.hidden = !user;
  for (const node of document.querySelectorAll("[data-auth-admin]")) node.hidden = user?.role !== "admin";
  stationPreview.replaceChildren();
  stationStatus.textContent = "";
  stationError.hidden = true;
  stationRetry.hidden = true;
}

function signOut() {
  sessionRequest++;
  stationRequest++;
  clearSession();
  renderViewer(null);
  sessionNotice.hidden = true;
  document.querySelector("#header-sign-in").focus();
}

function stationCard(station) {
  const column = document.createElement("div");
  column.className = "col-md-4 station-column";
  const card = document.createElement("article");
  card.className = "card station-preview-card";
  const title = document.createElement("h3");
  title.textContent = `${station.networkCode}.${station.stationCode}`;
  card.append(title);
  for (const value of [station.name, station.province, station.instrumentType]) {
    if (!value) continue;
    const text = document.createElement("p");
    text.textContent = value;
    card.append(text);
  }
  const coordinates = document.createElement("p");
  coordinates.className = "station-coordinate-status";
  coordinates.textContent = station.latitude != null && station.longitude != null
    ? "Coordinates available" : "Coordinates pending";
  card.append(coordinates);
  column.append(card);
  return column;
}

async function loadStations() {
  if (!viewer) return;
  const request = ++stationRequest;
  const token = getToken();
  stationError.hidden = true;
  stationRetry.hidden = true;
  stationStatus.textContent = "Loading station records…";
  try {
    const data = await stationApi.list({ limit: 3 });
    if (request !== stationRequest || token !== getToken() || !viewer) return;
    if (!data || !Array.isArray(data.items) || !Number.isInteger(data.total) || data.total < 0)
      throw new Error("Invalid station response");
    stationPreview.replaceChildren(...data.items.map(stationCard));
    stationStatus.textContent = data.total === 0 ? "No station records are available yet."
      : `Showing ${data.items.length} of ${data.total} station records.`;
  } catch (error) {
    if (request !== stationRequest || token !== getToken() || !viewer) return;
    if (error.status === 401) { signOut(); return; }
    stationStatus.textContent = "Station records are temporarily unavailable.";
    stationError.textContent = "Station records couldn't be loaded. Please try again.";
    stationError.hidden = false;
    stationRetry.hidden = false;
  }
}

async function checkSession() {
  const request = ++sessionRequest;
  const token = getToken();
  sessionNotice.hidden = true;
  if (!token) { renderViewer(null); return; }
  try {
    const user = await userApi.me();
    if (request !== sessionRequest || token !== getToken()) return;
    if (!user || typeof user.displayName !== "string" || typeof user.email !== "string")
      throw new Error("Invalid account response");
    renderViewer(user);
    loadStations();
  } catch (error) {
    if (request !== sessionRequest || token !== getToken()) return;
    renderViewer(null);
    if (error.status === 401) clearSession();
    else sessionNotice.hidden = false;
  }
}

document.querySelector("#sign-out").addEventListener("click", signOut);
document.querySelector("#session-retry").addEventListener("click", checkSession);
stationRetry.addEventListener("click", loadStations);
checkSession();
