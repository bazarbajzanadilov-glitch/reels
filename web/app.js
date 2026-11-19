"use strict";

const $ = s => document.querySelector(s);
const val = n => document.querySelector(`input[name=${n}]:checked`).value;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const money = x => "$" + Number(x || 0).toFixed(2);
const dlg = $("#dlg");

let OPT = null;
const mins = () => +$("#minutes").value;
const FLAGS = {ru: "🇷🇺", kk: "🇰🇿", en: "🇬🇧", de: "🇩🇪"};
const LANG_NAMES = {ru: "Русский", kk: "Қазақша", en: "English", de: "Deutsch"};
const STYLE_NOTES = {"2d": "Плоская векторная графика", "3d": "Объём, как в мультфильмах Pixar", anime: "Японская анимация",
  real: "Как настоящее фото", comic: "Чёткие контуры, яркие цвета", watercolor: "Мягкие краски на бумаге",
  clay: "Пластилиновые герои", pixel: "Ретро-игры, пиксели", noir: "Чёрно-белое кино, тени",
  paper: "Аппликация из бумаги", custom: "Опишите сами"};

function setMins(m) {
  $("#minutes").value = m; $("#mval").textContent = m + " мин";
  document.querySelectorAll(".chip[data-m]").forEach(c => c.classList.toggle("on", +c.dataset.m === m));
  if (OPT) estimate();
}
const radio = (name, v, checked) => `<input type="radio" name="${name}" id="${name}-${v}" value="${v}" ${v === checked ? "checked" : ""}>`;
const seg = (id, name, items, checked) => $(id).innerHTML = Object.entries(items).map(([v, l]) =>
  `${radio(name, v, checked)}<label for="${name}-${v}">${l}</label>`).join("");
// плитки: [значение, содержимое] → радио + оформленная метка
const tiles = (id, name, entries, checked, cls) => $(id).innerHTML = entries.map(([v, body]) =>
  `${radio(name, v, checked)}<label class="tile ${cls}" for="${name}-${v}">${body}</label>`).join("");

function voices() {
  const p = OPT.voices[val("provider")], list = p[val("gender")];
  $("#voice").innerHTML = list.map(v => `<option value="${v}" ${v === p.default ? "selected" : ""}>${v}</option>`).join("");
  if (!list.includes($("#voice").value)) $("#voice").value = list[0];
  // один клик по голосу: выбрать и сразу прослушать; повторный клик по играющему — остановить
  $("#voice-list").innerHTML = list.map(v => `<button type="button" class="voice" data-voice="${esc(v)}" role="radio" aria-checked="false">
    <span class="eq" aria-hidden="true"><i></i><i></i><i></i></span><b>${esc(v[0].toUpperCase() + v.slice(1))}</b></button>`).join("");
  syncVoices();
}
function syncVoices() {
  document.querySelectorAll("#voice-list .voice").forEach(el => {
    const on = el.dataset.voice === $("#voice").value;
    el.classList.toggle("on", on); el.setAttribute("aria-checked", String(on));
  });
}
$("#voice-list").onclick = e => {
  const tile = e.target.closest(".voice"); if (!tile) return;
  if ($("#voice").value !== tile.dataset.voice) {
    $("#voice").value = tile.dataset.voice;
    $("#voice").dispatchEvent(new Event("change", {bubbles: true}));
  }
  playVoice(tile.dataset.voice, tile);
};

