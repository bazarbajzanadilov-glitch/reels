"use strict";

const $ = s => document.querySelector(s);
const val = n => document.querySelector(`input[name=${n}]:checked`).value;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const money = x => "$" + Number(x || 0).toFixed(2);
const dlg = $("#dlg");

let OPT = null;
const mins = () => +$("#minutes").value;
const FLAGS = {ru: "🇷🇺", kk: "🇰🇿", en: "🇬🇧", de: "🇩🇪"};
function setMins(m) {
  $("#minutes").value = m; $("#mval").textContent = m + " мин";
  document.querySelectorAll(".chip[data-m]").forEach(c => c.classList.toggle("on", +c.dataset.m === m));
  if (OPT) estimate();
}
const seg = (id, name, items, checked) => $(id).innerHTML = Object.entries(items).map(([v, l]) =>
  `<input type="radio" name="${name}" id="${name}-${v}" value="${v}" ${v === checked ? "checked" : ""}><label for="${name}-${v}">${l}</label>`).join("");
function voices() {
  const p = OPT.voices[val("provider")], list = p[val("gender")];
  $("#voice").innerHTML = list.map(v => `<option value="${v}" ${v === p.default ? "selected" : ""}>${v[0].toUpperCase() + v.slice(1)}</option>`).join("");
}
async function init() {
  OPT = await fetch("/api/options").then(r => r.json());
  if (OPT.word_timing) { $("#subtitle-word-option").disabled=false; $("#subtitle-word-option").textContent="По словам · локальная обработка"; }
  seg("#langs", "lang", Object.fromEntries(Object.entries(OPT.langs).map(([k, v]) => [k, `${FLAGS[k] || ""} ${v}`])), "ru");
  seg("#genres", "genre", OPT.genres, "auto");
  seg("#tones", "tone", OPT.tones, "auto");
  seg("#vmodels", "vmodel", Object.fromEntries(Object.entries(OPT.video_models).map(([k, v]) =>
    [k, `${v.label}<small>${v.note} · $${v.price.toFixed(2)}</small>`])), "wan");
  let priceTimer;
  $("#maxprice").oninput = () => { clearTimeout(priceTimer); priceTimer = setTimeout(estimate, 300); };
  seg("#narrators", "narrator", OPT.narrators, "auto");
  seg("#endings", "ending", OPT.endings, "auto");
  seg("#audiences", "audience", OPT.audiences, "all");
  $("#morebtn").onclick = () => { const o = $("#extra").classList.toggle("open");
    $("#morebtn").setAttribute("aria-expanded", String(o));
    $("#morebtn").textContent = o ? "Скрыть настройки сюжета ▴" : "Ещё настройки сюжета ▾"; };
  seg("#styles", "style", Object.fromEntries(Object.entries(OPT.styles).map(([k, v]) => [k, v.replace(" мультфильм", "")])), "2d");
  seg("#providers", "provider", Object.fromEntries(Object.entries(OPT.voices).map(([k, v]) => [k, v.label])), "gemini");
  $("#minutes").oninput = () => setMins(mins());
  document.querySelectorAll(".chip[data-m]").forEach(c => c.onclick = () => setMins(+c.dataset.m));
  seg("#genders", "gender", {male: "Мужской", female: "Женский"}, "male");
  voices();
  document.querySelectorAll(".panel input[type=radio]").forEach(i => i.onchange = () => {
    if (["provider", "gender", "lang"].includes(i.name)) stopAudio();
    if (i.name === "provider" || i.name === "gender") voices();
    estimate(); });
  restorePreferences();
  setupStudio();
  setupCustomChoices();
  $("#go").disabled = false;
  await estimate();
}
let estimateController;
function summary() {
  const label = (name, items) => { const v = val(name); const x = items?.[v]; return typeof x === "string" ? x : x?.label || v; };
  const rows = [
    ["i-screen", val("format") === "vertical" ? "Вертикально 9:16" : "Горизонтально 16:9"],
    ["i-clock", mins() + " мин"],
    ["i-globe", `${FLAGS[val("lang")] || ""} ${label("lang", OPT.langs)}`],
    ["i-palette", label("style", OPT.styles)],
    ["i-book", label("genre", OPT.genres)],
    ["i-mic", `${$("#voice").value || ""} · ${label("provider", Object.fromEntries(Object.entries(OPT.voices).map(([k, v]) => [k, v.label])))}`],
  ];
  $("#summary-list").innerHTML = rows.map(([icon, text]) => `<li><svg class="ic"><use href="#${icon}"/></svg>${esc(text)}</li>`).join("");
}
async function estimate() {
  if (!OPT) return;
  summary();
  const ex = refData && val("exact") === "1" ? 1 : 0;
  estimateController?.abort();
  const controller = estimateController = new AbortController();
  const query = new URLSearchParams({minutes:mins(), animate:val("animate"), exact:ex,
    voice:val("provider"), style:val("style"), video:val("vmodel"), max:$("#maxprice").value || 0});
  try {
    const response = await fetch(`/api/estimate?${query}`, {signal:controller.signal});
    if (!response.ok) throw new Error("estimate");
    const r = await response.json();
    if (controller.signal.aborted) return;
    $("#est").textContent = "≈ " + money(r.total);
    $("#price-big").textContent = "≈ " + money(r.total);
    $("#scene-summary").innerHTML = `<span><strong>${r.scenes}</strong> сцен</span><span><strong>${r.clips || 0}</strong> с анимацией</span>`;
    $("#note").textContent = "Списывается по факту. Повторы используют уже готовые материалы.";
  } catch (error) {
    if (error.name !== "AbortError") {
      $("#est").textContent = "";
      $("#note").textContent = "Не удалось рассчитать цену. Попробуйте изменить настройки.";
    }
  }
}

