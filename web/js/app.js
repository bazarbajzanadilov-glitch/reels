"use strict";

/*
 * Vanilla-контроллер студии.
 * Состояние живёт в DOM и модульных переменных (OPT, jobs, refData).
 * При переносе на React это разбивается на: OptionsProvider, useEstimate,
 * useCreateJob, useHistory и KitDialog. Вспомогательные функции ниже
 * (esc, money, copyText) переиспользуются как утилиты.
 */
const $ = s => document.querySelector(s);
const val = n => (document.querySelector(`input[name=${n}]:checked`) || document.querySelector(`select[name=${n}]`))?.value;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const money = x => "$" + Number(x || 0).toFixed(2);
const ACTIVE = ["queued", "running", "cancelling"];

let OPT = null;
const mins = () => +$("#minutes").value;
// Флаги — SVG из спрайта (#flag-ru …): эмодзи-флаги Windows показывает буквами.
const LANG_NAMES = {ru: "Русский", kk: "Қазақша", en: "English", de: "Deutsch"};
const langName = code => LANG_NAMES[code] || code;

const copyText = async text => {
  try { await navigator.clipboard.writeText(text); return true; }
  catch { const t=document.createElement("textarea"); t.value=text; t.style.cssText="position:fixed;opacity:0"; document.body.append(t); t.select(); const ok=document.execCommand("copy"); t.remove(); return ok; }
};

function setMins(m) {
  m = Math.min(15, Math.max(1, Math.round(+m || 1)));
  $("#minutes").value = m;
  $("#minutes-range").value = m;
  refreshSliders();
  if (OPT) estimate();
}
// выпадающий список: [значение, подпись]
const opts = (id, entries, checked) => { const el = $(id);
  el.innerHTML = entries.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
  el.value = checked; };
const labelOf = x => typeof x === "string" ? x : x?.label || "";

// Голоса — сетка карточек; скрытый <select id=voice> хранит выбор для формы и настроек.
const voiceTitle = v => v[0].toUpperCase() + v.slice(1);
function voices() {
  const p = OPT.voices[val("provider")], list = p[val("gender")];
  const current = $("#voice").value;
  $("#voice").innerHTML = list.map(v => `<option value="${esc(v)}">${esc(voiceTitle(v))}</option>`).join("");
  $("#voice").value = list.includes(current) ? current : list.includes(p.default) ? p.default : list[0];
  const gender = val("gender") === "female" ? "женский" : "мужской";
  $("#voice-grid").innerHTML = list.map(v => `<button type="button" class="voice-card" data-voice="${esc(v)}" aria-pressed="${v === $("#voice").value}">
    <span class="voice-play"><svg aria-hidden="true"><use href="#i-play"/></svg><span class="eq" aria-hidden="true"><i></i><i></i><i></i><i></i></span></span>
    <span><b>${esc(voiceTitle(v))}</b><small>${gender}</small></span></button>`).join("");
}
// Клик по карточке = выбор + проба; повторный клик по выбранной — остановить или прослушать снова.
$("#voice-grid").onclick = e => {
  const card = e.target.closest("[data-voice]");
  if (!card) return;
  if ($("#voice").value === card.dataset.voice) return playVoice(card.dataset.voice, card);
  $("#voice").value = card.dataset.voice;
  $("#voice-grid").querySelectorAll("[data-voice]").forEach(b => b.setAttribute("aria-pressed", String(b === card)));
  $("#voice").dispatchEvent(new Event("change", {bubbles: true}));
  summary();
  playVoice(card.dataset.voice, card, true);
};

