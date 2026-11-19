// Run against a local server: NODE_PATH=<playwright modules> node tests/mobile-ui.cjs
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
  const page = await browser.newPage({viewport:{width:260,height:700}});
  const errors=[];
  page.on("pageerror", error=>errors.push(error.message));
  const job={id:"fixture",topic:"Тест",title:"Тест",status:"draft",format:"vertical",animate:"none",minutes:1,stages:{script:{state:"done"}}};
  const script={title:"Тест",scenes:[{text:"Тестовый текст",image:"image",motion:"motion",caption:""}],social:{youtube:{title:"Тест",description:"Описание",tags:["тест"]}}};
  await page.route("**/api/balance",r=>r.fulfill({json:{}}));
  await page.route("**/api/events",r=>r.fulfill({status:204}));
  await page.route("**/api/jobs/fixture/script",r=>r.fulfill({json:script}));
  await page.route("**/api/jobs/fixture/render",r=>r.fulfill({json:{status:"queued"}}));
  await page.route("**/files/fixture/social.json",r=>r.fulfill({json:{youtube:{Название:"Тест",Описание:"Описание",Теги:"тест"}}}));
  await page.route("**/api/jobs",r=>r.fulfill({json:[job]}));
  await page.goto(process.env.TEST_URL || "http://127.0.0.1:8765",{waitUntil:"networkidle"});
  await page.waitForSelector(".choice-group button");
  assert.equal(await page.locator('[data-worktab="scenes"], #scene-dock, #morebtn').count(),0);
  assert.equal(await page.locator('#log, .log-pane').count(),0);
  assert.equal(await page.locator('[data-project="animated"]').getAttribute("aria-pressed"),"true");
  assert.equal(await page.locator('#styles + .choice-group button[data-value="stained_glass"]').count(),1);
  assert.equal(await page.locator("#extra").isVisible(),true);
  await page.locator('#genres + .choice-group button[data-value="custom"]').click();
  await page.locator("#custom-genre").fill("Особый жанр");
  await page.locator('#genres + .choice-group button[data-value="auto"]').click();
  await page.locator('#genres + .choice-group button[data-value="custom"]').click();
  assert.equal(await page.locator("#custom-genre").inputValue(),"Особый жанр");
  await page.locator('#styles + .choice-group button[data-value="custom"]').click();
  await page.locator('#genders + .choice-group button[data-value="female"]').focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.locator("#genders").inputValue(),"female");
  assert.equal(await page.locator('#genders + .choice-group button[data-value="female"]').getAttribute("aria-pressed"),"true");
  await page.reload({waitUntil:"networkidle"});
  await page.waitForSelector(".choice-group button");
  assert.equal(await page.locator("#genders").inputValue(),"female");
  assert.equal(await page.locator("#custom-genre").inputValue(),"Особый жанр");
  await page.locator('[data-caption="cycle"]').click();
  await page.locator(".subtitle-details summary").click();
  for (const id of ["langs","tones","narrators","endings","audiences","vmodels","providers","genders","subtitle-preset","subtitle-outline-mode","subtitle-timing"]) {
    const button=page.locator(`#${id} + .choice-group button:not(:disabled)`).last();
    const value=await button.getAttribute("data-value"); await button.click();
    assert.equal(await page.locator(`#${id}`).inputValue(),value, id);
    assert.equal(await button.getAttribute("aria-pressed"),"true", id);
  }
  const fail=async (width,state)=>{const details=await page.evaluate(()=>({width:document.documentElement.scrollWidth,view:innerWidth}));if(details.width>width) errors.push(`${width} ${state}: ${details.width}`);};
  for(let width=260;width<=420;width+=5) {
    await page.setViewportSize({width,height:700});
    await page.locator('[data-worktab="create"]').click();
    await fail(width,"создание");
    for(const mode of ["none","animated"]) {
      const card=page.locator(`[data-project="${mode}"]`);
      await card.click(); await page.waitForTimeout(350);
      const positioned=await card.evaluate(element=>{const a=element.getBoundingClientRect(),b=element.parentElement.getBoundingClientRect();return a.left>=b.left-1 && a.right<=b.right+1;});
      if(!positioned) errors.push(`${width} карточка ${mode} обрезана`);
    }
    const panel=await page.locator("#checkout").boundingBox(), go=await page.locator("#go").boundingBox();
    if (!panel || !go || go.x<0 || go.x+go.width>width || go.y<panel.y || go.y+go.height>700) errors.push(`${width} нижняя панель`);
    await page.evaluate(()=>{document.querySelector("#err").textContent="Ошибка проверки"; document.querySelector("#err").scrollIntoView({block:"center",behavior:"instant"});});
    const alert=await page.locator("#err").boundingBox();
    if(!alert || alert.y+alert.height>panel.y) errors.push(`${width} ошибка закрыта панелью`);
    for(const nav of ["history","music"]) {await page.locator(`[data-worktab="${nav}"]`).click(); await fail(width,nav);if(await page.locator("#checkout").isVisible())errors.push(`${width} панель в ${nav}`);}
    await page.evaluate(()=>showProgress("fixture")); await fail(width,"прогресс");
    await page.locator("#progress-review").click(); await fail(width,"редактор");
    if(await page.locator("#checkout").isVisible()) errors.push(`${width} панель в редакторе`);
    await page.locator("#script-close").click();
    await page.evaluate(()=>{jobs[0].status="done"; jobs[0].files=[]; openJob("fixture");});
    await page.locator("#dlg").waitFor({state:"visible"}); await fail(width,"результат");
    await page.locator("#close-dialog").click();
    await page.evaluate(()=>{jobs[0].status="draft";});
  }
  await page.locator("#progress-review").click(); await page.locator("#script-render").click();
  await page.locator("#script-dialog").waitFor({state:"hidden",timeout:5000});
  await page.setViewportSize({width:1280,height:800}); await page.locator('[data-worktab="create"]').click(); await fail(1280,"компьютер");
  if(errors.length) throw Error(errors.join("\n"));
  console.log("33 widths, settings, navigation, progress and draft: OK");
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