let audio = null;
function stopAudio() {
  if (audio) { audio.pause(); audio.removeAttribute("src"); audio.load(); }
  audio = null;
  $("#play").textContent = "▶";
  $("#play").classList.remove("busy");
}
$("#play").onclick = async () => {
  if (audio) { stopAudio(); return; }
  $("#play").classList.add("busy");
  const sample = audio = new Audio(`/voices/${val("provider")}/${$("#voice").value}_${val("lang")}.mp3`);
  sample.oncanplay = () => { if (audio === sample) $("#play").classList.remove("busy"); };
  sample.onended = sample.onerror = () => { if (audio === sample) stopAudio(); };
  $("#play").textContent = "■";
  try { await sample.play(); } catch { if (audio === sample) stopAudio(); }
};
$("#voice").onchange = () => { stopAudio(); summary(); };

async function balance() {
  const r = await fetch("/api/balance").then(r => r.json()).catch(() => ({}));
  $("#bal").innerHTML = r.balance != null ? `Баланс <b>${money(r.balance)}</b>` : "—";
}

let refData = null, sceneRefData = null;
$("#reffile").onchange = e => {
  const file = e.target.files[0]; if (!file) return;
  const img = new Image();
  const imageURL = URL.createObjectURL(file);
  img.onload = () => {
    URL.revokeObjectURL(imageURL);
    const k = Math.min(1, 1024 / Math.max(img.width, img.height)), c = document.createElement("canvas");
    c.width = img.width * k; c.height = img.height * k; c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    refData = c.toDataURL("image/jpeg", 0.88);
    $("#ref").textContent = "✓ Персонаж · заменить";
    $("#refrm").hidden = false;
    $("#exactrow").style.display = ""; estimate();
  };
  img.onerror = () => { URL.revokeObjectURL(imageURL); $("#reffile").value = ""; $("#err").textContent = "Не удалось открыть изображение. Выберите JPG, PNG или WebP."; };
  img.src = imageURL;
};
$("#refrm").onclick = e => { e.preventDefault(); e.stopPropagation(); refData = null; $("#reffile").value = "";
  $("#refrm").hidden = true;
  $("#ref").textContent = "＋ Персонаж";
  $("#exactrow").style.display = "none"; $("#e0").checked = true; estimate(); };

$("#scene-file").onchange = e => {
  const file=e.target.files[0]; if (!file) return;
  const img=new Image(), url=URL.createObjectURL(file);
  img.onload=()=>{ URL.revokeObjectURL(url); const k=Math.min(1,1024/Math.max(img.width,img.height)), c=document.createElement("canvas"); c.width=img.width*k; c.height=img.height*k; c.getContext("2d").drawImage(img,0,0,c.width,c.height); sceneRefData=c.toDataURL("image/jpeg",.88); $("#scene-ref").textContent="✓ Сцена · заменить"; $("#scene-rm").hidden=false; };
  img.onerror=()=>{ URL.revokeObjectURL(url); e.target.value=""; $("#err").textContent="Не удалось открыть изображение. Выберите JPG, PNG или WebP."; }; img.src=url;
};
$("#scene-rm").onclick=()=>{sceneRefData=null; $("#scene-file").value=""; $("#scene-ref").textContent="＋ Сцена"; $("#scene-rm").hidden=true;};

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
      audience:val("audience"), notes:$("#notes").value, video_model:val("vmodel"), max_price:+$("#maxprice").value || null, voice_provider:val("provider"), voice:$("#voice").value});
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
  if (!filtered.length) { lastJobsMarkup = ""; $("#grid").innerHTML = `<div class="empty"><svg class="ic"><use href="#i-film"/></svg><b>${jobs.length?"Нет роликов под этим фильтром":"Здесь появятся ваши ролики"}</b><span>${jobs.length?"Измените поиск или фильтр":"Опишите идею выше и нажмите «Создать ролик»"}</span></div>`; return; }
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
    if (change) { const input=$('#'+(mode==='none'?'a0':'a1')); input.checked=true; input.dispatchEvent(new Event('change',{bubbles:true})); }
    $('#animation-settings').classList.toggle('no-animation',mode==='none');
  }
  tabs.forEach(b=>b.onclick=()=>choose(b.dataset.project));
  document.querySelectorAll('input[name=animate]').forEach(i=>i.addEventListener('change',()=>choose(val('animate')==='none'?'none':'animated',false)));
  choose(val('animate')==='none'?'none':'animated',false);
  const captionButtons=[...document.querySelectorAll('[data-caption]')];
  function syncCaptions(){captionButtons.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.caption===$('#subtitle-mode').value)));}
  captionButtons.forEach(b=>b.onclick=()=>{ $('#subtitle-mode').value=b.dataset.caption; $('#subtitle-mode').dispatchEvent(new Event('change',{bubbles:true}));syncCaptions(); });
  $('#subtitle-mode').addEventListener('change',syncCaptions); syncCaptions();
}

function setupCustomChoices() {
 const sync=()=>{ $('#custom-style-field').hidden=val('style')!=='custom'; $('#custom-genre-field').hidden=val('genre')!=='custom'; };
 document.querySelectorAll('[name=style],[name=genre]').forEach(input=>input.addEventListener('change',sync)); sync();
}
