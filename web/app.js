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
    container.append(row);
  }
}

async function refresh(preferred = selected) {
  const sessions = await request("/api/sessions");
  const select = byId("sessions");
  select.replaceChildren(option("", "Выберите эфир"), ...sessions.map(item =>
    option(String(item.id), item.title + (item.ended === null ? " · в эфире" : " · завершён"))
  ));
  const latest = sessions.find(item => item.ended === null) || sessions[0];
  const target = preferred ?? (latest ? String(latest.id) : "");
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


function renderChat() {
  list("questions", current.questions, (row, item) => {
    row.textContent = item.nick + " · " + item.body + " · " + (item.answered ? "Отвечен" : "Новый");
    if (!item.answered) itemButton(row, "Отметить отвеченным", "answer", item.id);
  }, "Вопросов пока нет.");
}
