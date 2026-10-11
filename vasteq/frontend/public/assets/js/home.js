import { user, station } from "./api.js";
import { token, clear } from "./session.js";
import { $, $$, el, msg } from "./ui.js";

const notice = $("#session-note");
const status = $("#station-status");
const cards = $("#station-cards");
const alert = $("#station-error");
const retry = $("#station-retry");
let viewer = null;
let seq = 0;

function render(data) {
  viewer = data;
  for (const node of $$("[data-auth-public]")) node.hidden = !!data;
  for (const node of $$("[data-auth-private]")) node.hidden = !data;
  for (const node of $$("[data-auth-admin]")) node.hidden = data?.role !== "admin";
  cards.replaceChildren();
  status.textContent = "";
  msg(alert);
  retry.hidden = true;
}

function out() {
  seq++;
  clear();
  render(null);
  notice.hidden = true;
  $("#sign-in").focus();
}

function card(data) {
  const col = el("div", "", "col-md-4 station-col");
  const box = el("article", "", "card station-card");
  box.append(el("h3", `${data.networkCode}.${data.stationCode}`));
  for (const text of [data.name, data.province, data.instrumentType]) {
    if (text) box.append(el("p", text));
  }
  box.append(el("p", data.latitude != null && data.longitude != null
    ? "Coordinates available" : "Coordinates pending", "coords"));
  col.append(box);
  return col;
}

async function load() {
  if (!viewer) return;
  const id = ++seq;
  msg(alert);
  retry.hidden = true;
  status.textContent = "Loading station records…";
  try {
    const data = await station.list({ limit: 3 });
    if (id !== seq) return;
    cards.replaceChildren(...data.items.map(card));
    status.textContent = data.total ? `Showing ${data.items.length} of ${data.total} station records.`
      : "No station records are available yet.";
  } catch (err) {
    if (id !== seq) return;
    if (err.status === 401) return out();
    status.textContent = "Station records are temporarily unavailable.";
    msg(alert, "Station records couldn't be loaded. Please try again.");
    retry.hidden = false;
  }
}

async function init() {
  const id = ++seq;
  notice.hidden = true;
  if (!token()) return render(null);
  try {
    const data = await user.me();
    if (id !== seq) return;
    render(data);
    load();
  } catch (err) {
    if (id !== seq) return;
    render(null);
    if (err.status === 401) clear();
    else notice.hidden = false;
  }
}

$("#sign-out").onclick = out;
$("#session-retry").onclick = init;
retry.onclick = load;
init();
