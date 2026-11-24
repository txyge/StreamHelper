const player = byId("recording-video");
const fileInput = byId("recording-file");
let recording = null;
let mediaSession = null;
let exporting = false;

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
  const sid = selected;
  exporting = true;
  byId("save-clip").disabled = true;
  status("Экспортируем клип…");
  try {
    await action("clips", {recording, position: player.currentTime}, sid);
    if (selected === sid) await refresh();
  } finally {
    exporting = false;
    byId("save-clip").disabled = false;
  }
}, "Клип сохранён.");
byId("save-clip").addEventListener("click", saveClip);
player.addEventListener("error", () => status("Браузер не смог открыть запись. Попробуйте MP4 с кодеком H.264.", true));

const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
const voiceButton = byId("voice");
const voiceStatus = byId("voice-status");
let recognition = null;
if (!Speech) voiceStatus.textContent = "Этот браузер не поддерживает распознавание речи.";
voiceButton.addEventListener("click", () => {
  if (!Speech) return;
  if (recognition) {
    recognition.stop();
    return;
  }
  const listen = new Speech();
  listen.lang = "ru-RU";
  listen.interimResults = false;
  recognition = listen;
  voiceButton.textContent = "Остановить прослушивание";
  voiceStatus.textContent = "Произнесите «Сохрани клип».";
  let resultMessage = "Прослушивание завершено.";
  listen.onresult = event => {
    const phrase = event.results[0][0].transcript.toLocaleLowerCase("ru").trim().replace(/[.!?…]+$/, "");
    if (phrase === "сохрани клип") {
      resultMessage = "Команда распознана.";
      saveClip();
    } else {
      resultMessage = "Команда не распознана. Произнесите «Сохрани клип».";
    }
  };
  listen.onerror = event => {
    const messages = {
      "not-allowed": "Разрешите браузеру доступ к микрофону.",
      "service-not-allowed": "Браузер запретил сервис распознавания.",
      "audio-capture": "Микрофон недоступен.",
      "network": "Сервис распознавания недоступен по сети.",
      "no-speech": "Речь не обнаружена."
    };
    resultMessage = messages[event.error] || "Ошибка распознавания: " + event.error;
    voiceStatus.textContent = resultMessage;
  };
  const reset = () => {
    recognition = null;
    voiceButton.textContent = "Включить голос";
    voiceStatus.textContent = resultMessage;
  };
  listen.onend = reset;
  try {
    listen.start();
  } catch {
    resultMessage = "Браузер не смог запустить распознавание.";
    reset();
  }
});
