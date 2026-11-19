"use strict";

/*
 * Подбор темы на шаге «Создание». Только готовая библиотека (/data/topics.json, 20 ниш × 100 тем):
 * листание, поиск и выбор ничего не генерируют. Платная генерация начинается лишь с «Создать ролик».
 */
const AI_PAGE = 6;
let aiLibrary = {}, aiNiche = "";

const aiStore = {
  get(name, fallback) { try { return JSON.parse(localStorage.getItem("factory.ai." + name)) ?? fallback; } catch { return fallback; } },
  set(name, value) { try { localStorage.setItem("factory.ai." + name, JSON.stringify(value)); } catch { /* только удобство */ } },
};

function renderNiches() {
  $("#ai-niches").innerHTML = Object.keys(aiLibrary).map(name =>
    `<button type="button" data-niche="${esc(name)}" aria-pressed="${name === aiNiche}">${esc(name)}</button>`).join("");
}

function topicButtons(list) {
  const chosen = $("#topic").value.trim();
  return list.map((topic, i) => `<button type="button" class="ai-topic" style="--i:${i}" data-topic="${esc(topic)}" aria-pressed="${topic === chosen}">${esc(topic)}</button>`).join("");
}

function renderTopics() {
  const query = $("#ai-query").value.trim().toLocaleLowerCase();
  if (query) {
    const found = Object.values(aiLibrary).flat().filter(t => t.toLocaleLowerCase().includes(query)).slice(0, 12);
    $("#ai-niche-title").textContent = found.length ? `Найдено: ${found.length}${found.length === 12 ? "+" : ""}` : "Ничего не нашлось — попробуйте другое слово";
    $("#ai-topics").innerHTML = topicButtons(found);
    $("#ai-more").hidden = true;
    return;
  }
  const list = aiLibrary[aiNiche] || [], offsets = aiStore.get("offsets", {});
  const start = (offsets[aiNiche] || 0) % Math.max(1, list.length);
  const page = Array.from({length: Math.min(AI_PAGE, list.length)}, (_, i) => list[(start + i) % list.length]);
  $("#ai-niche-title").textContent = aiNiche ? `${aiNiche} · ${list.length} тем` : "Библиотека тем не загрузилась";
  $("#ai-topics").innerHTML = topicButtons(page);
  $("#ai-more").hidden = list.length <= AI_PAGE;
}

function chooseNiche(name) {
  aiNiche = name;
  aiStore.set("niche", name);
  $("#ai-query").value = "";
  renderNiches(); renderTopics();
  $("#ai-niches").querySelector('[aria-pressed="true"]')?.scrollIntoView({block: "nearest", inline: "nearest", behavior: "smooth"});
}

$("#ai-niches").onclick = e => { const button = e.target.closest("[data-niche]"); if (button) chooseNiche(button.dataset.niche); };
$("#ai-more").onclick = () => {
  const offsets = aiStore.get("offsets", {});
  offsets[aiNiche] = ((offsets[aiNiche] || 0) + AI_PAGE) % Math.max(1, (aiLibrary[aiNiche] || []).length);
  aiStore.set("offsets", offsets);
  renderTopics();
};
$("#ai-query").oninput = renderTopics;
$("#ai-topics").onclick = e => {
  const topic = e.target.closest("[data-topic]")?.dataset.topic;
  if (!topic) return;
  $("#topic").value = topic.slice(0, 200);
  setIdeaTab("idea");
  renderTopics();
  $("#ai-status").textContent = `✓ «${topic}» — идея ролика. Настройте параметры ниже и нажмите «Создать ролик».`;
};

function setIdeaTab(name) {
  const script = name === "script";
  $("#tab-idea").setAttribute("aria-selected", String(!script));
  $("#tab-script").setAttribute("aria-selected", String(script));
  $("#idea-panel").hidden = script;
  $("#script-field").hidden = !script;
}
$("#tab-idea").onclick = () => setIdeaTab("idea");
$("#tab-script").onclick = () => { setIdeaTab("script"); $("#script").focus(); };

function setAssistantOpen(open) {
  $("#ai-body").hidden = !open;
  $("#ai-toggle").textContent = open ? "Пропустить" : "Открыть";
  $("#ai-toggle").setAttribute("aria-expanded", String(open));
  $("#ai-sub").textContent = open ? "2 000 готовых тем по 20 нишам — бесплатно" : "Свёрнуто — откройте, чтобы подобрать тему";
  $("#assistant").classList.toggle("collapsed", !open);
  aiStore.set("open", open);
}
$("#ai-toggle").onclick = () => {
  const open = $("#ai-body").hidden;
  setAssistantOpen(open);
  if (!open) $("#topic").focus();
};

async function setupAssistant() {
  aiLibrary = await fetch("/data/topics.json", {cache: "no-cache"}).then(r => r.ok ? r.json() : {}).catch(() => ({}));
  const saved = aiStore.get("niche", "");
  chooseNiche(aiLibrary[saved] ? saved : Object.keys(aiLibrary)[0] || "");
  if (aiStore.get("open", true) === false) setAssistantOpen(false);
}
setupAssistant();
