"use strict";

/*
 * Окно «Комплект под ключ»: прогресс, видео, обложка и тексты для публикации в одном месте.
 * Открывается сразу после запуска и при клике по ролику; данные берутся из общего списка jobs,
 * поэтому процент и этап одинаковы в карточке и в окне. kitRequest отсекает ответы чужого ролика.
 */
const kit = $("#kit");
let kitId = null, kitScript = null, kitScriptFor = null, kitLoading = false, kitNetwork = "youtube", kitRequest = 0;
const KIT_STAGES = {script:"Сценарий",voice:"Озвучка",images:"Кадры",animation:"Анимация",render:"Монтаж",cover:"Обложка",texts:"Тексты"};
const KIT_STATES = {waiting:"Ожидание",running:"Идёт",done:"Готово",skipped:"Не выбрано",error:"Ошибка"};
const NETWORKS = {youtube:"YouTube",tiktok:"TikTok",instagram:"Instagram",facebook:"Facebook"};
const ICON_COPY = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>';
const ICON_OK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l5 5L20 7"/></svg>';

const hashtags = list => (Array.isArray(list) ? list : String(list || "").split(/[\s,]+/))
  .map(x => String(x).trim().replace(/^#/, "").replace(/\s+/g, "")).filter(Boolean).map(x => "#" + x).join(" ");

// Поля публикации из сценария: доступны сразу после этапа «Сценарий», до конца сборки.
function packageFields(data, network) {
  const s = data.social || {}, title = data.title || "";
  const yt = s.youtube || {}, ig = s.instagram || {}, tt = s.tiktok || {}, fb = s.facebook || {};
  const tags = (yt.tags || []).map(t => String(t).replace(/^#/, "").trim()).filter(Boolean);
  return {
    youtube: [["Заголовок", yt.title || title], ["Описание", yt.description], ["Теги", tags.join(", ")], ["Хештеги", hashtags(tags.slice(0, 3))]],
    tiktok: [["Заголовок", title], ["Описание", tt.caption], ["Хештеги", hashtags(tt.hashtags)]],
    instagram: [["Заголовок", title], ["Описание", ig.caption], ["Хештеги", hashtags(ig.hashtags)]],
    facebook: [["Заголовок", fb.title || title], ["Описание", fb.text], ["Хештеги", hashtags(fb.hashtags)]],
  }[network].filter(([, value]) => value);
}

function flowMarkup(active, done) {
  return ["Сценарий", "Сборка и метаданные", "Готово"].map((label, i) =>
    `<li class="${i < done ? "done" : i === active ? "active" : ""}"><span>${i < done ? "✓" : i + 1}</span>${label}</li>`).join("");
}

function setMarkup(node, markup) {
  if (node.dataset.markup === markup) return false;
  node.innerHTML = markup; node.dataset.markup = markup;
  return true;
}

function openKit(id) {
  if (kitId !== id) { kitScript = null; kitScriptFor = null; kitNetwork = "youtube"; kitRequest++; }
  kitId = id;
  $("#kit-status").textContent = "";
  for (const node of kit.querySelectorAll("[data-markup]")) delete node.dataset.markup;
  if (!kit.open) kit.showModal();
  refreshKit();
}

async function loadKitScript(job) {
  if (kitLoading || kitScriptFor === job.id) return;
  kitLoading = true; const request = kitRequest;
  try {
    const response = await fetch(`/api/jobs/${job.id}/script`);
    if (!response.ok) return;
    const data = await response.json();
    if (request !== kitRequest) return;
    kitScript = data; kitScriptFor = job.id;
    refreshKit();
  } catch { /* Следующее событие воркера повторит запрос. */ }
  finally { kitLoading = false; }
}

function refreshKit() {
  if (!kit.open || !kitId) return;
  const job = jobs.find(j => j.id === kitId);
  if (!job) return;
  if (job.deleted_at) return kit.close();  // остановлен без списаний и убран автоматически
  const f = `/files/${job.id}/`, stages = job.stages || {}, status = job.status;
  const active = ACTIVE.includes(status), done = status === "done", stopped = ["error", "cancelled"].includes(status);
  const scriptReady = stages.script?.state === "done" || ["draft", "done"].includes(status);
  const has = name => (job.files || []).includes(name);
  const coverReady = done ? has("cover.jpg") : stages.cover?.state === "done";
  const percent = job.percent ?? 0;
  if (scriptReady && kitScriptFor !== job.id) loadKitScript(job);

  $("#kit-title").textContent = job.title || job.topic;
  const cost = job.cost?.total > 0 ? `${job.accounting === "pending" ? "≥ " : ""}${money(job.cost.total)}` : `≈ ${money(job.estimate?.total)}`;
  $("#kit-meta").textContent = `${job.format === "horizontal" ? "16:9" : "9:16"} · ${job.minutes} мин · ${cost}`;
  setMarkup($("#kit-flow"), done ? flowMarkup(-1, 3) : status === "draft" ? flowMarkup(0, 0) : flowMarkup(scriptReady ? 1 : 0, scriptReady ? 1 : 0));

  // Видео: прогресс до монтажа, затем плеер.
  const backdrop = coverReady ? ` style="background-image:linear-gradient(rgba(11,14,30,.72),rgba(11,14,30,.9)),url('${f}cover.jpg')"` : "";
  const screen = done
    ? `<video controls playsinline preload="metadata" ${has("cover.jpg") ? `poster="${f}cover.jpg"` : ""} src="${f}video.mp4"></video>`
    : status === "draft"
      ? `<div class="kit-progress"><b class="kit-state">Сценарий готов</b><span>Проверьте текст и запустите сборку видео</span><button type="button" class="btn main" data-kit="script">Проверить сценарий →</button></div>`
      : stopped
        ? `<div class="kit-progress"><b class="kit-state ${status}">${status === "error" ? "Ошибка" : "Остановлено"}</b><span>${esc(job.progress || "Создание прервано")}</span><small>Повтор использует оставшийся бюджет и готовые материалы.</small><button type="button" class="btn main" data-kit="retry">Повторить</button></div>`
        : `<div class="kit-progress"${backdrop}><b class="kit-percent">${percent}%</b><span>${esc(job.stage || "В очереди")}</span><span class="prog big"><i style="width:${percent}%"></i></span><small>Окно можно закрыть — сборка продолжится, прогресс сохранится в «Мои ролики».</small></div>`;
  const screenNode = $("#kit-screen");
  if (done) { if (!screenNode.querySelector("video")) setMarkup(screenNode, screen); }
  else setMarkup(screenNode, screen);
  screenNode.classList.toggle("h", job.format === "horizontal");

  setMarkup($("#kit-stages"), Object.entries(KIT_STAGES).map(([key, label]) => {
    let stage = stages[key] || {state: done ? "done" : "waiting"};
    if (key === "animation" && job.animate === "none") stage = {state: "skipped"};
    const count = stage.total && key !== "render" ? ` ${stage.completed}/${stage.total}` : "";
    return `<span class="kit-stage ${esc(stage.state)}"><i></i>${label}<small>${KIT_STATES[stage.state] || "Ожидание"}${count}</small></span>`;
  }).join(""));

  setMarkup($("#kit-video-actions"), done
    ? `<a class="btn main" href="${f}video.mp4?download=1" download><svg class="ic" aria-hidden="true"><use href="#i-download"/></svg>Скачать видео</a><a class="btn" href="${f}result.zip?download=1" download>Скачать архив</a>${has("subtitles.srt") ? `<a class="btn" href="${f}subtitles.srt" download>SRT</a>` : ""}${has("subtitles.ass") ? `<a class="btn" href="${f}subtitles.ass" download>ASS</a>` : ""}`
    : active && status !== "cancelling" ? `<button type="button" class="btn ghost danger" data-kit="cancel">Остановить</button>` : "");

  // Обложка.
  const pill = (state, text) => `<span class="pill ${state}">${text}</span>`;
  const waiting = active || status === "draft";
  setMarkup($("#kit-cover"), coverReady
      ? `<div class="kit-card-head"><h3>Обложка</h3>${pill("ok", "Готово")}</div><div class="kit-cover"><img class="reveal" src="${f}cover.jpg" alt="Обложка ролика"><div class="kit-cover-actions"><a class="btn" href="${f}cover.jpg?download=1" download>Скачать JPG</a><button type="button" class="btn" data-kit="copy-cover">Скопировать</button><div class="cover-sizes"><a href="${f}cover-vertical.jpg?download=1" download>9:16</a><a href="${f}cover-youtube.jpg?download=1" download>YouTube</a><a href="${f}cover-square.jpg?download=1" download>Квадрат</a></div></div></div>`
      : `<div class="kit-card-head"><h3>Обложка</h3>${pill(waiting ? "wait" : "off", stages.cover?.state === "running" ? "Генерируется" : waiting ? "Ожидает" : "Не готово")}</div><div class="kit-cover"><span class="skeleton cover-skeleton"></span><div class="kit-cover-actions"><span class="skeleton line"></span><span class="skeleton line short"></span></div></div>`);

  // Заголовок, описание, теги и хештеги.
  const metaNode = $("#kit-meta-card");
  if (!kitScript || kitScriptFor !== job.id) setMarkup(metaNode, `<div class="kit-card-head"><h3>Тексты для публикации</h3>${pill(waiting ? "wait" : "off", scriptReady ? "Загружаются" : waiting ? "Пишутся со сценарием" : "Не готово")}</div>${["", "", " short", "", " short"].map(x => `<span class="skeleton line${x}"></span>`).join("")}`);
  else {
    const fields = packageFields(kitScript, kitNetwork);
    const fresh = setMarkup(metaNode, `<div class="kit-card-head"><h3>Тексты для публикации</h3>${pill("ok", "Готово")}<button type="button" class="btn" data-kit="copy-all">Скопировать всё</button></div>
      <div class="tabs" role="tablist">${Object.entries(NETWORKS).map(([key, label]) => `<button type="button" role="tab" aria-selected="${key === kitNetwork}" class="${key === kitNetwork ? "on" : ""}" data-network="${key}">${label}</button>`).join("")}</div>
      <div class="fields">${fields.map(([label, value], i) => `<div class="field"><div class="fh"><span>${esc(label)}</span><button type="button" class="copy" data-copy="${i}" title="Копировать" aria-label="Копировать: ${esc(label)}">${ICON_COPY}</button></div><div class="fv">${esc(value)}</div></div>`).join("")}</div>`);
    if (fresh) revealFields(job.id);
  }

  const editable = !active;
  $("#kit-edit").hidden = !editable || !scriptReady; $("#kit-trash").hidden = !editable;
}

// Плавное «печатание» текстов один раз на ролик.
function revealFields(id) {
  const key = "kit.revealed." + id;
  try { if (sessionStorage.getItem(key) || matchMedia("(prefers-reduced-motion: reduce)").matches) return; sessionStorage.setItem(key, "1"); } catch { return; }
  const nodes = [...$("#kit-meta-card").querySelectorAll(".fv")], values = nodes.map(n => n.textContent);
  nodes.forEach(n => n.textContent = "");
  let index = 0, offset = 0;
  const step = () => {
    if (index >= nodes.length || !nodes[index].isConnected) { nodes.forEach((n, i) => { if (n.isConnected) n.textContent = values[i]; }); return; }
    offset += 6; nodes[index].textContent = values[index].slice(0, offset);
    if (offset >= values[index].length) { index++; offset = 0; }
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function flash(button, ok) {
  if (!ok) { $("#kit-status").textContent = "Не удалось скопировать — выделите текст вручную"; return; }
  button.innerHTML = ICON_OK; button.classList.add("ok");
  setTimeout(() => { button.innerHTML = ICON_COPY; button.classList.remove("ok"); }, 1200);
}

async function copyCover() {
  try {
    const image = $("#kit-cover img"), canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth; canvas.height = image.naturalHeight; canvas.getContext("2d").drawImage(image, 0, 0);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
    await navigator.clipboard.write([new ClipboardItem({"image/png": blob})]);
    $("#kit-status").textContent = "Обложка скопирована";
  } catch { $("#kit-status").textContent = "На этом устройстве картинку нельзя скопировать — скачайте JPG"; }
}

kit.addEventListener("click", async e => {
  if (e.target === kit) return kit.close();
  const network = e.target.closest("[data-network]");
  if (network) { kitNetwork = network.dataset.network; return refreshKit(); }
  const copy = e.target.closest("[data-copy]");
  if (copy) return flash(copy, await copyText(packageFields(kitScript, kitNetwork)[copy.dataset.copy][1]));
  const action = e.target.closest("[data-kit]")?.dataset.kit;
  if (!action) return;
  const job = jobs.find(j => j.id === kitId);
  if (action === "copy-all") {
    const text = Object.keys(NETWORKS).map(key => NETWORKS[key].toUpperCase() + "\n" + packageFields(kitScript, key).map(([k, v]) => `${k}:\n${v}`).join("\n\n")).join("\n\n");
    $("#kit-status").textContent = await copyText(text) ? "Тексты для всех соцсетей скопированы" : "Не удалось скопировать";
  } else if (action === "copy-cover") copyCover();
  else if (action === "script") openScript(job);
  else {
    const button = e.target.closest("button"); button.disabled = true;
    try { await postJob(kitId, action); await load(); }
    catch (error) { $("#kit-status").textContent = error.message; }
    finally { button.disabled = false; }
  }
});
kit.addEventListener("close", () => {
  kit.querySelector("video")?.pause();
  for (const node of kit.querySelectorAll("[data-markup]")) { node.innerHTML = ""; delete node.dataset.markup; }
  kitId = null;
});
$("#kit-close").onclick = () => kit.close();
$("#kit-edit").onclick = () => openScript(jobs.find(j => j.id === kitId));
$("#kit-trash").onclick = async () => {
  try { if (await deleteJob(kitId)) kit.close(); }
  catch (error) { $("#kit-status").textContent = error.message; }
};
