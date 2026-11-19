/*
 * Субтитры: DOM-поля #subtitle-* — единственный source of truth.
 * subtitleSettings() собирает plain object для API, localStorage и React-порта.
 * Превью рендерит сервер на настоящем кадре; готовые картинки кэшируются по настройкам,
 * поэтому возврат к прежнему оформлению не делает запрос.
 */
const SUBTITLE_PALETTES = {
  bright: ["#ffffff", "#ffd166", "#62e6b5", "#7cc8ff", "#ff92c2"],
  pastel: ["#fff1b8", "#b8f0dd", "#c9deff", "#edcaff", "#ffd1dc"],
  warm: ["#fff4d6", "#ffd166", "#ffaf75", "#ff8494", "#ffe29a"],
};
const SUBTITLE_PREVIEW_CACHE = new Map();
let subtitlePage = 0, subtitleTimer, subtitleController;
function subtitleSettings() {
  const get = name => $("#subtitle-" + name).value;
  return {mode:get("mode"), color:get("color"), palette:[...document.querySelectorAll("[data-sub-color]")].map(i => i.value),
    size:+get("size"), position:+get("position"), width:+get("width"), words:+get("words"), spacing:+get("spacing"),
    outline:+get("outline"), outline_color:get("outline-mode") === "auto" ? "auto" : get("outline-color"),
    timing:get("timing"), background:+get("background"), uppercase:$("#subtitle-uppercase").checked, show_captions:$("#subtitle-captions").checked};
}
function updateSubtitleControls() {
  for (const id of ["subtitle-preset","subtitle-outline-mode","subtitle-timing"]) syncChoiceButtons($("#"+id));
  const settings = subtitleSettings();
  $("#subtitle-editor").hidden = settings.mode === "off";
  $("#subtitle-single").hidden = settings.mode !== "single";
  $("#subtitle-palette-settings").hidden = settings.mode !== "cycle";
  $("#subtitle-outline-swatch").hidden = settings.outline_color === "auto";
  document.querySelectorAll("[data-sub-position]").forEach(b => b.setAttribute("aria-pressed", String(+b.dataset.subPosition === settings.position)));
  refreshSliders();
  refreshSwatches();
  clearTimeout(subtitleTimer);
  subtitleController?.abort();
  if (settings.mode !== "off") subtitleTimer = setTimeout(previewSubtitles, 300);
}
async function previewSubtitles() {
  subtitleController?.abort();
  const controller = subtitleController = new AbortController();
  const horizontal = val("format") === "horizontal";
  const body = JSON.stringify({subtitles:subtitleSettings(), format:val("format"), page:subtitlePage, width:horizontal ? 960 : 540});
  const frame = $("#subtitle-frame"), image = $("#subtitle-preview");
  frame.classList.toggle("h", horizontal);
  let url = SUBTITLE_PREVIEW_CACHE.get(body);
  if (!url) {
    frame.classList.add("loading");
    try {
      const response = await fetch("/api/subtitles/preview", {method:"POST", signal:controller.signal, headers:{"Content-Type":"application/json"}, body});
      if (!response.ok) throw new Error("preview");
      url = URL.createObjectURL(await response.blob());
      SUBTITLE_PREVIEW_CACHE.set(body, url);
      if (SUBTITLE_PREVIEW_CACHE.size > 40) { const [oldest, old] = SUBTITLE_PREVIEW_CACHE.entries().next().value; URL.revokeObjectURL(old); SUBTITLE_PREVIEW_CACHE.delete(oldest); }
    } catch (error) {
      if (error.name !== "AbortError") { frame.classList.remove("loading"); $("#subtitle-preview-status").textContent = "Пример не загрузился"; }
      return;
    }
  }
  if (controller.signal.aborted) return;
  image.src = url;
  frame.classList.remove("loading");
  $("#subtitle-preview-status").textContent = "Блок " + (subtitlePage + 1);
}
$("#subtitle-mode").onchange = () => { subtitlePage = 0; updateSubtitleControls(); };
document.querySelectorAll(".subtitle-editor input, .subtitle-editor select").forEach(input => {
  input.addEventListener("input", () => { if (input.hasAttribute("data-sub-color")) $("#subtitle-preset").value = "custom"; updateSubtitleControls(); });
  input.addEventListener("change", updateSubtitleControls);
});
$("#subtitle-preset").onchange = () => {
  const colors = SUBTITLE_PALETTES[$("#subtitle-preset").value];
  if (colors) document.querySelectorAll("[data-sub-color]").forEach((input, i) => input.value = colors[i]);
  updateSubtitleControls();
};
document.querySelectorAll("[data-sub-position]").forEach(b => b.onclick = () => {
  $("#subtitle-position").value = b.dataset.subPosition; updateSubtitleControls();
});
$("#subtitle-next").onclick = () => { subtitlePage += 1; previewSubtitles(); };
$("#subtitle-prev").onclick = () => { subtitlePage = Math.max(0, subtitlePage - 1); previewSubtitles(); };
$("#subtitle-reset").onclick = () => {
  for (const [name, value] of Object.entries({color:"#ffffff", size:54, position:78, width:86, words:10, spacing:1.2, outline:2, background:0, "outline-mode":"auto", "outline-color":"#101014", preset:"bright", timing:"phrase"})) {
    $("#subtitle-" + name).value = value;
  }
  $("#subtitle-uppercase").checked = $("#subtitle-captions").checked = false;
  document.querySelectorAll("[data-sub-color]").forEach((input,i) => input.value = SUBTITLE_PALETTES.bright[i]);
  subtitlePage = 0; updateSubtitleControls();
};
document.querySelectorAll('input[name="format"]').forEach(input => input.addEventListener("change", updateSubtitleControls));