async function init() {
  OPT = await fetch("/api/options").then(r => r.json());
  if (OPT.word_timing) { $("#subtitle-word-option").disabled = false; $("#subtitle-word-option").textContent = "По словам"; }
  opts("#langs", Object.keys(OPT.langs).map(k => [k, langName(k)]), "ru");
  opts("#genres", Object.entries(OPT.genres).map(([k, l]) => [k, labelOf(l)]), "auto");
  opts("#tones", Object.entries(OPT.tones).map(([k, l]) => [k, labelOf(l)]), "auto");
  opts("#styles", Object.entries(OPT.styles).map(([k, l]) => [k, labelOf(l).replace(" мультфильм", "")]), "2d");
  opts("#vmodels", Object.entries(OPT.video_models).map(([k, v]) => [k, `${v.label}|${money(v.price)} за сцену`]), "pvideo");
  opts("#narrators", Object.entries(OPT.narrators).map(([k, l]) => [k, labelOf(l)]), "auto");
  opts("#endings", Object.entries(OPT.endings).map(([k, l]) => [k, labelOf(l)]), "auto");
  opts("#audiences", Object.entries(OPT.audiences).map(([k, l]) => [k, labelOf(l)]), "all");
  opts("#providers", Object.entries(OPT.voices).map(([k, v]) => [k, v.label]), "gemini");
  opts("#genders", [["male", "Мужской"], ["female", "Женский"]], "male");
  let priceTimer;
  const later = (ms = 250) => { clearTimeout(priceTimer); priceTimer = setTimeout(estimate, ms); };
  $("#maxprice").oninput = () => later(300);
  $("#clips").oninput = () => { clipsTouched = true; later(); };
  for (const name of ["minutes", "clips", "maxprice"]) {
    const number = $("#"+name), range = $("#"+name+"-range");
    range.oninput = () => { number.value=range.value; number.dispatchEvent(new Event("input", {bubbles:true})); };
    number.addEventListener("input", () => { range.value=number.value; });
  }
  $("#clips-reset").onclick = () => { clipsTouched = false; estimate(); };
  $("#minutes").oninput = () => { clearTimeout(priceTimer); priceTimer = setTimeout(() => setMins($("#minutes").value), 250); };
  voices();
  document.querySelectorAll(".panel input[type=radio], .panel select[name]").forEach(i => i.addEventListener("change", () => {
    if (["provider", "gender", "lang"].includes(i.name)) stopAudio();
    if (i.name === "provider" || i.name === "gender") voices();
    estimate(); }));
  setupSliders();
  setupSwatches();
  restorePreferences();
  voices();
  setupChoiceButtons();
  setMins(mins());
  setupStudio();
  setupCustomChoices();
  updateSubtitleControls();
  $("#go").disabled = false;
  await estimate();
}

let estimateController;
function summary() {
  const label = (name, items) => { const v = val(name); const x = items?.[v]; return typeof x === "string" ? x : x?.label || v; };
  const rows = [
    ["Формат", `${val("format") === "vertical" ? "9:16" : "16:9"} · ${mins()} мин`],
    ["Язык", langName(val("lang"))],
    ["Сюжет", `${label("genre", OPT.genres)} · ${label("tone", OPT.tones).toLowerCase()}`],
    ["Стиль", label("style", OPT.styles)],
    ["Голос", `${$("#voice").value || ""} · ${OPT.voices[val("provider")].label}`],
  ];
  $("#summary-list").innerHTML = rows.map(([k, text]) => `<li><span>${k}</span><b>${esc(text)}</b></li>`).join("");
}
// Оценка стоимости: отменяем предыдущий запрос, чтобы последний ввод побеждал.
async function estimate() {
  if (!OPT) return;
  summary();
  const ex = refData && val("exact") === "1" ? 1 : 0;
  estimateController?.abort();
  const controller = estimateController = new AbortController();
  const query = new URLSearchParams({minutes:mins(), animate:val("animate"), exact:ex,
    voice:val("provider"), style:val("style"), video:val("vmodel"), max:$("#maxprice").value || 0});
  if (clipsTouched) query.set("clips", $("#clips").value);
  try {
    const response = await fetch(`/api/estimate?${query}`, {signal:controller.signal});
    if (!response.ok) throw new Error("estimate");
    const r = await response.json();
    if (controller.signal.aborted) return;
    $("#est").textContent = "≈ " + money(r.total);
    countTo($("#price-big"), r.total);
    $("#scene-summary").innerHTML = `<span><b>${r.scenes}</b>сцен</span><span><b>${r.clips || 0}</b>с анимацией</span>`;
    const parts = r.parts || {}, detail = {"картинки": `${r.scenes} кадров`, "анимация": `${r.clips || 0} сцен`, "голос": $("#voice").value};
    $("#plan").innerHTML = Object.entries(parts).map(([k, v]) =>
      `<li><span>${esc(k[0].toUpperCase() + k.slice(1))}${detail[k] ? `<small>${esc(detail[k])}</small>` : ""}</span><b>${money(v)}</b></li>`).join("");
    showClips(r);
    $("#note").textContent = "Списывается по факту";
  } catch (error) {
    if (error.name !== "AbortError") {
      $("#est").textContent = "";
      $("#note").textContent = "Не удалось рассчитать цену";
    }
  }
}

