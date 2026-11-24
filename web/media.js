const player = byId("recording-video");
const fileInput = byId("recording-file");
let recording = null;
let mediaSession = null;
let exporting = false;
const clipDuration = byId("clip-duration");

function useRecording(item) {
  const id = item?.id ?? null;
  if (recording === id) return;
  recording = id;
  if (id) {
    player.src = "/recordings/" + id;
  } else {
    player.removeAttribute("src");
    player.load();
  }
}

function renderMedia() {
  byId("media").hidden = !current || current.card.source === "twitch";
  if (!current) {
    mediaSession = null;
    useRecording(null);
    return;
  }
  if (mediaSession !== current.session.id) {
    fileInput.value = "";
  }
  mediaSession = current.session.id;
  useRecording(current.recordings[0]);
  list("clips", current.clips, (row, item) => {
    const url = "/clips/" + item.id;
    row.append("Запись " + time(item.start) + " – " + time(item.end) + " · ");
    const watch = document.createElement("a");
    watch.textContent = "Смотреть";
    watch.href = url;
    watch.target = "_blank";
    watch.rel = "noopener";
    const download = document.createElement("a");
    download.textContent = "Скачать";
    download.href = url + "?download=1";
    download.download = "clip-" + item.id.slice(0, 8) + ".mp4";
    row.append(watch, " · ", download);
  }, "Сохранённых клипов пока нет.");
}

async function upload(file) {
  const sid = selected;
  const mime = /\.webm$/i.test(file.name) ? "video/webm" : "video/mp4";
  if (!/\.(mp4|webm)$/i.test(file.name)) throw new Error("Выберите MP4 или WebM.");
  const button = byId("load-demo");
  fileInput.disabled = button.disabled = true;
  status("Загружаем запись…");
  try {
    await parseResponse(await fetch("/api/sessions/" + sid + "/recording", {
      method: "POST", headers: {"Content-Type": mime}, body: file
    }));
    if (selected === sid) await refresh();
  } finally {
    fileInput.disabled = button.disabled = false;
  }
}

fileInput.addEventListener("change", run(async () => {
  const file = fileInput.files[0];
  if (!file) return;
  try { await upload(file); } finally { fileInput.value = ""; }
}));
byId("load-demo").addEventListener("click", run(async () => {
  const response = await fetch("/demo.mp4");
  if (!response.ok) throw new Error("Деморолик недоступен.");
  await upload(new File([await response.blob()], "demo.mp4", {type: "video/mp4"}));
}));

form("seek", async ({seconds}) => {
  if (!recording || player.readyState < 1) throw new Error("Сначала загрузите запись.");
  const position = Number(seconds);
  if (!Number.isFinite(position) || position < 0 || position > player.duration) {
    throw new Error("Позиция выходит за пределы записи.");
  }
  player.currentTime = position;
});

const saveClip = run(async () => {
  if (exporting) return;
  if (!recording || player.readyState < 1) throw new Error("Сначала загрузите запись.");
  if (!(player.currentTime > 0)) throw new Error("Пустой отрезок. Перейдите к нужной позиции записи.");
  if (!clipDuration.reportValidity()) return;
  const sid = selected;
  exporting = true;
  byId("save-clip").disabled = true;
  status("Экспортируем клип…");
  try {
    await action("clips", {recording, position: player.currentTime, duration: clipDuration.valueAsNumber}, sid);
    if (selected === sid) await refresh();
  } finally {
    exporting = false;
    byId("save-clip").disabled = false;
  }
}, "Клип сохранён.");
byId("save-clip").addEventListener("click", saveClip);

player.addEventListener("error", () => status("Браузер не смог открыть запись. Попробуйте MP4 с кодеком H.264.", true));

const hotkeyStorage = "streamhelper.localClipHotkey";
const bindHotkey = byId("clip-hotkey");
const clearHotkey = byId("clear-clip-hotkey");
const hotkeyStatus = byId("clip-hotkey-status");
const allowedHotkey = /^(Key[A-Z]|Digit[0-9])$/;
let hotkey = readHotkey();
let assigningHotkey = false;

function readHotkey() {
  try {
    const saved = localStorage.getItem(hotkeyStorage);
    return allowedHotkey.test(saved) ? saved : "";
  } catch {
    return "";
  }
}

function setHotkey(value) {
  hotkey = value;
  assigningHotkey = false;
  renderHotkey();
  try {
    if (value) localStorage.setItem(hotkeyStorage, value);
    else localStorage.removeItem(hotkeyStorage);
  } catch {
    hotkeyStatus.textContent += " Браузер заблокировал сохранение настройки.";
  }
}

function renderHotkey() {
  bindHotkey.textContent = assigningHotkey ? "Отменить назначение" : "Назначить клавишу";
  clearHotkey.hidden = !hotkey;
  if (assigningHotkey) {
    hotkeyStatus.textContent = "Нажмите букву или цифру. Esc отменяет назначение.";
  } else {
    hotkeyStatus.textContent = (hotkey ? "Клавиша: " + hotkey.slice(-1) + "." : "Клавиша не назначена.")
      + " Работает, пока панель в фокусе.";
  }
}

bindHotkey.addEventListener("click", () => {
  assigningHotkey = !assigningHotkey;
  renderHotkey();
});
clearHotkey.addEventListener("click", () => setHotkey(""));
document.addEventListener("keydown", event => {
  if (byId("media").hidden || event.repeat || event.isComposing) return;
  if (assigningHotkey && event.code === "Escape") {
    event.preventDefault();
    assigningHotkey = false;
    renderHotkey();
    return;
  }
  if (event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return;
  if (assigningHotkey && allowedHotkey.test(event.code)) {
    event.preventDefault();
    setHotkey(event.code);
    return;
  }
  if (!assigningHotkey && hotkey === event.code &&
      !event.defaultPrevented && !event.target.closest("input, textarea, select, [contenteditable], [role=textbox]")) {
    event.preventDefault();
    byId("save-clip").click();
  }
});
renderHotkey();
