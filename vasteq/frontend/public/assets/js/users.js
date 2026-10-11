import { userApi } from "./api.js";
import { getToken, clearSession } from "./session.js";

const $ = (selector) => document.querySelector(selector);
const panel = $("#user-management");
const tbody = $("#users-body");
const userDialog = $("#user-dialog");
const deleteDialog = $("#delete-dialog");
const userForm = $("#user-form");
const pageSize = 20;
let users = [];
let offset = 0;
let total = 0;
let selectedUser = null;
let saving = false;
let loading = false;

function signOut() {
  clearSession();
  window.location.replace("login.html");
}

function showError(element, message) {
  element.textContent = message;
  element.hidden = !message;
}

function toast(message, error = false) {
  const notification = document.createElement("div");
  notification.className = `notification${error ? " error" : ""}`;
  const text = document.createElement("p");
  text.textContent = message;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "btn";
  close.setAttribute("aria-label", "Dismiss notification");
  close.textContent = "×";
  notification.append(text, close);
  $("#toast-region").append(notification);
  // Pause automatic dismissal while the notification is being read or focused.
  let timer;
  const dismiss = () => { clearTimeout(timer); notification.remove(); };
  const resume = () => { clearTimeout(timer); timer = setTimeout(dismiss, error ? 10000 : 6000); };
  notification.addEventListener("mouseenter", () => clearTimeout(timer));
  notification.addEventListener("mouseleave", resume);
  notification.addEventListener("focusin", () => clearTimeout(timer));
  notification.addEventListener("focusout", resume);
  close.addEventListener("click", dismiss);
  resume();
}

function accessDenied() {
  panel.hidden = true;
  tbody.replaceChildren();
  users = [];
  userDialog.close();
  deleteDialog.close();
  $("#access-status").textContent = "Administrator access is required to manage users.";
  $("#retry-access").hidden = true;
}

function handleAccessError(error) {
  if (error.status === 401) { signOut(); return true; }
  if (error.status === 403) { accessDenied(); return true; }
  return false;
}

function errorMessage(error) {
  if (error.code === "email_exists") return "An account with this email already exists.";
  if (error.code === "last_admin") return "The last active administrator cannot be deleted, disabled, or changed to another role.";
  if (error.status === 404) return "This account no longer exists. Refresh the user list and try again.";
  return error.message || "The request could not be completed. Please try again.";
}

function updatePagination() {
  $("#previous-page").disabled = loading || offset === 0;
  $("#next-page").disabled = loading || offset + pageSize >= total;
  $("#add-user").disabled = loading;
}

function userRow(user) {
  const row = document.createElement("tr");
  for (const value of [user.id, user.displayName, user.email]) {
    const cell = document.createElement("td");
    cell.textContent = value;
    row.append(cell);
  }
  if (!user.enabled) {
    const badge = document.createElement("span");
    badge.className = "disabled-label";
    badge.textContent = "Disabled";
    row.children[1].append(badge);
  }
  const actions = document.createElement("td");
  actions.className = "actions-column";
  for (const action of ["Edit", "Delete"]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `btn row-action${action === "Delete" ? " delete-action" : ""}`;
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("aria-hidden", "true");
    icon.setAttribute("focusable", "false");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    // Material Design edit and delete icons, embedded to avoid external fonts.
    path.setAttribute("d", action === "Edit"
      ? "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a.996.996 0 0 0 0-1.41l-2.34-2.34a.996.996 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"
      : "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z");
    icon.append(path);
    button.append(icon);
    button.title = action;
    button.setAttribute("aria-label", `${action} ${user.displayName}`);
    button.disabled = action === "Delete" && !user.enabled;
    button.addEventListener("click", () => action === "Edit" ? openUser(user) : openDelete(user));
    actions.append(button);
  }
  row.append(actions);
  return row;
}

async function loadUsers() {
  if (loading) return;
  loading = true;
  updatePagination();
  tbody.replaceChildren();
  $("#list-status").textContent = "Loading users…";
  $("#retry-list").hidden = true;
  showError($("#page-error"), "");
  try {
    let data = await userApi.list({ offset, limit: pageSize });
    // A concurrent deletion may have emptied the last page.
    if (Number.isInteger(data?.total) && data.total > 0 && offset >= data.total) {
      offset = Math.floor((data.total - 1) / pageSize) * pageSize;
      data = await userApi.list({ offset, limit: pageSize });
    }
    if (!Array.isArray(data?.items) || !Number.isInteger(data.total) || data.total < 0 ||
        data.items.some(user => !Number.isInteger(user.id) || typeof user.displayName !== "string" ||
          typeof user.email !== "string" || typeof user.enabled !== "boolean"))
      throw new Error("Unable to read the user list. Please try again.");
    users = data.items;
    total = data.total;
    tbody.replaceChildren(...users.map(userRow));
    if (total === 0) {
      offset = 0;
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 4;
      cell.textContent = "No users found. Add a user to get started.";
      row.append(cell);
      tbody.append(row);
    }
    $("#list-status").textContent = total ? `Showing ${offset + 1}–${offset + users.length} of ${total} users` : "0 users";
  } catch (error) {
    if (handleAccessError(error)) return;
    users = [];
    total = 0;
    $("#list-status").textContent = "Users could not be loaded.";
    showError($("#page-error"), errorMessage(error));
    $("#retry-list").hidden = false;
  } finally {
    loading = false;
    updatePagination();
  }
}