// Цена плавно пересчитывается к новому значению.
function countTo(node, target) {
  const from = Number(node.dataset.value || target), start = performance.now(), slow = matchMedia("(prefers-reduced-motion: reduce)").matches;
  node.dataset.value = target;
  const step = now => {
    const k = slow ? 1 : Math.min(1, (now - start) / 320);
    node.textContent = "≈ " + money(from + (target - from) * (1 - (1 - k) ** 3));
    if (k < 1 && node.dataset.value == target) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// сколько сцен оживить: по умолчанию 4 на минуту в пределах стандартного лимита, ползунком — любое число
let clipsTouched = false;
function showClips(r) {
  if (val("animate") === "none") return;  // без анимации число сцен не трогаем
  const field = $("#clips"), want = clipsTouched ? r.wanted : r.clips;
  field.max = Math.max(1, r.scenes);
  field.value = Math.max(1, want);
  $("#clips-range").max = field.max; $("#clips-range").value = field.value;
  $("#clips-value").textContent = r.scenes;
  refreshSliders();
  $("#clips-reset").hidden = !clipsTouched;
  if (r.capped) {
    const need = Math.min(LIMIT_MAX, Math.ceil((r.minimum + r.wanted * r.clip_price) * 1.15 * 4) / 4);
    $("#clips-note").innerHTML = need > r.budget
      ? `В лимит $${r.budget.toFixed(2)} помещается ${r.clips} из ${r.wanted}. <button type="button" class="link" id="raise">Поднять лимит до $${need.toFixed(2)}</button>`
      : `В лимит $${r.budget.toFixed(2)} помещается ${r.clips} из ${r.wanted} — это максимум на один ролик.`;
    if ($("#raise")) $("#raise").onclick = () => setLimit(need);
  } else {
    $("#clips-note").textContent = clipsTouched ? `Все ${r.wanted} сцен помещаются в лимит $${r.budget.toFixed(2)}.` : "По умолчанию 4 анимированные сцены на минуту.";
  }
}
// Лимит расходов — ползунок до $10 на ролик, при каждом открытии $3; скрытое #maxprice хранит значение для формы.
const LIMIT_MAX = 10;
function setLimit(value) {
  const input = $("#maxprice");
  input.value = Math.min(LIMIT_MAX, Math.max(0.25, Math.round(+value * 4) / 4)).toFixed(2);
  $("#maxprice-range").value = input.value;
  input.dispatchEvent(new Event("change", {bubbles: true}));
  refreshSliders();
  estimate();
}

let audio = null, audioButton = null;
function stopAudio() {
  if (audio) { audio.pause(); audio.removeAttribute("src"); audio.load(); }
  audio = null;
  if (audioButton) audioButton.classList.remove("busy", "playing");
  audioButton = null;
}
async function playVoice(name, button, restart = false) {
  const same = audioButton === button;
  stopAudio();
  if (same && !restart) return;
  audioButton = button;
  button.classList.add("busy", "playing");
  const sample = audio = new Audio(`/voices/${val("provider")}/${name}_${val("lang")}.mp3`);
  sample.oncanplay = () => { if (audio === sample) button.classList.remove("busy"); };
  sample.onended = sample.onerror = () => { if (audio === sample) stopAudio(); };
  try { await sample.play(); } catch { if (audio === sample) stopAudio(); }
}

async function balance() {
  const r = await fetch("/api/balance").then(r => r.json()).catch(() => ({}));
  const el = $("#bal");
  if (r.balance == null) { el.innerHTML = `<span>Баланс</span><b>—</b>`; return; }
  el.innerHTML = `<span>Баланс</span><b>${money(r.balance)}</b>`;
  el.classList.toggle("low", r.balance < 1);
}

let refData = null, sceneRefData = null;
// Референс сжимается до 1024 px и JPEG 0.88: меньше payload, достаточно для сходства.
function readImage(input, done) {
  const file = input.files[0]; if (!file) return;
  const img = new Image(), url = URL.createObjectURL(file);
  img.onload = () => {
    URL.revokeObjectURL(url);
    const k = Math.min(1, 1024 / Math.max(img.width, img.height)), c = document.createElement("canvas");
    c.width = img.width * k; c.height = img.height * k; c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    done(c.toDataURL("image/jpeg", 0.88));
  };
  img.onerror = () => { URL.revokeObjectURL(url); input.value = ""; $("#err").textContent = "Не удалось открыть изображение. Выберите JPG, PNG или WebP."; };
  img.src = url;
}
function showReference(labelId, removeId, data, text) {
  const drop = $(labelId).closest(".drop");
  drop.classList.toggle("has", !!data);
  drop.style.backgroundImage = data ? `linear-gradient(rgba(14,15,18,.55),rgba(14,15,18,.8)),url(${data})` : "";
  $(labelId).textContent = text;
  $(removeId).hidden = !data;
}
$("#reffile").onchange = e => readImage(e.target, data => {
  refData = data; showReference("#ref", "#refrm", data, "Персонаж добавлен");
  $("#exactrow").hidden = false; estimate();
});
$("#refrm").onclick = e => { e.preventDefault(); e.stopPropagation(); refData = null; $("#reffile").value = "";
  showReference("#ref", "#refrm", null, "Персонаж");
  $("#exactrow").hidden = true; $("#e0").checked = true; estimate(); };
$("#scene-file").onchange = e => readImage(e.target, data => { sceneRefData = data; showReference("#scene-ref", "#scene-rm", data, "Место добавлено"); });
$("#scene-rm").onclick = () => { sceneRefData = null; $("#scene-file").value = ""; showReference("#scene-ref", "#scene-rm", null, "Место"); };

/*
 * Idempotency-Key: одинаковый payload переиспользует pending id.
 * Это защищает от двойного клика и повторной отправки после сетевой ошибки.
 */
async function creationKey(body) {
  let signature;
  if (window.crypto?.subtle) {
    const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(body));
    signature=[...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,"0")).join("");
  } else {
    signature=body; // Fallback stays in memory and is never persisted with reference images.
  }
  let pending=creationKey.pending;
  try { if (!pending) pending=JSON.parse(sessionStorage.getItem("factory.pending") || "null"); } catch {}
  if (!pending || pending.signature!==signature) pending={signature,id:window.crypto?.randomUUID?.() || "request_"+Date.now()+"_"+Math.random().toString(36).slice(2)};
  creationKey.pending=pending;
  if (signature.length===64) { try { sessionStorage.setItem("factory.pending",JSON.stringify(pending)); } catch {} }
  return pending.id;
}