async function init() {
  OPT = await fetch("/api/options").then(r => r.json());
  if (OPT.word_timing) { $("#subtitle-word-option").disabled = false; $("#subtitle-word-option").textContent = "По словам"; }
  tiles("#langs", "lang", Object.keys(OPT.langs).map(k =>
    [k, `<span class="flag">${FLAGS[k] || ""}</span><b>${OPT.langs[k]}</b><small>${LANG_NAMES[k] || ""}</small>`]), "ru", "tile-lang");
  tiles("#genres", "genre", Object.entries(OPT.genres).map(([k, l]) =>
    [k, `<b>${esc(l)}</b>`]), "auto", "tile-text");
  seg("#tones", "tone", OPT.tones, "auto");
  tiles("#styles", "style", Object.entries(OPT.styles).map(([k, l]) =>
    [k, `<b>${esc(l.replace(" мультфильм", ""))}</b><small>${STYLE_NOTES[k] || ""}</small>`]), "2d", "tile-style");
  tiles("#vmodels", "vmodel", Object.entries(OPT.video_models).map(([k, v]) =>
    [k, `<span class="dot"></span><b>${esc(v.label)}</b><small>${esc(v.note)}</small><em>${money(v.price)} <i>за сцену</i></em>`]), "pvideo", "row-option");
  let priceTimer;
  $("#maxprice").oninput = () => { clearTimeout(priceTimer); priceTimer = setTimeout(estimate, 300); };
  $("#clips").oninput = () => { clipsTouched = true; $("#clips-value").textContent = `${$("#clips").value} из ${$("#clips").max}`;
    clearTimeout(priceTimer); priceTimer = setTimeout(estimate, 200); };
  $("#clips-reset").onclick = () => { clipsTouched = false; estimate(); };
  seg("#narrators", "narrator", OPT.narrators, "auto");
  seg("#endings", "ending", OPT.endings, "auto");
  seg("#audiences", "audience", OPT.audiences, "all");
  $("#morebtn").onclick = () => { const o = $("#extra").classList.toggle("open");
    $("#morebtn").setAttribute("aria-expanded", String(o));
    $("#morebtn").textContent = o ? "Скрыть настройки сюжета ▴" : "Ещё настройки сюжета ▾"; };
  seg("#providers", "provider", Object.fromEntries(Object.entries(OPT.voices).map(([k, v]) => [k, v.label])), "gemini");
  seg("#genders", "gender", {male: "Мужские", female: "Женские"}, "male");
  $("#minutes").oninput = () => setMins(mins());
  document.querySelectorAll(".chip[data-m]").forEach(c => c.onclick = () => setMins(+c.dataset.m));
  voices();
  document.querySelectorAll(".panel input[type=radio]").forEach(i => i.onchange = () => {
    if (["provider", "gender", "lang"].includes(i.name)) stopAudio();
    if (i.name === "provider" || i.name === "gender") voices();
    estimate(); });
  restorePreferences();
  syncVoices();
  setMins(mins());
  setupStudio();
  setupCustomChoices();
  $("#go").disabled = false;
  await estimate();
}

let estimateController;
function summary() {
  const label = (name, items) => { const v = val(name); const x = items?.[v]; return typeof x === "string" ? x : x?.label || v; };
  const rows = [
    ["Формат", `${val("format") === "vertical" ? "9:16" : "16:9"} · ${mins()} мин`],
    ["Язык", LANG_NAMES[val("lang")] || ""],
    ["Сюжет", `${label("genre", OPT.genres)} · ${label("tone", OPT.tones).toLowerCase()}`],
    ["Стиль", label("style", OPT.styles)],
    ["Голос", `${$("#voice").value || ""} · ${OPT.voices[val("provider")].label}`],
  ];
  $("#summary-list").innerHTML = rows.map(([k, text]) => `<li><span>${k}</span><b>${esc(text)}</b></li>`).join("");
}
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
    $("#price-big").textContent = "≈ " + money(r.total);
    $("#scene-summary").innerHTML = `<span><b>${r.scenes}</b>сцен</span><span><b>${r.clips || 0}</b>с анимацией</span>`;
    showClips(r);
    $("#note").textContent = "Списывается по факту";
  } catch (error) {
    if (error.name !== "AbortError") {
      $("#est").textContent = "";
      $("#note").textContent = "Не удалось рассчитать цену";
    }
  }
}

