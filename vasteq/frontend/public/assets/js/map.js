import { user, station } from "./api.js";
import { token, logout } from "./session.js";
import { $, el, msg, busy } from "./ui.js";

const L = window.L;
const panel = $("#stations");
const filters = $("#filters");
const status = $("#map-status");
const select = $("#focus");
const pins = new Map();
let map;
let tiles;
let group;
let params = {};
let loading = false;

function auth(err) {
  if (err.status === 401) { logout(); return true; }
  if (err.status === 403) {
    panel.hidden = true;
    $("#access-status").textContent = "Station access is unavailable for this account.";
    $("#admin-nav").hidden = true;
    return true;
  }
  return false;
}

function fit() {
  map.closePopup();
  select.value = "";
  if (pins.size) map.fitBounds(group.getBounds(), { padding: [32, 32], maxZoom: 12 });
  else map.setView([21.8, 103.3], 7);
}

function popup(data) {
  const box = el("div", "", "station-popup");
  box.append(el("h3", `${data.networkCode}.${data.stationCode}`));
  if (data.name) box.append(el("p", data.name));
  const list = el("dl");
  const fields = {
    Province: data.province, City: data.city, Latitude: data.latitude,
    Longitude: data.longitude, "Elevation (m)": data.elevationM,
    "Coordinate CRS": data.coordinateCrs || "Not specified",
    Instrument: data.instrumentType
  };
  for (const [key, value] of Object.entries(fields)) list.append(el("dt", key), el("dd", value ?? "—"));
  box.append(list);
  return box;
}

function draw(items) {
  let unknown = 0;
  for (const data of items) {
    if (data.latitude == null || data.longitude == null) continue;
    const code = `${data.networkCode}.${data.stationCode}`;
    const pin = L.marker([data.latitude, data.longitude], { title: code, alt: code })
      .bindPopup(popup(data), { maxWidth: 240, maxHeight: 280, keepInView: true }).addTo(group);
    pins.set(String(data.id), pin);
    const option = el("option", `${code}${data.name ? " · " + data.name : ""}`);
    option.value = data.id;
    select.append(option);
    if (!data.coordinateCrs) unknown++;
  }
  status.textContent = `${pins.size} of ${items.length} stations mapped · ${items.length - pins.size} missing coordinates`;
  msg($("#empty"), items.length ? pins.size ? "" : "These stations have no coordinates to plot." : "No stations found. Try changing the filters.");
  msg($("#crs-note"), unknown ? `${unknown} mapped ${unknown === 1 ? "station has" : "stations have"} no specified coordinate system. See station details.` : "");
  fit();
}

async function load() {
  if (loading) return;
  loading = true;
  busy(filters, true);
  $("#refresh").disabled = $("#fit").disabled = select.disabled = true;
  group.clearLayers();
  pins.clear();
  select.replaceChildren(new Option("Choose a station", ""));
  status.textContent = "Loading stations…";
  for (const id of ["#page-error", "#empty", "#crs-note"]) msg($(id));
  try {
    const items = [];
    let offset = 0;
    let total = 0;
    do {
      const data = await station.list({ ...params, offset, limit: 100 });
      items.push(...data.items);
      total = data.total;
      offset += 100;
      status.textContent = `Loading stations… ${items.length} of ${total}`;
    } while (offset < total);
    draw(items);
  } catch (err) {
    if (auth(err)) return;
    status.textContent = "Stations could not be loaded. Use Refresh to try again.";
    msg($("#page-error"), err.message);
  } finally {
    loading = false;
    busy(filters, false);
    $("#refresh").disabled = false;
    $("#fit").disabled = select.disabled = !pins.size;
  }
}

function apply() {
  params = Object.fromEntries([...new FormData(filters)].map(([key, value]) => [key, value.trim()]).filter(([, value]) => value));
  load();
}

async function init() {
  if (!token()) return logout();
  $("#retry-access").hidden = true;
  msg($("#page-error"));
  try {
    const data = await user.me();
    $("#access-status").textContent = "";
    $("#admin-nav").hidden = data.role !== "admin";
    panel.hidden = false;
    map = L.map("map").setView([21.8, 103.3], 7);
    group = L.featureGroup().addTo(map);
    tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    tiles.on("tileerror", () => { $("#tile-note").hidden = false; });
    await load();
  } catch (err) {
    if (auth(err)) return;
    $("#access-status").textContent = "Your session could not be checked.";
    msg($("#page-error"), err.message);
    $("#retry-access").hidden = false;
  }
}

filters.onsubmit = e => { e.preventDefault(); apply(); };
$("#clear").onclick = () => { filters.reset(); apply(); };
$("#refresh").onclick = load;
$("#fit").onclick = fit;
select.onchange = () => {
  if (!select.value) return;
  const pin = pins.get(select.value);
  map.setView(pin.getLatLng(), Math.max(map.getZoom(), 10));
  pin.openPopup();
};
$("#retry-tiles").onclick = () => { $("#tile-note").hidden = true; tiles.redraw(); };
$("#retry-access").onclick = init;
$("#sign-out").onclick = logout;
init();