// Собирает один payload, блокирует CTA на время запроса и сохраняет pending id для retry.
async function create() {
  if ($("#go").disabled || !OPT) return;
  const topic = $("#topic").value.trim();
  $("#err").textContent = "";
  if (!topic) { $("#topic").focus(); return; }
  if (val("style")==="custom" && !$("#custom-style").value.trim()) { $("#custom-style").focus(); return; }
  if (val("genre")==="custom" && !$("#custom-genre").value.trim()) { $("#custom-genre").focus(); return; }
  $("#go").disabled = true;
  const body=JSON.stringify({topic, script:$("#script").value, review:$("#review-script").checked, subtitles:subtitleSettings(), format:val("format"), minutes:+mins(), animate:val("animate"), reference:refData, scene_reference:sceneRefData, custom_style:$("#custom-style").value, custom_genre:$("#custom-genre").value,
      exact: !!refData && val("exact") === "1", lang:val("lang"), style:val("style"), genre:val("genre"), tone:val("tone"), narrator:val("narrator"), ending:val("ending"),
      audience:val("audience"), notes:$("#notes").value, video_model:val("vmodel"), max_price:+$("#maxprice").value || null, clips:clipsTouched && val("animate") !== "none" ? +$("#clips").value : null, voice_provider:val("provider"), voice:$("#voice").value,
      voice_speed:+$("#voice-speed").value, channel_name:$("#channel-name").value});
  let r;
  try {
    const id=await creationKey(body);
    const response=await fetch("/api/jobs",{method:"POST",headers:{"Content-Type":"application/json","Idempotency-Key":id},body});
    r=await response.json();
    if (!response.ok && !r.error) r={error:"Не удалось создать ролик"};
  } catch { r={error:"Нет связи с сервером. Повторная отправка сохранит ту же задачу."}; }
  $("#go").disabled = false;
  if (r.error) { $("#err").textContent = r.error; $("#err").scrollIntoView({block:"center",behavior:"smooth"}); return; }
  creationKey.pending=null;
  try { sessionStorage.removeItem("factory.pending"); } catch {}
  $("#topic").value = ""; $("#notes").value = ""; $("#script").value = ""; setIdeaTab("idea"); $("#refrm").click(); $("#scene-rm").click();
  if (!jobs.some(j => j.id === r.id)) jobs.unshift(r);
  openKit(r.id); load();
}
$("#go").onclick = create;
$("#topic").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); create(); } };
document.querySelectorAll(".idea").forEach(b => b.onclick = () => { $("#topic").value = b.textContent; $("#topic").focus({preventScroll:true}); });