// сколько сцен оживить: по умолчанию 4 на минуту в пределах стандартного лимита, ползунком — любое число
let clipsTouched = false;
function showClips(r) {
  const slider = $("#clips"), want = clipsTouched ? r.wanted : r.clips;
  slider.max = Math.max(1, r.scenes);
  slider.value = Math.max(1, want);
  $("#clips-value").textContent = `${r.clips} из ${r.scenes}`;
  $("#clips-reset").hidden = !clipsTouched;
  const max = +$("#maxprice").value;
  $("#maxprice").placeholder = "авто · " + r.budget.toFixed(2);
  if (r.capped && max) {
    const need = Math.ceil((r.minimum + r.wanted * r.clip_price) * 1.15 * 20) / 20;
    $("#clips-note").innerHTML = `В лимит $${max.toFixed(2)} помещается ${r.clips} из ${r.wanted}. <button type="button" class="link" id="raise">Поднять лимит до $${need.toFixed(2)}</button>`;
    $("#raise").onclick = () => { $("#maxprice").value = need.toFixed(2); $("#maxprice").dispatchEvent(new Event("change", {bubbles: true})); estimate(); };
  } else if (r.capped) {
    $("#clips-note").textContent = `В стандартный лимит $${r.budget.toFixed(2)} помещается ${r.clips}. Сдвиньте ползунок — лимит поднимется.`;
  } else {
    $("#clips-note").textContent = clipsTouched ? `Лимит подстроен: до $${r.budget.toFixed(2)}.` : "По умолчанию 4 на минуту ролика.";
  }
}

let audio = null, audioButton = null;
function stopAudio() {
  if (audio) { audio.pause(); audio.removeAttribute("src"); audio.load(); }
  audio = null;
  if (audioButton) audioButton.classList.remove("busy", "playing");
  audioButton = null;
}
async function playVoice(name, button) {
  const same = audioButton === button;
  stopAudio();
  if (same) return;
  audioButton = button;
  button.classList.add("busy", "playing");
  const sample = audio = new Audio(`/voices/${val("provider")}/${name}_${val("lang")}.mp3`);
  sample.oncanplay = () => { if (audio === sample) button.classList.remove("busy"); };
  sample.onended = sample.onerror = () => { if (audio === sample) stopAudio(); };
  try { await sample.play(); } catch { if (audio === sample) stopAudio(); }
}
$("#voice").onchange = () => { syncVoices(); summary(); };

async function balance() {
  const r = await fetch("/api/balance").then(r => r.json()).catch(() => ({}));
  const el = $("#bal");
  if (r.balance == null) { el.innerHTML = `<span>Баланс</span><b>—</b>`; return; }
  el.innerHTML = `<span>Баланс</span><b>${money(r.balance)}</b>`;
  el.classList.toggle("low", r.balance < 1);
}

let refData = null, sceneRefData = null;
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
  $("#exactrow").style.display = ""; estimate();
});
$("#refrm").onclick = e => { e.preventDefault(); e.stopPropagation(); refData = null; $("#reffile").value = "";
  showReference("#ref", "#refrm", null, "Персонаж");
  $("#exactrow").style.display = "none"; $("#e0").checked = true; estimate(); };
$("#scene-file").onchange = e => readImage(e.target, data => { sceneRefData = data; showReference("#scene-ref", "#scene-rm", data, "Место добавлено"); });
$("#scene-rm").onclick = () => { sceneRefData = null; $("#scene-file").value = ""; showReference("#scene-ref", "#scene-rm", null, "Место действия"); };

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

