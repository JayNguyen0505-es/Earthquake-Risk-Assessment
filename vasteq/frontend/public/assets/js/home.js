import { userApi } from "./api.js";
import { getToken, clearSession } from "./session.js";

const status = document.querySelector("#home-status");
const alert = document.querySelector("#home-error");
const retry = document.querySelector("#retry-button");

function signOut() {
  clearSession();
  window.location.replace("login.html");
}

async function loadAccount() {
  if (!getToken()) { signOut(); return; }
  alert.hidden = true;
  retry.hidden = true;
  status.textContent = "Loading your account…";
  try {
    const user = await userApi.me();
    if (!user || typeof user.displayName !== "string" || typeof user.email !== "string")
      throw new Error("Invalid account response");
    document.querySelector("#account-name").textContent = user.displayName;
    document.querySelector("#account-email").textContent = user.email;
    document.querySelector("#account").hidden = false;
    status.textContent = "You're signed in to VAST-Earthquake.";
  } catch (error) {
    if (error.status === 401) { signOut(); return; }
    status.textContent = "Your account could not be loaded.";
    alert.textContent = error.status === 0 ? error.message : "Unable to load your account. Please try again.";
    alert.hidden = false;
    retry.hidden = false;
  }
}

document.querySelector("#sign-out").addEventListener("click", signOut);
retry.addEventListener("click", loadAccount);
loadAccount();