let jobs = [];
let loadingJobs = false, reloadJobs = false;
let lastJobsMarkup = "";
/*
 * Единая загрузка истории. Событие, пришедшее во время запроса, не теряется:
 * после ответа история перезапрашивается, иначе последний статус «застревал».
 * Процент и этап (percent, stage) считает сервер — они переживают смену вкладок и перезагрузку.
 */
async function load() {
  if (loadingJobs) { reloadJobs = true; return; }
  loadingJobs = true;
  try {
    do {
      reloadJobs = false;
      const r = await fetch("/api/jobs").then(r => r.json()).catch(() => null);
      if (!Array.isArray(r)) continue;
      jobs = r;
      renderHistory();
      refreshKit();
    } while (reloadJobs);
  } finally { loadingJobs = false; }
}
let historyVisible=48;
const STATUS_LABELS = {done:"Готово", draft:"Сценарий", queued:"В очереди", running:"Создаётся", cancelling:"Останавливается", cancelled:"Остановлено", error:"Ошибка"};
function renderHistory() {
  const spent = jobs.filter(j => j.cost).reduce((a, j) => a + j.cost.total, 0);
  $("#spent").innerHTML = spent ? `потрачено <b>${money(spent)}</b>` : "";
  const query=$("#history-search").value.trim().toLocaleLowerCase();
  const status=$("#history-status").value;
  const filtered=jobs.filter(j=>(status==="deleted"?!!j.deleted_at:!j.deleted_at) && (status==="all"||status==="deleted"||(status==="running"?["running","queued","cancelling"].includes(j.status):j.status===status)) && String(j.title||j.topic).toLocaleLowerCase().includes(query));
  $("#history-more").hidden=filtered.length<=historyVisible;
  if (!filtered.length) { lastJobsMarkup = ""; $("#grid").innerHTML = `<div class="empty"><b>${jobs.length?"Нет роликов под этим фильтром":"Здесь появятся ваши ролики"}</b><span>${jobs.length?"Измените поиск или фильтр":"Опишите идею выше и нажмите «Создать ролик»"}</span></div>`; return; }
  const markup = filtered.slice(0,historyVisible).map(j => {
    const f = `/files/${j.id}/`, done = j.status === "done", active = ACTIVE.includes(j.status);
    const has = name => (j.files || []).includes(name), percent = j.percent ?? 0;
    const price = j.cost && j.cost.total>0 ? (j.accounting==="pending"?"≥ ":"")+money(j.cost.total) : "≈"+money(j.estimate?.total);
    const L = OPT?.langs?.[j.lang || "ru"] || "RU";
    const sub = j.deleted_at ? "Восстановить из корзины" : done ? `${L} · ${j.format === "vertical" ? "9:16" : "16:9"} · ${j.minutes} мин`
              : j.status === "draft" ? "Сценарий готов — проверить" : j.status === "error" ? "Ошибка — посмотреть подробности" : j.status === "cancelled" ? "Остановлено — можно продолжить" : `<b>${percent}%</b> · ${esc(j.stage || "В очереди")}`;
    const preview = has("cover.jpg") ? `<img src="${f}cover.jpg" alt="" loading="lazy" decoding="async">` : "";
    const downloads = [["video.mp4","MP4","видео"],["cover.jpg","JPG","обложку"],["all-texts.txt","TXT","тексты"]].filter(([name]) => has(name))
      .map(([name,label,what]) => `<a href="${f}${name}?download=1" download title="Скачать ${what}">${label}</a>`).join("");
    return `<article class="item ${esc(j.status)} ${j.format === "horizontal" ? "h" : ""}" data-job="${esc(j.id)}" tabindex="0">
      <span class="thumb"${has("cover.jpg") && j.format === "horizontal" ? ` style="--cover:url('${f}cover.jpg')"` : ""}>${preview}
        ${active ? `<span class="spin"><b>${percent}%</b></span>` : ""}
        <span class="badge">${j.deleted_at ? "Корзина" : STATUS_LABELS[j.status] || ""}</span>
        <span class="price">${price}</span>${done && downloads ? `<span class="quick-downloads">${downloads}</span>` : ""}</span>
      <span class="meta"><span class="t">${esc(j.title || j.topic)}</span><span class="s">${sub}</span>
        ${active ? `<span class="prog"><i style="width:${percent}%"></i></span>` : ""}
        ${active || j.deleted_at ? "" : `<button type="button" class="card-delete" data-delete="${esc(j.id)}" aria-label="Удалить ролик" title="Удалить"><svg class="ic" aria-hidden="true"><use href="#i-trash"/></svg></button>`}</span></article>`;
  }).join("");
  if (markup !== lastJobsMarkup) {
    $("#grid").innerHTML = markup;
    lastJobsMarkup = markup;
  }
}