async function create() {
  if ($("#go").disabled || !OPT) return;
  const topic = $("#topic").value.trim();
  $("#err").textContent = "";
  if (!topic) { $("#topic").focus(); return; }
  if (val("style")==="custom" && !$("#custom-style").value.trim()) { $("#custom-style").focus(); return; }
  if (val("genre")==="custom" && !$("#custom-genre").value.trim()) { $("#custom-genre").focus(); return; }
  $("#go").disabled = true;
  const body=JSON.stringify({topic, review:$("#review-script").checked, subtitles:subtitleSettings(), format:val("format"), minutes:+mins(), animate:val("animate"), reference:refData, scene_reference:sceneRefData, custom_style:$("#custom-style").value, custom_genre:$("#custom-genre").value,
      exact: !!refData && val("exact") === "1", lang:val("lang"), style:val("style"), genre:val("genre"), tone:val("tone"), narrator:val("narrator"), ending:val("ending"),
      audience:val("audience"), notes:$("#notes").value, video_model:val("vmodel"), max_price:+$("#maxprice").value || null, clips:clipsTouched && val("animate") !== "none" ? +$("#clips").value : null, voice_provider:val("provider"), voice:$("#voice").value});
  let r;
  try {
    const id=await creationKey(body);
    const response=await fetch("/api/jobs",{method:"POST",headers:{"Content-Type":"application/json","Idempotency-Key":id},body});
    r=await response.json();
    if (!response.ok && !r.error) r={error:"Не удалось создать ролик"};
  } catch { r={error:"Нет связи с сервером. Повторная отправка сохранит ту же задачу."}; }
  $("#go").disabled = false;
  if (r.error) { $("#err").textContent = r.error; return; }
  creationKey.pending=null;
  try { sessionStorage.removeItem("factory.pending"); } catch {}
  $("#topic").value = ""; $("#notes").value = ""; $("#refrm").click(); $("#scene-rm").click(); load();
}
$("#go").onclick = create;
$("#topic").onkeydown = e => { if (e.key === "Enter") create(); };
document.querySelectorAll(".idea").forEach(b => b.onclick = () => { $("#topic").value = b.textContent; $("#topic").focus(); });

// грубый процент готовности по этапу
function pct(p = "") {
  const m = p.match(/(\d+)\/(\d+)/), n = m ? m[1] / m[2] : 0, k = p.match(/монтаж (\d+)%/);
  if (p.startsWith("озвучка")) return 8 + 12 * n;
  if (p.startsWith("картинки")) return 20 + 15 * n;
  if (p.startsWith("анимация")) return 35 + 35 * n;
  if (k) return 72 + 0.22 * k[1];
  if (/обложка|архив/.test(p)) return 96;
  if (/сценарий готов|повтор/.test(p)) return 7;
  return 3;
}

let jobs = [];
let loadingJobs = false;
let lastJobsMarkup = "";
async function load() {
  if (loadingJobs) return;
  loadingJobs = true;
  const r = await fetch("/api/jobs").then(r => r.json()).catch(() => null);
  loadingJobs = false;
  if (!Array.isArray(r)) return;
  jobs = r;
  renderHistory();
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
    const f = `/files/${j.id}/`, done = j.status === "done";
    const price = j.cost && j.cost.total>0 ? (j.accounting==="pending"?"≥ ":"")+money(j.cost.total) : "≈"+money(j.estimate?.total);
    const L = OPT?.langs?.[j.lang || "ru"] || "RU";
    const sub = j.deleted_at ? "Восстановить из корзины" : done ? `${L} · ${j.format === "vertical" ? "9:16" : "16:9"} · ${j.minutes} мин`
              : j.status === "draft" ? "Сценарий готов — проверить" : j.status === "error" ? "Ошибка — посмотреть подробности" : j.status === "queued" ? "В очереди" : j.status === "cancelled" ? "Остановлено — можно продолжить" : esc(j.progress);
    return `<button type="button" class="item ${esc(j.status)} ${j.format === "horizontal" ? "h" : ""}" data-job="${esc(j.id)}">
      <span class="thumb">${done ? `<img src="${f}cover.jpg" alt="" loading="lazy" decoding="async">` : ""}
        ${["running","queued","cancelling"].includes(j.status) ? '<span class="spin"></span>' : ""}
        <span class="badge">${j.deleted_at ? "Корзина" : STATUS_LABELS[j.status] || ""}</span>
        <span class="price">${price}</span></span>
      <span class="meta"><span class="t">${esc(j.title || j.topic)}</span><span class="s">${sub}</span>
        ${j.status === "running" ? `<span class="prog"><i style="width:${pct(j.progress)}%"></i></span>` : ""}</span></button>`;
  }).join("");
  if (markup !== lastJobsMarkup) {
    $("#grid").innerHTML = markup;
    lastJobsMarkup = markup;
  }
}

