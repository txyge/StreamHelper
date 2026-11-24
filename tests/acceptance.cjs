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
    const page = await browser.newPage();
    page.setDefaultTimeout(10000);
    await page.goto(url);
    await page.getByRole("heading",{name:"Вопросы к стримеру"}).waitFor();
    await page.getByText(/Модератор · Где база\? · Новый/).waitFor();
    await page.getByRole("button",{name:"Отметить отвеченным"}).click();
    await page.getByText(/Модератор · Где база\? · Отвечен/).waitFor();
    await page.getByLabel("Подпись момента").fill("Важный момент");
    await page.getByRole("button",{name:"Поставить таймкод"}).click();
    await page.locator("#marks").getByText(/Важный момент/).waitFor();
    await page.locator("#topics").getByText(/Minecraft.*Строим базу/).waitFor();
    await page.locator("#viewers").getByText("Модератор").waitFor();
    await page.locator("#moderators").getByText("Модератор").waitFor();
    await page.locator("#donations").getByText(/Донатер.*200 RUB/).waitFor();
    await page.getByRole("button",{name:"Завершить сессию"}).click();
    await page.locator("#session-info").getByText(/Завершение/).waitFor();
    assert.equal(await page.getByRole("heading",{name:"Итог трансляции"}).count(),1);
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
