const {chromium} = require("playwright");
const {spawn} = require("node:child_process");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const root = path.join(__dirname, "..");
const directory = fs.mkdtempSync(path.join(process.env.STREAMHELPER_TEST_ROOT || os.tmpdir(), "streamhelper-"));
const python = process.env.STREAMHELPER_PYTHON || "python";

(async () => {
  const app = spawn(python, ["-m", "tests.fixture_server", directory], {
    cwd: root, stdio: ["ignore", "pipe", "ignore"]
  });
  let browser;
  try {
    const url = await new Promise((resolve, reject) => {
      app.once("error", reject);
      app.once("exit", code => reject(new Error("Server exited: " + code)));
      app.stdout.once("data", data => resolve(data.toString().trim()));
    });
    browser = await chromium.launch({channel: "msedge"});
    const context = await browser.newContext();
    context.setDefaultTimeout(10000);
    const viewer = await context.newPage();
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await viewer.goto(url + "/viewer");
    await viewer.getByText("Итоги ещё не опубликованы.").waitFor();
    await page.goto(url);
    await page.getByText(/Сова · Как дела\? · Новый/).waitFor();
    let clipRequest;
    await page.route("**/api/sessions/1/twitchclip", async route => {
      clipRequest = route.request().postDataJSON();
      await route.fulfill({status:202, json:{id:"NewClip"}});
    });
    await page.getByLabel("Длительность клипа, с").fill("17");
    await page.getByRole("button", {name:"Создать клип на Twitch"}).click();
    await page.getByText("Twitch принял запрос. Ссылка появится после обработки.").waitFor();
    assert.deepEqual(clipRequest, {duration:17});
    clipRequest = null;
    await page.getByRole("button", {name:"Назначить клавишу"}).click();
    await page.keyboard.press("k");
    await page.getByText("Клавиша: K.", {exact:false}).waitFor();
    await page.keyboard.press("k");
    await page.waitForFunction(() => document.getElementById("status").textContent.startsWith("Twitch принял"));
    assert.deepEqual(clipRequest, {duration:17});
    assert.equal(await page.locator("input[type=file], video, #seek").count(), 0);
    assert.equal(await page.getByRole("heading", {name:"Антиспойлер"}).count(), 0);
    assert.equal(await page.getByRole("heading", {name:"Тестовый чат"}).isVisible(), false);
    await page.getByRole("button", {name:"Отметить отвеченным"}).click();
    await page.getByText(/Сова · Как дела\? · Отвечен/).waitFor();
    await page.getByRole("button", {name:"Показать зрителям"}).click();
    await viewer.getByText("Категории · Just Chatting").waitFor();
    await viewer.getByText("Длительность 00:02:00").waitFor();
    await viewer.getByText("Сова · 2 сообщ.").waitFor();
    await viewer.getByText("Сова · 42 Bits").waitFor();
    assert.equal(await viewer.getByRole("link", {name:"Победа"}).getAttribute("href"), "https://clips.twitch.tv/TestClip");
    assert.doesNotMatch(await viewer.locator("body").innerText(), /Как дела/);
    const snapshot = await (await fetch(url + "/api/viewer")).json();
    assert.equal(snapshot.source, "twitch");
    assert.equal(snapshot.questions, undefined);
    console.log("PASS Twitch fixture: questions, automated summary, categories, audience, Bits and clip in viewer tab");

    await page.reload();
    await page.getByText("Клавиша: K.", {exact:false}).waitFor();
    await page.getByRole("button", {name:"Сбросить клавишу"}).click();
    await page.getByText("Клавиша не назначена.", {exact:false}).waitFor();
    for (const route of ["recording", "clips"]) {
      const removed = await fetch(url + "/api/sessions/1/" + route, {
        method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"
      });
      assert.equal(removed.status, 404);
    }
    assert.deepEqual(errors, []);
    console.log("PASS Twitch clip controls: selected duration, keyboard shortcut, reset, no local upload");
  } finally {
    if (browser) await browser.close();
    if (app.exitCode === null) await new Promise(resolve => {
      app.once("exit", resolve);
      app.kill();
    });
    fs.rmSync(directory, {recursive:true, force:true});
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
