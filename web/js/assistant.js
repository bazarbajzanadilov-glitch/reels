"use strict";

/*
 * ИИ-помощник на шаге «Создание»: ниша → тема → черновик сценария → форма ролика.
 * Темы берутся из готовой библиотеки (/data/topics.json) и листаются по кругу бесплатно.
 * Платный запрос — только «Придумать ИИ» для своей ниши и написание сценария;
 * сервер кэширует ответы и ограничивает число запросов в сутки.
 */
const AI_PAGE = 6, AI_REWRITES = 3;
let aiLibrary = {}, aiNiche = "", aiTopic = "", aiBusy = false, aiRewrites = 0;

const aiStore = {
  get(name, fallback) { try { return JSON.parse(localStorage.getItem("factory.ai." + name)) ?? fallback; } catch { return fallback; } },
  set(name, value) { try { localStorage.setItem("factory.ai." + name, JSON.stringify(value)); } catch { /* только удобство */ } },
};

function aiStatus(text, error = false) {
  $("#ai-status").textContent = text;
  $("#ai-status").classList.toggle("error", error);
}
function aiQuotaText() {
  return OPT ?`Темы из библиотеки бесплатны · ИИ-запросов на сегодня: ${OPT.assistant_left}` : "";
}

async function aiPost(path, body) {
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const data = await response.json().catch(() => ({}));
  if (data.left != null && OPT) OPT.assistant_left = data.left;
  if (!response.ok || data.error) throw new Error(data.error || (response.status === 429 ? "Слишком много запросов. Подождите минуту" : "ИИ-помощник недоступен"));
  return data;
}

function setAiBusy(value) {
  aiBusy = value;
  for (const node of document.querySelectorAll("#ai-send, #ai-query, #ai-more, #ai-rewrite, #ai-use, .ai-topic")) node.disabled = value;
}

function renderNiches() {
  $("#ai-niches").innerHTML = Object.keys(aiLibrary).map(name =>
    `<button type="button" data-niche="${esc(name)}" aria-pressed="${name === aiNiche}">${esc(name)}<span class="hint">${aiLibrary[name].length}</span></button>`).join("");
}

function renderTopics() {
  const list = aiLibrary[aiNiche] || [], offsets = aiStore.get("offsets", {});
  const start = (offsets[aiNiche] || 0) % Math.max(1, list.length);
  const page = Array.from({length: Math.min(AI_PAGE, list.length)}, (_, i) => list[(start + i) % list.length]);
  $("#ai-niche-title").textContent = aiNiche ? `${aiNiche} · ${list.length} тем` : "Темы";
  $("#ai-topics").innerHTML = page.length ? page.map((topic, i) =>
    `<button type="button" class="ai-topic" style="--i:${i}" data-topic="${esc(topic)}" aria-pressed="${topic === aiTopic}">${esc(topic)}</button>`).join("")
    : '<p class="hint">Библиотека тем не найдена. Опишите свою нишу ниже.</p>';
  $("#ai-more").hidden = list.length <= AI_PAGE;
}

function chooseNiche(name) {
  aiNiche = name;
  aiStore.set("niche", name);
  renderNiches(); renderTopics();
}

$("#ai-niches").onclick = e => { const button = e.target.closest("[data-niche]"); if (button) chooseNiche(button.dataset.niche); };
$("#ai-more").onclick = () => {
  const offsets = aiStore.get("offsets", {});
  offsets[aiNiche] = ((offsets[aiNiche] || 0) + AI_PAGE) % Math.max(1, (aiLibrary[aiNiche] || []).length);
  aiStore.set("offsets", offsets);
  renderTopics();
};

// Своя ниша: запрос к ИИ (повтор того же запроса сервер отдаёт из кэша бесплатно).
$("#ai-form").onsubmit = async e => {
  e.preventDefault();
  const query = $("#ai-query").value.trim();
  if (aiBusy || !query) return $("#ai-query").focus();
  setAiBusy(true); aiStatus("Придумываю темы…");
  try {
    const result = await aiPost("/api/assistant/topics", {query, lang: val("lang")});
    aiLibrary = {[query]: result.topics, ...aiLibrary};
    $("#ai-query").value = "";
    chooseNiche(query);
    aiStatus((result.cached ? "Взято из сохранённых ответов, бесплатно. " : "") + aiQuotaText());
  } catch (error) { aiStatus(error.message, true); }
  finally { setAiBusy(false); }
};

