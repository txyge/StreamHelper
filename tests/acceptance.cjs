const {chromium} = require("playwright");
const {spawn} = require("node:child_process");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

(async () => {
  const directory = fs.mkdtempSync(path.join(process.env.STREAMHELPER_TEST_ROOT || os.tmpdir(), "streamhelper-"));
  const app = spawn(process.env.STREAMHELPER_PYTHON || "python",
    ["-m", "tests.fixture_server", directory], {cwd:path.join(__dirname, ".."), stdio:["ignore","pipe","inherit"]});
  let browser;
  try {
    const url = await new Promise((resolve,reject) => {
      app.once("error",reject);
      app.once("exit",code => reject(new Error("Fixture exited: " + code)));
      app.stdout.once("data",data => resolve(data.toString().trim()));
    });
    browser = await chromium.launch({channel:"msedge"});
    const page = await browser.newPage({acceptDownloads:true});
    page.setDefaultTimeout(10000);
    await page.goto(url);
    await page.getByRole("heading",{name:"Вопросы к стримеру"}).waitFor();
    await page.locator("#questions").getByText("Где база?", {exact:true}).waitFor();
    await page.locator("#questions").getByText("Новый", {exact:true}).waitFor();
    await page.getByRole("button",{name:"Отметить отвеченным"}).click();
    await page.locator("#questions").getByText("Отвечен", {exact:true}).waitFor();
    await page.getByLabel("Подпись момента").fill("Важный момент");
    await page.getByRole("button",{name:"Поставить таймкод"}).click();
    await page.locator("#marks").getByText(/Важный момент/).waitFor();
    await page.locator("#topics").getByText(/Minecraft.*Строим базу/).waitFor();
    await page.locator("#viewers").getByText("Модератор").waitFor();
    await page.locator("#moderators").getByText("Модератор").waitFor();
    await page.locator("#donations").getByText(/Донатер.*200 RUB/).waitFor();
    await page.getByLabel("Тема").selectOption("dark");
    const questionsWindow = page.context().waitForEvent("page");
    await page.getByRole("link",{name:"Открыть вопросы в отдельном окне"}).click();
    const questions = await questionsWindow;
    await questions.locator("#questions").getByText("Где база?", {exact:true}).waitFor();
    assert.equal(new URL(questions.url()).searchParams.get("session"), "1");
    assert.equal(await questions.locator("#summary").isVisible(), false);
    assert.equal(await questions.locator("html").getAttribute("data-theme"), "dark");
    await page.getByLabel("Тема").selectOption("light");
    await questions.waitForFunction(() => document.documentElement.dataset.theme === "light");
    await questions.close();
    const marksWindow = page.context().waitForEvent("page");
    await page.getByRole("link",{name:"Открыть таймкоды в отдельном окне"}).click();
    const marks = await marksWindow;
    await marks.locator("#marks").getByText(/Важный момент/).waitFor();
    assert.equal(await marks.locator("#chat").isVisible(), false);
    await marks.getByLabel("Подпись момента").fill("Из отдельного окна");
    await marks.getByRole("button",{name:"Поставить таймкод"}).click();
    await page.locator("#marks").getByText(/Из отдельного окна/).waitFor();
    await marks.close();
    await page.getByLabel("Тема").selectOption("system");
    await page.emulateMedia({colorScheme:"dark"});
    assert.equal(await page.locator("html").getAttribute("data-theme"), "system");
    assert.equal(await page.locator("html").evaluate(el => getComputedStyle(el).backgroundColor), "rgb(16, 25, 22)");
    await page.getByRole("button",{name:"Завершить сессию"}).click();
    await page.locator("#session-info").getByText(/Завершение/).waitFor();
    assert.equal(await page.getByRole("heading",{name:"Итог трансляции"}).count(),1);
    const endpoint = await page.getByLabel("Локальный URL для интеграции").inputValue();
    const report = await (await fetch(endpoint)).json();
    assert.equal(report.title, "Строим базу");
    assert.equal(report.topics.at(-1).category, "Minecraft");
    assert.deepEqual(report.viewers, ["Модератор"]);
    assert.deepEqual(report.moderators, ["Модератор"]);
    assert.equal(report.donations[0].name, "Донатер");
    assert.ok(report.ended_at > report.started_at);
    for (const [label, filename] of [["Скачать JSON","stream-1.json"],
        ["Скачать текст для титров","stream-1-credits.txt"]]) {
      const pending = page.waitForEvent("download");
      await page.getByRole("link",{name:label}).click();
      const download = await pending;
      assert.equal(download.suggestedFilename(),filename);
      const content = fs.readFileSync(await download.path(),"utf8");
      if (filename.endsWith(".json")) assert.deepEqual(JSON.parse(content), report);
      else assert.match(content, /Донатер · 200 RUB/);
    }
    await page.getByText("Настройки DonationAlerts", {exact:true}).click();
    await page.getByLabel("Client ID", {exact:true}).fill("123");
    await page.getByLabel("Client Secret", {exact:true}).fill("private-fixture");
    await page.getByRole("button",{name:"Сохранить настройки"}).click();
    await page.getByRole("button",{name:"Подключить DonationAlerts"}).waitFor();
    assert.equal(await page.getByLabel("Client Secret", {exact:true}).inputValue(), "");
    const connection = await (await fetch(url + "/api/connections")).text();
    assert.doesNotMatch(connection, /private-fixture/);
    await page.getByRole("link",{name:"Инструкция подключения"}).click();
    await page.getByRole("heading",{name:"Streamer.bot",exact:true}).waitFor();
    await page.getByRole("heading",{name:"DonationAlerts",exact:true}).waitFor();
    assert.equal(await page.getByRole("button",{name:/клип|показать зрителям/i}).count(),0);
    for (const [route, method] of [["/viewer","GET"],["/api/viewer","GET"],
        ["/api/sessions/1/publish","POST"],["/api/sessions/1/twitchclip","POST"]]) {
      assert.equal((await fetch(url+route,{method})).status,404);
    }
    console.log("PASS Edge: marks, question queue, single session report, removed routes");
  } finally {
    if (browser) await browser.close();
    if (app.exitCode === null && app.pid) await new Promise(resolve => {
      app.once("exit",resolve);
      app.kill();
    });
    fs.rmSync(directory,{recursive:true,force:true});
  }
})().catch(error => {console.error(error);process.exitCode=1;});
