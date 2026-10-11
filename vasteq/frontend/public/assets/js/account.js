import { user } from "./api.js";
import { token, logout } from "./session.js";
import { $, msg } from "./ui.js";

const status = $("#status");
const alert = $("#error");
const retry = $("#retry");

async function load() {
  if (!token()) return logout();
  msg(alert);
  retry.hidden = true;
  status.textContent = "Loading your account…";
  try {
    const data = await user.me();
    $("#name").textContent = data.displayName;
    $("#email").textContent = data.email;
    $("#account").hidden = false;
    status.textContent = "You're signed in to VAST-Earthquake.";
  } catch (err) {
    if (err.status === 401) return logout();
    status.textContent = "Your account could not be loaded.";
    msg(alert, err.status ? "Unable to load your account. Please try again." : err.message);
    retry.hidden = false;
  }
}

$("#sign-out").onclick = logout;
retry.onclick = load;
load();