$("#grid").onclick = e => {
  if (e.target.closest(".quick-downloads")) return;
  const remove = e.target.closest("[data-delete]");
  if (remove) return deleteJob(remove.dataset.delete);
  const item = e.target.closest("[data-job]");
  if (item) openJob(item.dataset.job);
};
$("#grid").onkeydown = e => { if ((e.key==="Enter" || e.key===" ") && e.target.matches("[data-job]")) { e.preventDefault(); openJob(e.target.dataset.job); } };

// Черновик открывает редактор сценария, остальные статусы — окно комплекта.
async function openJob(id) {
  const j = jobs.find(x => x.id === id);
  if (!j) return;
  if (j.deleted_at) { await postJob(j.id,"restore",{}); return load(); }
  if (j.status==="draft") return openScript(j);
  openKit(id);
}

document.querySelectorAll("[data-worktab]").forEach(button=>button.onclick=()=>{
  document.querySelectorAll("[data-worktab]").forEach(x=>{x.classList.toggle("active",x===button); if(x===button) x.setAttribute("aria-current","page"); else x.removeAttribute("aria-current");});
  const target=button.dataset.worktab;
  $("#project-history").hidden=target!=="history";
  $("#create").hidden=target==="history";
  $(".modes").hidden=target!=="create";
  $("#mode-heading").hidden=target!=="create";
  $("#video-workspace").hidden=target!=="create";
  $("#music-workspace").hidden=target!=="music";
  $("#checkout").hidden=target==="music";
  window.scrollTo({top:0,behavior:"smooth"});
});

// События воркера приходят пачками (каждый шаг сцены), поэтому история перезапрашивается не чаще раза в 1.5 с.
let jobEvents, loadTimer = null;
const scheduleLoad = () => { loadTimer ??= setTimeout(() => { loadTimer = null; load(); }, 1500); };
function connectJobEvents() {
  jobEvents?.close();
  if (document.hidden) return;
  load();
  if (window.EventSource) { jobEvents=new EventSource("/api/events"); jobEvents.onmessage=scheduleLoad; }
}
document.addEventListener("visibilitychange",connectJobEvents);
setInterval(()=>{if (!document.hidden) { balance(); if (!window.EventSource) load(); }},300000);




