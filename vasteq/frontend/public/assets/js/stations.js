import { user, station } from "./api.js";
import { token, logout } from "./session.js";
import { $, $$, el, msg, busy, toast } from "./ui.js";

const panel = $("#stations");
const rows = $("#rows");
const form = $("#edit-form");
const filters = $("#filters");
const editBox = $("#edit-box");
const delBox = $("#del-box");
const limit = 20;
let offset = 0;
let total = 0;
let params = {};
let selected = null;
let saving = false;
let loading = false;

function deny() {
  panel.hidden = true;
  rows.replaceChildren();
  editBox.close();
  delBox.close();
  $("#access-status").textContent = "Administrator access is required to manage stations.";
  $("#retry-access").hidden = true;
}

function auth(err) {
  if (err.status === 401) { logout(); return true; }
  if (err.status === 403) { deny(); return true; }
  return false;
}

function error(err) {
  if (err.code === "station_exists") return "A station with these network and station codes already exists.";
  if (err.code === "station_in_use") return "This station has linked channels and cannot be deleted.";
  if (err.status === 404) return "This station no longer exists. Refresh the list and try again.";
  return err.message;
}

function row(data) {
  const node = $("#station-row").content.firstElementChild.cloneNode(true);
  const code = `${data.networkCode}.${data.stationCode}`;
  const cells = { id: data.id, code, name: data.name, province: data.province, lat: data.latitude, lng: data.longitude };
  for (const [key, value] of Object.entries(cells)) $("[data-" + key + "]", node).textContent = value ?? "—";
  const editBtn = $(".edit-btn", node);
  const delBtn = $(".del-btn", node);
  editBtn.setAttribute("aria-label", `Edit ${code}`);
  delBtn.setAttribute("aria-label", `Delete ${code}`);
  editBtn.onclick = () => edit(data);
  delBtn.onclick = () => del(data);
  return node;
}

function pages() {
  $("#prev").disabled = loading || offset === 0;
  $("#next").disabled = loading || offset + limit >= total;
  $("#add").disabled = loading;
  busy(filters, loading);
}

async function load() {
  if (loading) return;
  loading = true;
  pages();
  rows.replaceChildren();
  $("#list-status").textContent = "Loading stations…";
  $("#retry-list").hidden = true;
  msg($("#page-error"));
  try {
    let data = await station.list({ ...params, offset, limit });
    if (offset && offset >= data.total) {
      offset = Math.max(0, Math.floor((data.total - 1) / limit) * limit);
      data = await station.list({ ...params, offset, limit });
    }
    total = data.total;
    rows.replaceChildren(...data.items.map(row));
    if (!total) {
      const empty = el("tr");
      const cell = el("td", "No stations found. Try changing the filters or add a station.");
      cell.colSpan = 7;
      empty.append(cell);
      rows.append(empty);
    }
    $("#list-status").textContent = total ? `Showing ${offset + 1}–${offset + data.items.length} of ${total} stations` : "0 stations";
  } catch (err) {
    if (auth(err)) return;
    total = 0;
    $("#list-status").textContent = "Stations could not be loaded.";
    msg($("#page-error"), error(err));
    $("#retry-list").hidden = false;
  } finally {
    loading = false;
    pages();
  }
}

function edit(data = null) {
  selected = data;
  form.reset();
  msg($("#edit-error"));
  for (const field of $$("input[name]", form)) field.value = data?.[field.name] ?? "";
  $("#edit-title").textContent = data ? "Edit station" : "Add station";
  $("#save").textContent = data ? "Save changes" : "Add station";
  editBox.showModal();
}

function del(data) {
  selected = data;
  $("#del-name").textContent = `${data.networkCode}.${data.stationCode}`;
  msg($("#del-error"));
  delBox.showModal();
}

async function run(box, task, text) {
  if (saving) return;
  saving = true;
  busy(box, true);
  msg($(".notice-error", box));
  try {
    await task();
    box.close();
    toast(text);
    $("#add").focus();
    await load();
  } catch (err) {
    toast(error(err), true);
    if (!auth(err)) msg($(".notice-error", box), error(err));
  } finally {
    saving = false;
    busy(box, false);
  }
}

form.onsubmit = e => {
  e.preventDefault();
  const data = {};
  for (const field of $$("input[name]", form)) {
    const value = field.value.trim();
    data[field.name] = value === "" ? null : field.type === "number" ? Number(value) : value;
  }
  if ((data.latitude === null) !== (data.longitude === null)) {
    msg($("#edit-error"), "Enter both latitude and longitude, or leave both blank.");
    $(data.latitude === null ? "#lat" : "#lng").focus();
    return;
  }
  run(editBox, () => selected ? station.edit(selected.id, data) : station.add(data),
    selected ? "Station updated successfully." : "Station added successfully.");
};

$("#del-form").onsubmit = e => {
  e.preventDefault();
  run(delBox, () => station.del(selected.id), "Station deleted successfully.");
};

for (const box of [editBox, delBox]) {
  box.oncancel = e => { if (saving) e.preventDefault(); };
  for (const btn of $$("[data-close]", box)) btn.onclick = () => box.close();
}

function apply() {
  params = Object.fromEntries([...new FormData(filters)].map(([key, value]) => [key, value.trim()]).filter(([, value]) => value));
  offset = 0;
  load();
}

async function init() {
  if (!token()) return logout();
  $("#access-status").textContent = "Checking administrator access…";
  $("#retry-access").hidden = true;
  msg($("#page-error"));
  try {
    const data = await user.me();
    if (data.role !== "admin") return deny();
    $("#access-status").textContent = "";
    panel.hidden = false;
    await load();
  } catch (err) {
    if (auth(err)) return;
    $("#access-status").textContent = "Your session could not be checked.";
    msg($("#page-error"), error(err));
    $("#retry-access").hidden = false;
  }
}

filters.onsubmit = e => { e.preventDefault(); apply(); };
$("#clear").onclick = () => { filters.reset(); apply(); };
$("#add").onclick = () => edit();
$("#prev").onclick = () => { offset -= limit; load(); };
$("#next").onclick = () => { offset += limit; load(); };
$("#retry-list").onclick = load;
$("#retry-access").onclick = init;
$("#sign-out").onclick = logout;
init();
