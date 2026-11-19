"use strict";

/*
 * Чат с ИИ на шаге «Создание»: клиент переписывается с GPT или Claude, модель подкидывает идеи.
 * Строки-идеи из ответа («- …» или «1. …») становятся кнопками — нажатие кладёт идею в поле темы.
 * Запрос уходит только по «Отправить»; история хранится в браузере.
 */
const CHAT_MAX = 30;
let chatHistory = [], chatModel = "gpt", chatBusy = false;

const aiStore = {
  get(name, fallback) { try { return JSON.parse(localStorage.getItem("factory.ai." + name)) ?? fallback; } catch { return fallback; } },
  set(name, value) { try { localStorage.setItem("factory.ai." + name, JSON.stringify(value)); } catch { /* только удобство */ } },
};

const IDEA_LINE = /^\s*(?:[-•*–]|\d{1,2}[.)])\s+(.+)$/;
const plainIdea = s => s.replace(/\*\*|__|`/g, "").replace(/^[«"“]+|[»"”]+$/g, "").trim();

// Ответ модели → абзацы и список идей-кнопок. Текст экранируется, разметку не исполняем.
function messageHtml(text) {
  const chosen = $("#topic").value.trim();
  const blocks = [];
  let list = null, para = [];
  const flush = () => { if (para.length) { blocks.push(`<p>${para.map(l => esc(l.replace(/\*\*/g, ""))).join("<br>")}</p>`); para = []; } };
  for (const line of String(text).split(/\r?\n/)) {
    const m = line.match(IDEA_LINE);
    if (m && plainIdea(m[1])) {
      flush();
      if (!list) { list = []; blocks.push(list); }
      list.push(plainIdea(m[1]));
    } else {
      list = null;
      if (line.trim()) para.push(line.trim()); else flush();
    }
  }
  flush();
  return blocks.map(b => Array.isArray(b)
    ? `<div class="chat-ideas">${b.map(idea => `<button type="button" class="ai-topic" data-topic="${esc(idea)}" aria-pressed="${idea === chosen}"><span>${esc(idea)}</span><small>Взять</small></button>`).join("")}</div>`
    : b).join("");
}

function renderChat() {
  const log = $("#chat-log");
  log.innerHTML = chatHistory.map(m => m.role === "user"
    ? `<div class="msg user"><p>${esc(m.content)}</p></div>`
    : `<div class="msg bot"><span class="msg-who">${esc(m.model || "ИИ")}</span>${messageHtml(m.content)}</div>`).join("")
    + (chatBusy ? `<div class="msg bot typing" aria-label="ИИ печатает"><i></i><i></i><i></i></div>` : "");
  log.hidden = !chatHistory.length && !chatBusy;
  $("#chat-starters").hidden = chatHistory.length > 0;
  log.scrollTop = log.scrollHeight;
}

function renderModels() {
  const models = OPT?.chat_models || {gpt: "GPT", claude: "Claude"};
  if (!models[chatModel]) chatModel = Object.keys(models)[0];
  $("#chat-models").innerHTML = Object.entries(models).map(([k, label]) =>
    `<button type="button" data-model="${esc(k)}" aria-pressed="${k === chatModel}">${esc(label)}</button>`).join("");
}

async function sendChat(text) {
  text = String(text || "").trim();
  if (!text || chatBusy) return;
  chatHistory.push({role: "user", content: text.slice(0, 4000)});
  chatHistory = chatHistory.slice(-CHAT_MAX);
  $("#chat-input").value = ""; fitChatInput();
  chatBusy = true; $("#chat-send").disabled = true;
  $("#ai-status").classList.remove("error");
  renderChat();
  const label = OPT?.chat_models?.[chatModel] || chatModel;
  try {
    const response = await fetch("/api/chat", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({model: chatModel, messages: chatHistory.map(({role, content}) => ({role, content}))})});
    const r = await response.json().catch(() => ({}));
    if (!response.ok || !r.reply) throw new Error(r.error || (response.status === 429 ? "Слишком много сообщений. Подождите минуту" : "Не удалось получить ответ"));
    chatHistory.push({role: "assistant", content: r.reply, model: label});
    $("#ai-status").textContent = "Нажмите на идею в ответе — она станет темой ролика.";
  } catch (error) {
    chatHistory.pop();
    $("#chat-input").value = text; fitChatInput();
    $("#ai-status").textContent = error.message || "Нет связи с сервером";
    $("#ai-status").classList.add("error");
  } finally {
    chatBusy = false; $("#chat-send").disabled = false;
    aiStore.set("chat", chatHistory);
    renderChat();
  }
}

function fitChatInput() {
  const input = $("#chat-input");
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

$("#chat-form").onsubmit = e => { e.preventDefault(); sendChat($("#chat-input").value); };
$("#chat-input").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendChat(e.target.value); } };
$("#chat-input").oninput = fitChatInput;
$("#chat-starters").onclick = e => { const b = e.target.closest("button"); if (b) sendChat(b.textContent); };
$("#chat-models").onclick = e => {
  const b = e.target.closest("[data-model]");
  if (!b) return;
  chatModel = b.dataset.model; aiStore.set("model", chatModel); renderModels();
};
$("#chat-clear").onclick = () => { if (chatBusy) return; chatHistory = []; aiStore.set("chat", []); renderChat(); $("#chat-input").focus(); };
$("#chat-log").onclick = e => {
  const topic = e.target.closest("[data-topic]")?.dataset.topic;
  if (!topic) return;
  $("#topic").value = topic.slice(0, 200);
  setIdeaTab("idea");
  renderChat();
  $("#ai-status").classList.remove("error");
  $("#ai-status").textContent = `✓ «${topic.slice(0, 200)}» — идея ролика. Настройте параметры ниже и нажмите «Создать ролик».`;
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
  $("#ai-toggle").textContent = open ? "Свернуть" : "Открыть";
  $("#ai-toggle").setAttribute("aria-expanded", String(open));
  $("#ai-sub").textContent = open ? "Обсудите идею — ИИ подкинет темы для ролика" : "Свёрнуто — откройте, чтобы обсудить идею с ИИ";
  $("#assistant").classList.toggle("collapsed", !open);
  aiStore.set("open", open);
}
$("#ai-toggle").onclick = () => {
  const open = $("#ai-body").hidden;
  setAssistantOpen(open);
  if (open) $("#chat-input").focus(); else $("#topic").focus();
};

function setupAssistant() {
  const saved = aiStore.get("chat", []);
  chatHistory = Array.isArray(saved) ? saved.filter(m => m && ["user", "assistant"].includes(m.role) && typeof m.content === "string").slice(-CHAT_MAX) : [];
  chatModel = aiStore.get("model", "gpt");
  renderModels(); renderChat();
  if (aiStore.get("open", true) === false) setAssistantOpen(false);
  // список моделей приходит с /api/options — перерисуем, когда он загрузится
  const wait = setInterval(() => { if (OPT) { clearInterval(wait); renderModels(); } }, 200);
  setTimeout(() => clearInterval(wait), 15000);
}
setupAssistant();