// «Мои оформления» хранятся в браузере и показываются чипсами: клик — применить, × — удалить.
function storedPresets() { try { return JSON.parse(localStorage.getItem("factory.subtitle-presets")||"{}"); } catch { return {}; } }
function writePresets(presets) { localStorage.setItem("factory.subtitle-presets",JSON.stringify(presets)); updatePresets(); }
function updatePresets() {
  const names = Object.keys(storedPresets());
  $("#subtitle-saved-list").innerHTML = names.length ? names.map(name=>`<span class="chip" role="button" tabindex="0" data-preset="${esc(name)}">${esc(name)}<button type="button" data-remove="${esc(name)}" aria-label="Удалить оформление ${esc(name)}">×</button></span>`).join("") : '<span class="hint">Сохраните текущие настройки, чтобы быстро применять их к новым роликам.</span>';
}
function applySubtitlePreset(settings) {
  for (const name of ["mode","color","size","position","width","words","spacing","outline","background","timing"]) if (settings[name]!=null) $("#subtitle-"+name).value=settings[name];
  $("#subtitle-outline-mode").value=settings.outline_color==="auto"?"auto":"custom";
  if (settings.outline_color!=="auto") $("#subtitle-outline-color").value=settings.outline_color;
  $("#subtitle-uppercase").checked=!!settings.uppercase;$("#subtitle-captions").checked=!!settings.show_captions;
  if (settings.palette) document.querySelectorAll("[data-sub-color]").forEach((input,i)=>input.value=settings.palette[i%settings.palette.length]);
  $("#subtitle-mode").dispatchEvent(new Event("change"));
}
$("#subtitle-saved-list").onclick = e => {
  const presets = storedPresets(), remove = e.target.closest("[data-remove]")?.dataset.remove;
  try {
    if (remove != null) { delete presets[remove]; writePresets(presets); $("#subtitle-preset-status").textContent = "Оформление удалено"; return; }
  } catch { $("#subtitle-preset-status").textContent = "Браузер запретил сохранение"; return; }
  const name = e.target.closest("[data-preset]")?.dataset.preset;
  if (name != null && Object.hasOwn(presets, name)) { applySubtitlePreset(presets[name]); $("#subtitle-preset-status").textContent = `Применено «${name}»`; }
};
$("#subtitle-saved-list").onkeydown = e => { if ((e.key === "Enter" || e.key === " ") && e.target.dataset.preset) { e.preventDefault(); e.target.click(); } };
$("#subtitle-save-preset").onclick=()=>{
  const name=$("#subtitle-preset-name").value.trim();if (!name) { $("#subtitle-preset-status").textContent="Введите название оформления";return; }
  const presets=storedPresets();if (!Object.hasOwn(presets,name)&&Object.keys(presets).length>=20) { $("#subtitle-preset-status").textContent="Можно сохранить до 20 оформлений";return; }
  try { Object.defineProperty(presets,name,{value:subtitleSettings(),enumerable:true,writable:true,configurable:true});writePresets(presets);$("#subtitle-preset-name").value="";$("#subtitle-preset-status").textContent="Сохранено на этом устройстве"; }
  catch { $("#subtitle-preset-status").textContent="Браузер запретил сохранение"; }
};
updatePresets();
