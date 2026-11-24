const connection = byId("twitch-state");
const twitchForm = byId("twitch-connect");
const authorization = byId("twitch-activation");
let polling = false;
let seenLogin = null;
let manualSelection = false;

form("twitch-connect", async data => {
  const activation = await request("/api/twitch/connect", data);
  byId("twitch-url").href = activation.url;
  byId("twitch-code").textContent = activation.code;
  authorization.hidden = false;
  await syncPanel();
});

async function syncPanel() {
  if (polling) return;
  polling = true;
  try {
    const state = await request("/api/twitch");
    connection.textContent = state.message + (state.ready && state.login ? " · @" + state.login : "");
    twitchForm.hidden = state.ready || state.pending;
    if (state.ready || !state.pending) authorization.hidden = true;
    if (state.login !== seenLogin) {
      seenLogin = state.login;
      manualSelection = false;
    }
    await refresh(!manualSelection && (state.ready || !selected) ? null : selected);
  } catch {
    connection.textContent = "Связь с локальным сервером потеряна.";
  } finally {
    polling = false;
  }
}

byId("sessions").addEventListener("change", () => { manualSelection = true; });

window.addEventListener("DOMContentLoaded", () => {
  syncPanel();
  setInterval(syncPanel, 3500);
});
