function time(seconds) {
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map(value => String(value).padStart(2, "0")).join(":");
}

function renderSummary() {
  const panel = byId("report");
  panel.hidden = !current;
  if (!current) return;
  const report = current.report;
  byId("report-title").textContent = report.title;
  byId("report-duration").textContent = "Длительность " + time(report.duration);
  byId("donation-updated").textContent = report.donations_synced
    ? "Обновлено: " + date(report.donations_synced)
    : "История DonationAlerts ещё не загружена для этой сессии.";
  list("topics", report.topics, (row, item) => {
    row.textContent = [date(item.occurred), item.category, item.title].filter(Boolean).join(" · ");
  }, "Категории и названия ещё не получены.");
  list("viewers", report.viewers, (row, name) => { row.textContent = name; }, "Никого пока не обнаружено.");
  list("moderators", report.moderators, (row, name) => { row.textContent = name; }, "Модераторы пока не обнаружены.");
  list("donations", report.donations, (row, item) => {
    row.textContent = [date(item.occurred), item.name, item.amount + " " + item.currency].join(" · ");
  }, report.donations_synced ? "За этот интервал донатов нет." : "Данные пока недоступны.");
}

byId("sync-donations").addEventListener("click", run(async () => {
  const button = byId("sync-donations");
  button.disabled = true;
  try {
    await action("donations", {});
    await refresh();
  } finally {
    button.disabled = false;
  }
}, "История донатов обновлена."));

let polling = false;
let chosenSession = false;
byId("sessions").addEventListener("change", () => { chosenSession = true; });
async function poll() {
  if (polling) return;
  polling = true;
  try {
    const state = await request("/api/connections");
    byId("bot-state").textContent = state.bot;
    byId("da-state").textContent = state.donations.message || (state.donations.connected
      ? "DonationAlerts подключён." : "DonationAlerts не подключён.");
    byId("da-connect").hidden = !state.donations.configured;
    await refresh(chosenSession ? selected : null);
  } catch {
    byId("bot-state").textContent = "Локальный сервер недоступен.";
  } finally {
    polling = false;
  }
}
window.addEventListener("DOMContentLoaded", () => {
  poll();
  setInterval(poll, 3500);
});
