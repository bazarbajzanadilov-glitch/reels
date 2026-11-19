const SUBTITLE_PALETTES = {
  bright: ["#ffffff", "#ffd166", "#62e6b5", "#7cc8ff", "#ff92c2"],
  pastel: ["#fff1b8", "#b8f0dd", "#c9deff", "#edcaff", "#ffd1dc"],
  warm: ["#fff4d6", "#ffd166", "#ffaf75", "#ff8494", "#ffe29a"],
};
let subtitlePage = 0, subtitleTimer, subtitleController, subtitlePreviewURL;
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
  $("#subtitle-outline-color").hidden = settings.outline_color === "auto";
  for (const name of ["size", "position", "width", "words", "spacing", "outline", "background"]) {
    $("#subtitle-" + name + "-value").textContent = settings[name] + (["position", "width", "background"].includes(name) ? "%" : "");
  }
  document.querySelectorAll("[data-sub-position]").forEach(b => b.classList.toggle("on", +b.dataset.subPosition === settings.position));
  clearTimeout(subtitleTimer);
  subtitleController?.abort();
  if (settings.mode !== "off") subtitleTimer = setTimeout(previewSubtitles, 180);
}
async function previewSubtitles() {
  subtitleController?.abort();
  const controller = subtitleController = new AbortController();
  $("#subtitle-preview-status").textContent = "Обновляю пример…";
  const previewWidth = Math.ceil($("#subtitle-preview").getBoundingClientRect().width * Math.min(window.devicePixelRatio || 1, 2));
  try {
    const response = await fetch("/api/subtitles/preview", {method:"POST", signal:controller.signal,
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({subtitles:subtitleSettings(), format:val("format"), page:subtitlePage, width:previewWidth})});
    if (!response.ok) throw new Error("preview");
    const blob = await response.blob();
    if (controller.signal.aborted) return;
    const previous = subtitlePreviewURL;
    subtitlePreviewURL = URL.createObjectURL(blob);
    const image = $("#subtitle-preview");
    image.src = subtitlePreviewURL;
    image.width = val("format") === "horizontal" ? 640 : 360;
    image.height = val("format") === "horizontal" ? 360 : 640;
    if (previous) URL.revokeObjectURL(previous);
    $("#subtitle-preview-status").textContent = "Бесплатный пример · блок " + (subtitlePage + 1);
  } catch (error) {
    if (error.name !== "AbortError") $("#subtitle-preview-status").textContent = "Не удалось загрузить пример. Измените настройку, чтобы повторить.";
  }
}
$("#subtitle-mode").onchange = () => { subtitlePage = 0; updateSubtitleControls(); };
document.querySelectorAll(".subtitle-editor input, .subtitle-editor select").forEach(input => {
  input.oninput = () => { if (input.hasAttribute("data-sub-color")) $("#subtitle-preset").value = "custom"; updateSubtitleControls(); };
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
$("#subtitle-reset").onclick = () => {
  for (const [name, value] of Object.entries({color:"#ffffff", size:54, position:78, width:86, words:10, spacing:1.2, outline:2, background:0, "outline-mode":"auto", "outline-color":"#101014", preset:"bright", timing:"phrase"})) {
    $("#subtitle-" + name).value = value;
  }
  $("#subtitle-uppercase").checked = $("#subtitle-captions").checked = false;
  document.querySelectorAll("[data-sub-color]").forEach((input,i) => input.value = SUBTITLE_PALETTES.bright[i]);
  subtitlePage = 0; updateSubtitleControls();
};
document.querySelectorAll('input[name="format"]').forEach(input => input.addEventListener("change", updateSubtitleControls));
updateSubtitleControls();

let subtitleResizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(subtitleResizeTimer);
  if ($("#subtitle-mode").value !== "off") subtitleResizeTimer = setTimeout(previewSubtitles, 240);
});



function storedPresets() { try { return JSON.parse(localStorage.getItem("factory.subtitle-presets")||"{}"); } catch { return {}; } }
function updatePresets() { $("#subtitle-saved").innerHTML='<option value="">Выбрать…</option>'+Object.keys(storedPresets()).map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join(""); }
function applySubtitlePreset(settings) {
  for (const name of ["mode","color","size","position","width","words","spacing","outline","background","timing"]) if (settings[name]!=null) $("#subtitle-"+name).value=settings[name];
  $("#subtitle-outline-mode").value=settings.outline_color==="auto"?"auto":"custom";
  if (settings.outline_color!=="auto") $("#subtitle-outline-color").value=settings.outline_color;
  $("#subtitle-uppercase").checked=!!settings.uppercase;$("#subtitle-captions").checked=!!settings.show_captions;
  if (settings.palette) document.querySelectorAll("[data-sub-color]").forEach((input,i)=>input.value=settings.palette[i%settings.palette.length]);
  updateSubtitleControls();
}
$("#subtitle-save-preset").onclick=()=>{
  const name=$("#subtitle-preset-name").value.trim();if (!name) { $("#subtitle-preset-status").textContent="Введите название оформления";return; }
  const presets=storedPresets();if (!Object.hasOwn(presets,name)&&Object.keys(presets).length>=20) { $("#subtitle-preset-status").textContent="Можно сохранить до 20 оформлений";return; }
  try { Object.defineProperty(presets,name,{value:subtitleSettings(),enumerable:true,writable:true,configurable:true});localStorage.setItem("factory.subtitle-presets",JSON.stringify(presets));updatePresets();$("#subtitle-saved").value=name;$("#subtitle-preset-status").textContent="Сохранено на этом устройстве"; }
  catch { $("#subtitle-preset-status").textContent="Браузер запретил сохранение"; }
};
$("#subtitle-saved").onchange=()=>{const preset=storedPresets()[$("#subtitle-saved").value];if (preset) applySubtitlePreset(preset);};
$("#subtitle-delete-preset").onclick=()=>{const presets=storedPresets();delete presets[$("#subtitle-saved").value];try{localStorage.setItem("factory.subtitle-presets",JSON.stringify(presets));updatePresets();}catch{}};
updatePresets();