$("#grid").onclick = e => { const item = e.target.closest("[data-job]"); if (item) openJob(item.dataset.job); };
$("#close-dialog").onclick = () => dlg.close();

let cur = null;
let openingJob = 0;
async function openJob(id) {
  const j = jobs.find(x => x.id === id);
  if (!j) return;
  if (j.deleted_at) { await postJob(j.id,"restore",{}); return load(); }
  if (j.status==="draft") return openScript(j);
  if (["error","cancelled","queued","running","cancelling"].includes(j.status)) {
    retryJob = j.id;
    retryAction=["queued","running","cancelling"].includes(j.status)?"cancel":"retry";
    $("#retry-title").textContent=retryAction==="cancel"?"Остановить создание?":"Повторить создание?";
    $("#retry-go").textContent=retryAction==="cancel"?"Остановить":"Повторить";
    $("#retry-error").textContent = j.progress || "Не удалось создать ролик";
    $("#retry-note").textContent=retryAction==="cancel"?"Новые запросы остановятся. Уже отправленные запросы могут завершиться и быть оплачены.":"Повтор использует оставшийся бюджет. Готовые материалы и этапы используются повторно.";
    $("#retry-dialog").showModal();
    return;
  }
  if (j.status !== "done") return;
  const opening = ++openingJob;
  cur = j; const f = `/files/${id}/`;
  $("#dialog-status").textContent = "";
  $("#dt").textContent = j.title || j.topic;
  $("#vid").src = f + "video.mp4"; $("#vid").poster = f + "cover.jpg";
  $("#dzip").href = f + "result.zip"; $("#dvid").href = f + "video.mp4"; $("#dcov").href = f + "cover.jpg";
  $("#dsrt").hidden = !j.files?.includes("subtitles.srt");
  $("#dsrt").href = f + "subtitles.srt";
  $("#dass").hidden=!j.files?.includes("subtitles.ass"); $("#dass").href=f+"subtitles.ass";
  $("#dcost").innerHTML=j.cost?`Стоимость <b>${j.accounting==="pending"?"≥ ":""}${money(j.cost.total)}</b>${j.accounting==="pending"?" · уточняется":""}`:"Стоимость уточняется";
  if (j.budget_status) $("#dcost").innerHTML+=` · Остаток лимита <b>${money(j.budget_status.remaining)}</b>`;
  $("#dinfo").textContent = `${j.format === "vertical" ? "9:16" : "16:9"} · ${j.minutes} мин`;
  const result = await fetch(f + "social.json").then(r => r.ok ? r.json() : null).catch(() => null);
  if (opening !== openingJob) return;
  social = result;
  tab("youtube");
  if (!dlg.open) dlg.showModal();
}
dlg.addEventListener("close", () => { $("#vid").pause(); $("#vid").removeAttribute("src"); $("#vid").load(); });
dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });

