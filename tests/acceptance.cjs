const {chromium} = require("playwright");
const {spawn, execFileSync} = require("node:child_process");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const root = path.join(__dirname, "..");
const directory = fs.mkdtempSync(path.join(process.env.STREAMHELPER_TEST_ROOT || os.tmpdir(), "streamhelper-"));
const python = process.env.STREAMHELPER_PYTHON || "python";
const probe = process.env.STREAMHELPER_FFPROBE || "ffprobe";
const ffmpeg = process.env.STREAMHELPER_FFMPEG || "ffmpeg";

async function startServer(overrides = {}) {
  const app = spawn(python, ["app.py", "--port", "0", "--data", directory], {
    cwd: root, env: {...process.env, ...overrides}, stdio: ["ignore", "pipe", "ignore"]
  });
  const url = await new Promise((resolve, reject) => {
    app.once("error", reject);
    app.once("exit", code => reject(new Error("Server exited: " + code)));
    app.stdout.once("data", data => resolve(data.toString().match(/http:\/\/[^/]+/)[0]));
  });
  return {app, url};
}

async function stopServer(server) {
  if (!server || server.app.exitCode !== null) return;
  await new Promise(resolve => {
    server.app.once("exit", resolve);
    server.app.kill();
  });
}

async function api(url, route, data, expected = 200) {
  const options = data === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)
  };
  const response = await fetch(url + route, options);
  assert.equal(response.status, expected, route);
  return response.json();
}

async function send(page, name, body) {
  await page.getByLabel("Ник", {exact:true}).fill(name);
  await page.getByLabel("Сообщение", {exact:true}).fill(body);
  await page.getByRole("button", {name:"Отправить"}).click();
  await page.waitForFunction(() => document.querySelector("#message input[name=body]").value === "");
}

async function checkClip(page, url, position, duration) {
  await page.getByLabel("Позиция в записи, с").fill(String(position));
  await page.getByRole("button", {name:"Перейти"}).click();
  await page.waitForFunction(p => {
    const video = document.getElementById("recording-video");
    return video.currentTime === p && !video.seeking;
  }, position);
  await page.getByRole("button", {name:"Сохранить последние 30 секунд"}).click();
  await page.getByText("Клип сохранён.", {exact:true}).waitFor();
  const clip = (await api(url, "/api/sessions/1")).clips[0];
  assert.deepEqual([clip.start, clip.end], [Math.max(0, position - 30), position]);
  const download = page.waitForEvent("download");
  await page.getByRole("link", {name:"Скачать"}).first().click();
  const target = path.join(directory, duration + ".mp4");
  await (await download).saveAs(target);
  const actual = Number(execFileSync(probe, [
    "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", target
  ]));
  assert.equal(actual, duration);
  execFileSync(ffmpeg, ["-v", "error", "-xerror", "-i", target, "-f", "null", "-"]);
  const popup = page.context().waitForEvent("page");
  await page.getByRole("link", {name:"Смотреть"}).first().click();
  const clipPage = await popup;
  await clipPage.waitForFunction(() => document.querySelector("video")?.readyState >= 2);
  assert.equal(await clipPage.locator("video").evaluate(video => video.duration), duration);
  await clipPage.close();
  console.log("PASS clip at " + position + " s: duration " + actual + " s, full decode, browser preview and download");
}