// Карточки формата, карусель на телефоне и переключатель режима субтитров.
function setupStudio() {
  const tabs=[...document.querySelectorAll('[data-project]')];
  const rail=$('.modes');
  const centerCard=card=>{ if (rail.scrollWidth<=rail.clientWidth) return; const left=rail.scrollLeft+card.getBoundingClientRect().left-rail.getBoundingClientRect().left; rail.scrollTo({left,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'}); };
  let carouselIndex=1;
  const move=step=>{const middle=rail.getBoundingClientRect().left+rail.clientWidth/2; carouselIndex=tabs.reduce((best,item,i)=>Math.abs(item.getBoundingClientRect().left+item.offsetWidth/2-middle)<Math.abs(tabs[best].getBoundingClientRect().left+tabs[best].offsetWidth/2-middle)?i:best,0); carouselIndex=Math.max(0,Math.min(tabs.length-1,carouselIndex+step));centerCard(tabs[carouselIndex]);};
  $('#mode-prev').onclick=()=>move(-1); $('#mode-next').onclick=()=>move(1);
  rail.addEventListener('keydown',e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();move(e.key==='ArrowRight'?1:-1);}});
  function choose(mode, change=true) {
    tabs.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.project===mode)));
    $('#project-history').hidden=true; $('#video-workspace').hidden=mode==='music'; $('#music-workspace').hidden=mode!=='music'; $('#checkout').hidden=mode==='music';
    if (mode==='music') return;
    if (change) { const input=$('#'+(mode==='none'?'a0':'a2')); input.checked=true; input.dispatchEvent(new Event('change',{bubbles:true})); }
    $('#animation-settings').hidden=mode==='none'; $('#clips-field').hidden=mode==='none'; $('.clips-hint').hidden=mode==='none';
  }
  tabs.forEach(b=>b.onclick=()=>{choose(b.dataset.project);centerCard(b);});
  document.querySelectorAll('input[name=animate]').forEach(i=>i.addEventListener('change',()=>choose(val('animate')==='none'?'none':'animated',false)));
  choose(val('animate')==='none'?'none':'animated',val('animate')==='key');  // старое «ключевые» → число сцен
  requestAnimationFrame(()=>centerCard(tabs.find(b=>b.getAttribute('aria-pressed')==='true')));
  const captionButtons=[...document.querySelectorAll('[data-caption]')];
  function syncCaptions(){captionButtons.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.caption===$('#subtitle-mode').value)));}
  captionButtons.forEach(b=>b.onclick=()=>{ $('#subtitle-mode').value=b.dataset.caption; $('#subtitle-mode').dispatchEvent(new Event('change',{bubbles:true}));syncCaptions(); });
  $('#subtitle-mode').addEventListener('change',syncCaptions); syncCaptions();
}

function setupCustomChoices() {
 const sync=()=>{ $('#custom-style-field').hidden=val('style')!=='custom'; $('#custom-genre-field').hidden=val('genre')!=='custom'; };
 document.querySelectorAll('[name=style],[name=genre]').forEach(input=>input.addEventListener('change',sync)); sync();
}