async function aiDraft(topic, fresh = false) {
  if (aiBusy) return;
  aiTopic = topic; aiRewrites = fresh ? aiRewrites + 1 : 0;
  renderTopics();
  setAiBusy(true); aiStatus(fresh ? "Переписываю сценарий…" : `Пишу сценарий на ${mins()} мин…`);
  try {
    const draft = await aiPost("/api/assistant/script", {topic, lang: val("lang"), minutes: mins(), fresh});
    showDraft(topic, draft.script);
    aiStore.set("draft", {topic, script: draft.script});
    aiStatus((draft.cached ? "Сценарий взят из сохранённых, бесплатно. " : "") + aiQuotaText());
    $("#ai-draft").scrollIntoView({block: "nearest", behavior: "smooth"});
  } catch (error) { aiStatus(error.message, true); }
  finally { setAiBusy(false); updateRewrites(); }
}
function showDraft(topic, script) {
  aiTopic = topic;
  $("#ai-draft-topic").textContent = topic;
  $("#ai-script").value = script;
  $("#ai-draft").hidden = false;
  updateRewrites();
}
function updateRewrites() {
  const left = AI_REWRITES - aiRewrites;
  $("#ai-rewrite").disabled = aiBusy || left <= 0;
  $("#ai-rewrites").textContent = left > 0 ? `ещё ${left}` : "лимит переписываний";
}
$("#ai-topics").onclick = e => { const topic = e.target.closest("[data-topic]"); if (topic) aiDraft(topic.dataset.topic); };
$("#ai-rewrite").onclick = () => aiDraft(aiTopic, true);
$("#ai-script").oninput = () => aiStore.set("draft", {topic: aiTopic, script: $("#ai-script").value});

function setIdeaTab(name) {
  const script = name === "script";
  $("#tab-idea").setAttribute("aria-selected", String(!script));
  $("#tab-script").setAttribute("aria-selected", String(script));
  $("#idea-panel").hidden = script;
  $("#script-field").hidden = !script;
}
$("#tab-idea").onclick = () => setIdeaTab("idea");
$("#tab-script").onclick = () => { setIdeaTab("script"); $("#script").focus(); };

function setAssistantOpen(open, note) {
  $("#ai-body").hidden = !open;
  $("#ai-toggle").textContent = open ? "Пропустить" : "Открыть";
  $("#ai-toggle").setAttribute("aria-expanded", String(open));
  $("#ai-sub").textContent = note || "Выберите нишу и тему — сценарий напишу сам";
  $("#assistant").classList.toggle("collapsed", !open);
  aiStore.set("open", open);
}
$("#ai-use").onclick = () => {
  const script = $("#ai-script").value.trim();
  if (!script) return $("#ai-script").focus();
  $("#topic").value = aiTopic.slice(0, 200);
  $("#script").value = script;
  setIdeaTab("script");
  setAssistantOpen(false, `✓ Сценарий «${aiTopic}» перенесён в форму ниже`);
  $("#h-idea").scrollIntoView({block: "start", behavior: "smooth"});
};
$("#ai-toggle").onclick = () => {
  const open = $("#ai-body").hidden;
  setAssistantOpen(open, open ? "" : "Свёрнут — впишите идею или свой сценарий ниже");
  if (!open) $("#topic").focus();
};

async function setupAssistant() {
  aiLibrary = await fetch("/data/topics.json").then(r => r.ok ? r.json() : {}).catch(() => ({}));
  const saved = aiStore.get("niche", "");
  chooseNiche(aiLibrary[saved] ? saved : Object.keys(aiLibrary)[0] || "");
  const draft = aiStore.get("draft", null);
  if (draft?.script) showDraft(draft.topic, draft.script);
  if (aiStore.get("open", true) === false) setAssistantOpen(false, "Свёрнут — откройте, чтобы подобрать тему");
}
setupAssistant();