(async () => {
  let server, browser;
  try {
    server = await startServer();
    const {url} = server;
    assert.deepEqual(await api(url, "/api/sessions"), []);
    const browserOptions = process.env.STREAMHELPER_EDGE
      ? {executablePath: process.env.STREAMHELPER_EDGE} : {channel: "msedge"};
    browser = await chromium.launch(browserOptions);
    const context = await browser.newContext({acceptDownloads:true});
    context.setDefaultTimeout(9000);
    const page = await context.newPage();
    const viewer = await context.newPage();
    const errors = [];
    const viewerRequests = new Set();
    page.on("pageerror", error => errors.push(error.message));
    viewer.on("pageerror", error => errors.push(error.message));
    viewer.on("request", request => viewerRequests.add(new URL(request.url()).pathname));
    await viewer.goto(url + "/viewer");
    await viewer.getByText("Итоги ещё не опубликованы.").waitFor();
    assert.equal(await api(url, "/api/viewer"), null);

    await page.goto(url);
    await page.getByLabel("Название").fill("Тестовый эфир");
    await page.getByRole("button", {name:"Начать эфир"}).click();
    await page.locator("#session-info").waitFor();
    await api(url, "/api/sessions", {title:"Дубликат"}, 409);
    await api(url, "/api/sessions/1/publish", {}, 409);
    await page.waitForTimeout(1100);
    await page.getByLabel("Подпись момента").fill("Победа");
    await page.getByLabel("Приватная заметка").fill("PRIVATE-ONLY");
    await page.getByRole("button", {name:"Поставить таймкод"}).click();
    await page.getByText("Победа", {exact:false}).waitFor();
    await page.reload();
    await page.getByText("Победа", {exact:false}).waitFor();
    const firstDetail = await api(url, "/api/sessions/1");
    assert.ok(firstDetail.marks[0].seconds >= 1);
    console.log("PASS clean startup, stream and persisted mark at " + firstDetail.marks[0].seconds + " s");

    await page.getByLabel("Игра", {exact:true}).fill("Игра");
    await page.getByLabel("Фразы, по одной на строку").fill("Тайный финал");
    await Promise.all([
      page.waitForResponse(response => response.url().endsWith("/api/sessions/1")),
      page.getByRole("button", {name:"Сохранить правила"}).click()
    ]);
    await send(page, "Лиса", "Привет!");
    await send(page, "Сова", "!вопрос Когда следующий эфир?");
    await send(page, "Кит", "ТАЙНЫЙ ФИНАЛ PRIVATE-SPOILER");
    await send(page, "Енот", "!вопрос Как открыть тайный финал?");
    await page.locator("#hidden-messages").getByText("Енот", {exact:false}).waitFor();
    assert.match(await page.locator("#messages").innerText(), /Лиса · Привет/);
    assert.doesNotMatch(await page.locator("#messages").innerText(), /PRIVATE-SPOILER|Енот/);
    assert.doesNotMatch(await page.locator("#questions").innerText(), /Енот/);
    await page.locator("#hidden-messages li").filter({hasText:"Енот"}).getByRole("button", {name:"Восстановить"}).click();
    await page.locator("#questions").getByText("Енот", {exact:false}).waitFor();
    await page.locator("#questions li").filter({hasText:"Сова"}).getByRole("button", {name:"Отметить отвеченным"}).click();
    await page.locator("#questions").getByText(/Сова.*Отвечен/).waitFor();
    await page.reload();
    await page.locator("#questions").getByText(/Сова.*Отвечен/).waitFor();
    const chat = await api(url, "/api/sessions/1");
    assert.equal(chat.questions.length, 2);
    assert.equal(chat.hidden.length, 1);
    assert.equal(chat.hidden[0].rule, "Тайный финал");
    console.log("PASS chat and case-insensitive rule, held question, restoration, answered after reload");

    const save = page.getByRole("button", {name:"Сохранить последние 30 секунд"});
    await save.click();
    await page.getByText("Сначала загрузите запись.", {exact:true}).waitFor();
    await api(url, "/api/sessions/1/clips", {position:45}, 400);
    await page.getByRole("button", {name:"Загрузить деморолик"}).click();
    await page.waitForFunction(() => document.getElementById("recording-video").readyState >= 2);
    await save.click();
    await page.getByText("Пустой отрезок.", {exact:false}).waitFor();
    const recording = (await api(url, "/api/sessions/1")).recordings[0].id;
    await api(url, "/api/sessions/1/clips", {recording,position:0}, 400);
    await checkClip(page, url, 45, 30);
    await checkClip(page, url, 12, 12);

    await page.getByRole("button", {name:"Завершить эфир"}).click();
    await page.getByRole("heading", {name:"Личные итоги"}).waitFor();
    const finished = await api(url, "/api/sessions/1");
    assert.ok(finished.session.ended >= finished.session.started);
    assert.equal(finished.duration, Math.floor(finished.session.ended - finished.session.started));
    assert.equal(finished.flagged_count, 2);
    assert.equal(finished.hidden.length, 1);
    assert.equal(finished.clips.length, 2);
    await api(url, "/api/sessions/1/finish", {}, 409);
    assert.equal((await api(url, "/api/sessions/1")).session.ended, finished.session.ended);
    await page.getByLabel("Момент", {exact:true}).selectOption(String(finished.marks[0].id));
    await page.getByLabel("Вопрос", {exact:true}).selectOption(String(finished.questions[0].id));
    await page.getByLabel("Результат челленджа").fill("3 из 3");
    await page.locator("#preview").getByText("3 из 3", {exact:true}).waitFor();
    assert.equal(await api(url, "/api/viewer"), null);
    await page.getByRole("button", {name:"Показать зрителям"}).click();
    await page.getByText("Карточка опубликована.").waitFor();
    await viewer.getByText("3 из 3", {exact:true}).waitFor();
    const card = {
      duration:finished.duration,
      moment:{seconds:finished.marks[0].seconds,label:"Победа"},
      question:{nick:"Сова",body:"Когда следующий эфир?"},
      challenge:"3 из 3"
    };
    assert.deepEqual(await api(url, "/api/viewer"), card);
    assert.doesNotMatch(await viewer.locator("body").innerText(), /PRIVATE|Енот|ТАЙНЫЙ/);
    await page.getByLabel("Результат челленджа").fill("DRAFT-ONLY");
    await page.getByLabel("Анонс следующего эфира").fill("DRAFT-ANNOUNCEMENT");
    await page.locator("#preview").getByText("DRAFT-ANNOUNCEMENT", {exact:true}).waitFor();
    await viewer.waitForResponse(response => response.url().endsWith("/api/viewer"));
    assert.deepEqual(await api(url, "/api/viewer"), card);
    assert.doesNotMatch(await viewer.locator("body").innerText(), /DRAFT|PRIVATE/);
    assert.deepEqual([...viewerRequests].filter(item => item.startsWith("/api/")), ["/api/viewer"]);
    console.log("PASS personal summary, 409 duplicate finish, viewer tab refresh, exact public payload, draft isolation");

    await api(url, "/api/sessions", {title:"Второй эфир"});
    const second = await api(url, "/api/sessions/2");
    assert.deepEqual([second.marks,second.clips,second.questions,second.hidden], [[],[],[],[]]);
    await api(url, "/api/sessions/2/answer", {id:finished.questions[0].id}, 404);
    await api(url, "/api/sessions/2/clips", {recording,position:12}, 400);
    if (process.env.STREAMHELPER_SCREENSHOTS) {
      await page.screenshot({path:path.join(process.env.STREAMHELPER_SCREENSHOTS,"panel.png"),fullPage:true});
      await viewer.screenshot({path:path.join(process.env.STREAMHELPER_SCREENSHOTS,"viewer.png")});
    }
    await stopServer(server);
    server = await startServer();
    assert.deepEqual(await api(server.url, "/api/sessions/1"), finished);
    assert.deepEqual(await api(server.url, "/api/viewer"), card);
    await page.goto(server.url);
    await page.getByLabel("Сессия").selectOption("1");
    await page.getByRole("heading", {name:"Личные итоги"}).waitFor();
    assert.equal(await page.getByRole("link", {name:"Смотреть"}).count(), 2);
    const clipUrl = await page.getByRole("link", {name:"Смотреть"}).first().getAttribute("href");
    const range = await fetch(server.url + clipUrl, {headers:{Range:"bytes=0-31"}});
    assert.equal(range.status, 206);
    assert.equal((await range.arrayBuffer()).byteLength, 32);
    await viewer.goto(server.url + "/viewer");
    await viewer.getByText("3 из 3", {exact:true}).waitFor();
    assert.deepEqual(errors, []);
    console.log("PASS session isolation, persistence after restart, persisted video range and viewer card");

    await stopServer(server);
    server = await startServer({STREAMHELPER_FFMPEG:probe});
    await page.goto(server.url);
    await page.getByLabel("Сессия").selectOption("1");
    await page.waitForFunction(() => document.getElementById("recording-video").readyState >= 2);
    await page.getByLabel("Позиция в записи, с").fill("12");
    await page.getByRole("button", {name:"Перейти"}).click();
    await save.click();
    await page.getByText("FFmpeg не смог обработать запись.", {exact:false}).waitFor();
    assert.equal((await api(server.url, "/api/sessions/1")).clips.length, 2);
    const files = fs.readdirSync(path.join(directory, "clips"));
    assert.equal(files.length, 2);
    console.log("PASS encoder failure displayed, no incomplete clip");
  } finally {
    if (browser) await browser.close();
    await stopServer(server);
    fs.rmSync(directory, {recursive:true, force:true});
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
