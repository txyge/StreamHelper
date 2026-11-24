const byId = id => document.getElementById(id);
const query = new URLSearchParams(location.search);
const panelMode = {marks:"Таймкоды", questions:"Вопросы к стримеру"};
const requestedPanel = query.get("panel");
const popoutMode = Object.hasOwn(panelMode, requestedPanel) ? requestedPanel : null;
const requestedSession = query.get("session");
let selected = popoutMode && /^[0-9]+$/.test(requestedSession) ? requestedSession : null;

if (popoutMode) {
  document.body.dataset.panel = popoutMode;
  byId("page-title").textContent = panelMode[popoutMode];
  document.title = panelMode[popoutMode] + " · StreamHelper";
}

const themeControl = byId("theme-choice");
const themeKey = "streamhelper.theme";
function setTheme(value) {
  const theme = ["light", "dark"].includes(value) ? value : "system";
  document.documentElement.dataset.theme = theme;
  themeControl.value = theme;
}
try { setTheme(localStorage.getItem(themeKey)); } catch { setTheme("system"); }
themeControl.addEventListener("change", () => {
  setTheme(themeControl.value);
  try { localStorage.setItem(themeKey, themeControl.value); } catch { /* Private storage is unavailable. */ }
});
window.addEventListener("storage", event => {
  if (event.key === themeKey || event.key === null) setTheme(event.newValue);
});

for (const link of document.querySelectorAll("[data-popout]")) {
  link.addEventListener("click", event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    window.open(link.href, "_blank", "popup,noopener,width=580,height=760");
  });
}
let current = null;
let sessionOptions = "";
let questionSnapshot = "";

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
      const message = await action(event);
      status(typeof message === "string" ? message : success);
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
      return await action(Object.fromEntries(new FormData(element)));
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
    row.className = "empty";
    container.append(row);
  }
}

async function refresh(preferred = selected) {
  const sessions = await request("/api/sessions");
  const select = byId("sessions");

  const snapshot = JSON.stringify(sessions);
  if (snapshot !== sessionOptions) {
    select.replaceChildren(option("", "Выберите эфир"), ...sessions.map(item =>
      option(String(item.id), item.title + (item.ended === null ? " · в эфире" : " · завершён"))
    ));
    sessionOptions = snapshot;
  }
  const activeSession = sessions.find(item => item.ended === null);
  byId("start").hidden = Boolean(activeSession);
  const latest = activeSession || sessions[0];
  const target = preferred === "" || sessions.some(item => String(item.id) === preferred)
    ? preferred : (latest ? String(latest.id) : "");
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
  byId("duration").hidden = !current;
  byId("session-state").classList.toggle("live", Boolean(current && current.session.ended === null));
  byId("session-state").textContent = current
    ? (current.session.ended === null ? "В эфире" : "Эфир завершён")
    : "Сессия не выбрана";
  for (const link of document.querySelectorAll("[data-session-link]")) link.hidden = !current;
  for (const link of document.querySelectorAll("[data-popout]")) {
    if (current) link.href = "/?panel=" + link.dataset.popout + "&session=" + current.session.id;
  }
  renderSummary();
  if (!current) {
    return;
  }
  renderChat();
  const {session, duration, marks} = current;
  const live = session.ended === null;
  byId("session-info").textContent = session.title + " · Начало " + date(session.started)
    + (live ? "" : " · Завершение " + date(session.ended));
  byId("finish").hidden = !live;
  byId("mark").hidden = !live;
  byId("duration-label").textContent = live ? "От начала эфира" : "Длительность";
  byId("duration-value").textContent = time(duration);
  byId("mark-count").textContent = marks.length;
  byId("mark-count").hidden = !marks.length;
  const unanswered = current.questions.filter(question => !question.answered).length;
  byId("question-count").textContent = "Новых: " + unanswered;
  byId("question-count").hidden = !unanswered;
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
  row.append(button);
}


function renderChat() {

  const snapshot = JSON.stringify([current.session.id, current.questions]);
  if (snapshot === questionSnapshot) return;
  questionSnapshot = snapshot;
  const questions = [...current.questions].sort((a, b) => Number(a.answered) - Number(b.answered));
  list("questions", questions, (row, item) => {
    row.className = "question-card";
    const meta = document.createElement("div");
    meta.className = "question-meta";
    const author = document.createElement("strong");
    author.textContent = item.nick;
    const state = document.createElement("span");
    state.className = item.answered ? "question-state answered" : "question-state";
    state.textContent = item.answered ? "Отвечен" : "Новый";
    meta.append(author, state);
    const text = document.createElement("p");
    text.className = "question-text";
    text.textContent = item.body;
    row.append(meta, text);
    if (!item.answered) itemButton(row, "Отметить отвеченным", "answer", item.id);
  }, "Вопросов пока нет.");
}
