import { user } from "./api.js";
import { token, logout } from "./session.js";
import { $, $$, el, msg, busy } from "./ui.js";

const panel = $("#users");
const rows = $("#rows");
const form = $("#edit-form");
const editBox = $("#edit-box");
const delBox = $("#del-box");
const limit = 20;
let offset = 0;
let total = 0;
let selected = null;
let saving = false;
let loading = false;

function toast(text, bad = false) {
  const box = el("div", "", `toast-item${bad ? " error" : ""}`);
  const close = el("button", "×", "btn");
  close.type = "button";
  close.setAttribute("aria-label", "Dismiss notification");
  box.append(el("p", text), close);
  $("#toasts").append(box);
  let timer;
  const stop = () => clearTimeout(timer);
  const hide = () => { stop(); box.remove(); };
  const start = () => { stop(); timer = setTimeout(hide, bad ? 10000 : 6000); };
  box.onmouseenter = box.onfocusin = stop;
  box.onmouseleave = box.onfocusout = start;
  close.onclick = hide;
  start();
}

function deny() {
  panel.hidden = true;
  rows.replaceChildren();
  editBox.close();
  delBox.close();
  $("#access-status").textContent = "Administrator access is required to manage users.";
  $("#retry-access").hidden = true;
}

function auth(err) {
  if (err.status === 401) { logout(); return true; }
  if (err.status === 403) { deny(); return true; }
  return false;
}

function error(err) {
  if (err.code === "email_exists") return "An account with this email already exists.";
  if (err.code === "last_admin") return "The last active administrator cannot be deleted, disabled, or changed to another role.";
  if (err.status === 404) return "This account no longer exists. Refresh the user list and try again.";
  return err.message;
}

function row(data) {
  const node = $("#user-row").content.firstElementChild.cloneNode(true);
  $("[data-id]", node).textContent = data.id;
  $("[data-name]", node).textContent = data.displayName;
  $("[data-email]", node).textContent = data.email;
  if (!data.enabled) $("[data-name]", node).append(el("span", "Disabled", "disabled-tag"));
  const editBtn = $(".edit-btn", node);
  const delBtn = $(".del-btn", node);
  editBtn.setAttribute("aria-label", `Edit ${data.displayName}`);
  delBtn.setAttribute("aria-label", `Delete ${data.displayName}`);
  editBtn.onclick = () => edit(data);
  delBtn.onclick = () => del(data);
  delBtn.disabled = !data.enabled;
  return node;
}

function pages() {
  $("#prev").disabled = loading || offset === 0;
  $("#next").disabled = loading || offset + limit >= total;
  $("#add-user").disabled = loading;
}

async function load() {
  if (loading) return;
  loading = true;
  pages();
  rows.replaceChildren();
  $("#list-status").textContent = "Loading users…";
  $("#retry-list").hidden = true;
  msg($("#page-error"));
  try {
    let data = await user.list({ offset, limit });
    if (data.total && offset >= data.total) {
      offset = Math.floor((data.total - 1) / limit) * limit;
      data = await user.list({ offset, limit });
    }
    total = data.total;
    rows.replaceChildren(...data.items.map(row));
    if (!total) {
      offset = 0;
      const empty = el("tr");
      const cell = el("td", "No users found. Add a user to get started.");
      cell.colSpan = 4;
      empty.append(cell);
      rows.append(empty);
    }
    $("#list-status").textContent = total ? `Showing ${offset + 1}–${offset + data.items.length} of ${total} users` : "0 users";
  } catch (err) {
    if (auth(err)) return;
    total = 0;
    $("#list-status").textContent = "Users could not be loaded.";
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
  $("#edit-title").textContent = data ? "Edit user" : "Add user";
  $("#save-user").textContent = data ? "Save changes" : "Add user";
  $("#name").value = data?.displayName || "";
  $("#email").value = data?.email || "";
  $("#role").value = data?.role || "user";
  $("#enabled").checked = data?.enabled ?? true;
  $("#enabled-group").hidden = !data;
  $("#pass-group").hidden = !!data;
  $("#pass").required = !data;
  editBox.showModal();
}

function del(data) {
  selected = data;
  $("#del-name").textContent = `${data.displayName} (${data.email})`;
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
    $("#add-user").focus();
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
  const data = {
    displayName: $("#name").value.trim(),
    email: $("#email").value.trim().toLowerCase(),
    role: $("#role").value
  };
  if (!data.displayName || !data.email) return msg($("#edit-error"), "Enter a name and email.");
  if (selected) data.enabled = $("#enabled").checked;
  else data.password = $("#pass").value;
  run(editBox, () => selected ? user.edit(selected.id, data) : user.add(data),
    selected ? "User updated successfully." : "User added successfully.");
};

$("#del-form").onsubmit = e => {
  e.preventDefault();
  run(delBox, () => user.del(selected.id), "User deleted successfully. Their account is now disabled.");
};

for (const box of [editBox, delBox]) {
  box.oncancel = e => { if (saving) e.preventDefault(); };
  box.onclose = () => { $("#pass").value = ""; };
  for (const btn of $$("[data-close]", box)) btn.onclick = () => box.close();
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

$("#add-user").onclick = () => edit();
$("#prev").onclick = () => { offset -= limit; load(); };
$("#next").onclick = () => { offset += limit; load(); };
$("#retry-list").onclick = load;
$("#retry-access").onclick = init;
$("#sign-out").onclick = logout;
init();