function openUser(user = null) {
  selectedUser = user;
  userForm.reset();
  showError($("#user-form-error"), "");
  $("#user-dialog-title").textContent = user ? "Edit user" : "Add user";
  $("#save-user").textContent = user ? "Save changes" : "Add user";
  $("#user-name").value = user?.displayName || "";
  $("#user-email").value = user?.email || "";
  $("#user-role").value = user?.role || "user";
  $("#user-enabled").checked = user?.enabled ?? true;
  $("#enabled-group").hidden = !user;
  $("#password-group").hidden = Boolean(user);
  $("#user-password").required = !user;
  $("#user-password").disabled = Boolean(user);
  userDialog.showModal();
}

function openDelete(user) {
  selectedUser = user;
  $("#delete-user-name").textContent = `${user.displayName} (${user.email})`;
  showError($("#delete-error"), "");
  deleteDialog.showModal();
}

function setSaving(dialog, busy) {
  saving = busy;
  dialog.setAttribute("aria-busy", String(busy));
  for (const control of dialog.querySelectorAll("input, select, button")) {
    if (busy) { control.dataset.wasDisabled = String(control.disabled); control.disabled = true; }
    else { control.disabled = control.dataset.wasDisabled === "true"; delete control.dataset.wasDisabled; }
  }
}

userForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (saving) return;
  const displayName = $("#user-name").value.trim();
  const email = $("#user-email").value.trim().toLowerCase();
  if (!displayName || !email) {
    showError($("#user-form-error"), "Enter a name and email.");
    return;
  }
  const editing = Boolean(selectedUser);
  const account = { displayName, email, role: $("#user-role").value };
  if (editing) account.enabled = $("#user-enabled").checked;
  else account.password = $("#user-password").value;
  setSaving(userDialog, true);
  showError($("#user-form-error"), "");
  try {
    if (editing) await userApi.update(selectedUser.id, account);
    else await userApi.create(account);
    userDialog.close();
    userForm.reset();
    toast(editing ? "User updated successfully." : "User added successfully.");
    $("#add-user").focus();
    await loadUsers();
  } catch (error) {
    const message = errorMessage(error);
    toast(message, true);
    if (!handleAccessError(error)) showError($("#user-form-error"), message);
  } finally { setSaving(userDialog, false); }
});

$("#delete-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (saving || !selectedUser) return;
  setSaving(deleteDialog, true);
  showError($("#delete-error"), "");
  try {
    await userApi.remove(selectedUser.id);
    deleteDialog.close();
    toast("User deleted successfully. Their account is now disabled.");
    $("#add-user").focus();
    await loadUsers();
  } catch (error) {
    const message = errorMessage(error);
    toast(message, true);
    if (!handleAccessError(error)) showError($("#delete-error"), message);
  } finally { setSaving(deleteDialog, false); }
});

for (const dialog of [userDialog, deleteDialog]) {
  dialog.addEventListener("cancel", event => { if (saving) event.preventDefault(); });
  for (const close of dialog.querySelectorAll("[data-close]")) {
    close.addEventListener("click", () => { if (!saving) dialog.close(); });
  }
  // Clear the entered password when an add dialog is dismissed.
  dialog.addEventListener("close", () => { $("#user-password").value = ""; });
}

async function initialize() {
  if (!getToken()) { signOut(); return; }
  $("#access-status").textContent = "Checking administrator access…";
  $("#retry-access").hidden = true;
  showError($("#page-error"), "");
  try {
    const viewer = await userApi.me();
    if (viewer.role !== "admin") { accessDenied(); return; }
    $("#access-status").textContent = "";
    panel.hidden = false;
    await loadUsers();
  } catch (error) {
    if (handleAccessError(error)) return;
    $("#access-status").textContent = "Your session could not be checked.";
    showError($("#page-error"), errorMessage(error));
    $("#retry-access").hidden = false;
  }
}

$("#add-user").addEventListener("click", () => openUser());
$("#previous-page").addEventListener("click", () => { offset = Math.max(0, offset - pageSize); loadUsers(); });
$("#next-page").addEventListener("click", () => { offset += pageSize; loadUsers(); });
$("#retry-list").addEventListener("click", loadUsers);
$("#retry-access").addEventListener("click", initialize);
$("#sign-out").addEventListener("click", signOut);
initialize();