let social = null;
const ICON_COPY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>';
const ICON_OK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>';
let selectedTab = 0;
async function tab(name) {
  const requestId = ++selectedTab;
  const jobId = cur.id;
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.f === name));
  const fields = social?.[name] || {"Текст": await fetch(`/files/${cur.id}/${name}.txt`).then(r => r.text()).catch(() => "")};
  if (requestId !== selectedTab || cur.id !== jobId) return;
  $("#dialog-status").textContent = "";
  $("#fields").innerHTML = Object.entries(fields).map(([k, v], i) =>
    `<div class="field"><div class="fh"><span>${esc(k)}</span><button class="copy" data-i="${i}" title="Копировать">${ICON_COPY}</button></div><div class="fv">${esc(v)}</div></div>`).join("");
  const vals = Object.values(fields);
  $("#fields").querySelectorAll(".copy").forEach(b => b.onclick = async () => {
    try { await navigator.clipboard.writeText(vals[b.dataset.i]); }
    catch {
      const value = String(vals[b.dataset.i]);
      const input = document.createElement("textarea");
      input.value = value;
      input.readOnly = true;
      input.style.cssText = "position:fixed;left:0;top:0;opacity:0;font-size:16px";
      dlg.append(input);
      let copied = false;
      try { input.focus(); input.select(); input.setSelectionRange(0, value.length); copied = document.execCommand("copy"); }
      catch { /* A browser may allow only manual selection. */ }
      input.remove();
      b.focus({preventScroll:true});
      if (!copied) {
        const range = document.createRange();
        range.selectNodeContents(b.closest(".field").querySelector(".fv"));
        const selection = window.getSelection();
        selection.removeAllRanges(); selection.addRange(range);
        $("#dialog-status").textContent = "Текст выделен. Нажмите и удерживайте его, затем выберите «Копировать».";
        return;
      }
    }
    b.innerHTML = ICON_OK; b.classList.add("ok");
    setTimeout(() => { b.innerHTML = ICON_COPY; b.classList.remove("ok"); }, 1200);
  });
}
document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => tab(b.dataset.f));

let jobEvents;
function connectJobEvents() {
  jobEvents?.close();
  load();
  if (document.hidden) return;
  if (window.EventSource) { jobEvents=new EventSource("/api/events"); jobEvents.onmessage=()=>load(); }
}
document.addEventListener("visibilitychange",connectJobEvents);
setInterval(()=>{if (!document.hidden) { balance(); if (!window.EventSource) load(); }},60000);

let retryJob = null, retryAction="retry";
$("#retry-cancel").onclick = () => $("#retry-dialog").close();
$("#retry-go").onclick = async () => {
  if (!retryJob || $("#retry-go").disabled) return;
  $("#retry-go").disabled = true;
  try {
    const response = await fetch(`/api/jobs/${retryJob}/${retryAction}`, {method:"POST"});
    const result = await response.json();
    if (!response.ok || result.error) throw new Error(result.error || "Не удалось повторить");
    $("#retry-dialog").close();
    await load();
  } catch (error) { $("#retry-error").textContent = error.message; }
  finally { $("#retry-go").disabled = false; }
};



function setupStudio() {
  const tabs=[...document.querySelectorAll('[data-project]')];
  function choose(mode, change=true) {
    tabs.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.project===mode)));
    $('#project-history').hidden=mode==='music'; $('#video-workspace').hidden=mode==='music'; $('#music-workspace').hidden=mode!=='music'; $('#checkout').hidden=mode==='music';
    if (mode==='music') return;
    if (change) { const input=$('#'+(mode==='none'?'a0':'a2')); input.checked=true; input.dispatchEvent(new Event('change',{bubbles:true})); }
    $('#animation-settings').classList.toggle('no-animation',mode==='none');
  }
  tabs.forEach(b=>b.onclick=()=>choose(b.dataset.project));
  document.querySelectorAll('input[name=animate]').forEach(i=>i.addEventListener('change',()=>choose(val('animate')==='none'?'none':'animated',false)));
  choose(val('animate')==='none'?'none':'animated',val('animate')==='key');  // старое «ключевые» → число сцен
  const captionButtons=[...document.querySelectorAll('[data-caption]')];
  function syncCaptions(){captionButtons.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.caption===$('#subtitle-mode').value)));}
  captionButtons.forEach(b=>b.onclick=()=>{ $('#subtitle-mode').value=b.dataset.caption; $('#subtitle-mode').dispatchEvent(new Event('change',{bubbles:true}));syncCaptions(); });
  $('#subtitle-mode').addEventListener('change',syncCaptions); syncCaptions();
}

function setupCustomChoices() {
 const sync=()=>{ $('#custom-style-field').hidden=val('style')!=='custom'; $('#custom-genre-field').hidden=val('genre')!=='custom'; };
 document.querySelectorAll('[name=style],[name=genre]').forEach(input=>input.addEventListener('change',sync)); sync();
}