// Скрытый <select> остаётся источником значения для формы и localStorage, кнопки — визуальный слой.
function syncChoiceButtons(select) {
  const group=select.parentElement.querySelector(":scope > .choice-group");
  if (!group) return;
  group.querySelectorAll("button").forEach(button=>{
    const option=[...select.options].find(o=>o.value===button.dataset.value);
    button.setAttribute("aria-pressed",String(button.dataset.value===select.value));
    button.disabled=!!option?.disabled;
  });
}
// Особые виды кнопок: флаг у языка, превью у стиля, цена отдельной строкой у модели анимации.
const CHOICE_CONTENT = {
  langs: option => `<svg class="flag" aria-hidden="true"><use href="#flag-${esc(option.value)}"/></svg>${esc(option.textContent)}`,
  styles: option => (option.value === "custom" ? `<span class="style-custom"><svg aria-hidden="true"><use href="#i-plus"/></svg></span>` : `<img src="/img/styles/${esc(option.value)}.webp" alt="" loading="lazy" decoding="async">`) + esc(option.textContent),
  vmodels: option => { const [name, price] = option.textContent.split("|"); return `${esc(name)}<small>${esc(price)}</small>`; },
};
const CHOICE_MIN = {langs: "8.5rem", styles: "7.5rem", vmodels: "10rem", genres: "8rem", "history-status": "6.5rem"};
function setupChoiceButtons() {
  const ids=["langs","genres","tones","narrators","endings","audiences","styles","vmodels","providers","genders","subtitle-preset","subtitle-outline-mode","subtitle-timing","history-status"];
  const labels={"subtitle-preset":"Палитра","subtitle-outline-mode":"Цвет обводки","subtitle-timing":"Синхронизация","history-status":"Фильтр роликов"};
  ids.forEach(id=>{
    const select=document.getElementById(id);
    const group=document.createElement("div");
    group.className="choice-group"+(id==="styles"?" style-grid":"");
    group.setAttribute("role","group"); group.setAttribute("aria-label",labels[id]||select.parentElement.querySelector(":scope > span")?.textContent||id);
    if (CHOICE_MIN[id]) group.style.setProperty("--seg-min",CHOICE_MIN[id]);
    for(const option of select.options) {
      const button=document.createElement("button"); button.type="button"; button.dataset.value=option.value;
      button.innerHTML=CHOICE_CONTENT[id]?.(option) ?? esc(option.textContent);
      if (id==="vmodels") button.style.flexDirection="column";
      button.onclick=()=>{ if(select.value===option.value) return; select.value=option.value; select.dispatchEvent(new Event("input",{bubbles:true})); select.dispatchEvent(new Event("change",{bubbles:true})); syncChoiceButtons(select); };
      group.append(button);
    }
    select.hidden=true; select.insertAdjacentElement("afterend",group);
    select.addEventListener("change",()=>syncChoiceButtons(select)); syncChoiceButtons(select);
    if (id==="styles") setupCarousel(group, select);
  });
}

// Карусель стилей: стрелки листают на две карточки, выбранная карточка всегда в поле зрения.
function setupCarousel(group, select) {
  const wrap=document.createElement("div"); wrap.className="carousel";
  group.replaceWith(wrap); wrap.append(group);
  const nav=(name,label,step)=>{ const b=document.createElement("button"); b.type="button"; b.className="carousel-nav "+name; b.textContent=step<0?"‹":"›"; b.setAttribute("aria-label",label);
    b.onclick=()=>group.scrollBy({left:step*2*(group.firstElementChild.offsetWidth+12)}); wrap.append(b); return b; };
  const prev=nav("prev","Предыдущие стили",-1), next=nav("next","Следующие стили",1);
  const edges=()=>{ prev.disabled=group.scrollLeft<4; next.disabled=group.scrollLeft+group.clientWidth>=group.scrollWidth-4; };
  const reveal=()=>{ const on=group.querySelector('[aria-pressed="true"]'); if(on) group.scrollTo({left:on.offsetLeft-(group.clientWidth-on.offsetWidth)/2}); };
  group.addEventListener("scroll",edges,{passive:true}); addEventListener("resize",edges);
  select.addEventListener("change",reveal);
  requestAnimationFrame(()=>{ reveal(); edges(); });
}

// На телефоне план ролика — нижняя панель; «Состав» раскрывает подробности.
$("#summary-toggle").onclick=()=>{ const open=$("#checkout").classList.toggle("open"); $("#summary-toggle").setAttribute("aria-expanded",String(open)); };

function syncKeyboardPanel() {
  const field=document.activeElement;
  const editing=field && (field.matches('input:not([type="range"]):not([type="checkbox"]):not([type="radio"]), textarea') || field.isContentEditable);
  const viewport=window.visualViewport;
  document.body.classList.toggle("keyboard-open", !!(editing && viewport && window.innerHeight-viewport.height>120));
}
window.visualViewport?.addEventListener("resize",syncKeyboardPanel);
document.addEventListener("focusin",syncKeyboardPanel);
document.addEventListener("focusout",()=>setTimeout(syncKeyboardPanel,0));
