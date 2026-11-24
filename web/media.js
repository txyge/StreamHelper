form("clip-form", async ({duration}) => {
  if (!current || current.card.source !== "twitch") {
    throw new Error("Выберите текущий прямой эфир Twitch.");
  }
  await action("twitchclip", {duration: Number(duration)});
  return "Twitch принял запрос. Ссылка появится после обработки.";
});

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
  if (event.repeat || event.isComposing) return;
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
      !event.defaultPrevented && !(event.target instanceof Element && event.target.closest("input, textarea, select, [contenteditable], [role=textbox]"))) {
    event.preventDefault();
    byId("save-clip").click();
  }
});
renderHotkey();
