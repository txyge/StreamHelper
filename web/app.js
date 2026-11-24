const byId = id => document.getElementById(id);
let selected = null;
let current = null;

async function request(path, data) {
  const options = data === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data)
  };
  return parseResponse(await fetch(path, options));
}

async function parseResponse(response) {
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error);
  return payload;
}

function status(message, error = false) {
  byId("status").textContent = message;
  byId("status").classList.toggle("error", error);
}

function run(action, success = "") {
  return async event => {
    event?.preventDefault();
    try {
      await action(event);
      status(success);
    } catch (error) {
      status(error.message, true);
    }
  };
}

function form(id, action) {
  byId(id).addEventListener("submit", run(async () => {
    const element = byId(id);
    const button = element.querySelector("button");
    button.disabled = true;
    try {
      await action(Object.fromEntries(new FormData(element)));
    } finally {
      button.disabled = false;
    }
  }));
}

function option(value, label) {
  return new Option(label, value);
}

function list(id, items, render, empty) {
  const container = byId(id);
  container.replaceChildren();
  for (const item of items) {
    const row = document.createElement("li");
    render(row, item);
    container.append(row);
  }
  if (!items.length) {
    const row = document.createElement("li");
    row.textContent = empty;
    container.append(row);
  }
}

async function refresh(preferred = selected) {
  const sessions = await request("/api/sessions");
  const select = byId("sessions");
  select.replaceChildren(option("", "Выберите эфир"), ...sessions.map(item =>
    option(String(item.id), item.title + (item.ended === null ? " · в эфире" : " · завершён"))
  ));
  const target = preferred ?? (sessions.length ? String(sessions[0].id) : "");
  selected = target;
  select.value = target;
  const detail = target ? await request("/api/sessions/" + target) : null;
  if (selected !== target) return;
  current = detail;
  render();
}

function date(seconds) {
  return new Date(seconds * 1000).toLocaleString("ru-RU");
}

function render() {
  byId("session").hidden = !current;
  byId("summary").hidden = !current;
  byId("chat").hidden = !current;
  renderMedia();
  renderPublication();
  if (!current) return;
  renderChat();
  const {session, duration, marks} = current;
  const live = session.ended === null;
  byId("session-info").textContent = session.title + " · Начало " + date(session.started)
    + (live ? "" : " · Завершение " + date(session.ended));
  byId("finish").hidden = !live;
  byId("mark").hidden = !live;
  byId("summary-title").textContent = live ? "Таймкоды" : "Личные итоги";
  byId("duration").textContent = (live ? "От начала эфира " : "Длительность ") + time(duration);
  list("marks", marks, (row, item) => {
    row.textContent = time(item.seconds) + " · " + item.label + (item.note ? " · " + item.note : "");
  }, "Отметок пока нет.");
}

const action = (name, data, sid = selected) => request("/api/sessions/" + sid + "/" + name, data);
form("start", async data => {
  const result = await request("/api/sessions", data);
  byId("start").reset();
  await refresh(String(result.id));
});
form("mark", async data => {
  await action("marks", data);
  byId("mark").reset();
  await refresh();
});
byId("finish").addEventListener("click", run(async () => {
  await action("finish", {});
  await refresh();
}));
byId("sessions").addEventListener("change", run(async event => {
  selected = event.target.value;
  await refresh();
}));
function itemButton(row, label, name, id) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", run(async () => {
    await action(name, {id});
    await refresh();
  }));
  row.append(" ", button);
}

let rulesSession = null;
function renderChat() {
  const {session, messages, hidden, flagged_count, questions, settings} = current;
  const live = session.ended === null;
  byId("message").hidden = !live;
  byId("rules").hidden = !live;
  if (rulesSession !== session.id) {
    rulesSession = session.id;
    byId("rules").elements.game.value = settings.game;
    byId("rules").elements.phrases.value = settings.phrases.join("\n");
  }
  byId("hidden-count").textContent = "Сейчас скрыто " + hidden.length + " · Всего срабатываний " + flagged_count;
  list("messages", messages, (row, item) => {
    row.textContent = item.nick + " · " + item.body;
  }, "Сообщений пока нет.");
  list("hidden-messages", hidden, (row, item) => {
    row.textContent = item.nick + " · " + item.body + " · Правило «" + item.rule + "»";
    itemButton(row, "Восстановить", "restore", item.id);
  }, "Очередь проверки пуста.");
  list("questions", questions, (row, item) => {
    row.textContent = item.nick + " · " + item.body + " · " + (item.answered ? "Отвечен" : "Новый");
    if (!item.answered) itemButton(row, "Отметить отвеченным", "answer", item.id);
  }, "Вопросов пока нет.");
}

form("message", async data => {
  await action("message", data);
  byId("message").elements.body.value = "";
  await refresh();
});
form("rules", async data => {
  await action("rules", data);
  rulesSession = null;
  await refresh();
});
window.addEventListener("DOMContentLoaded", run(() => refresh()));
