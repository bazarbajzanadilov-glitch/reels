"use strict";

/*
 * Общие элементы управления: слайдер с пилюлей значения и свотчи цвета со своим окном выбора.
 * Исходные <input type=range|number|color> остаются источником значения для остального кода.
 */

// ---------- Слайдеры ----------
// data-suffix / data-decimals — формат пилюли; data-of — «4 из 10»;
// data-prefix — знак перед числом ($); data-source="number" — значение хранит скрытое числовое поле (#minutes, #clips, #maxprice), иначе сам range.
function sliderParts(slider) {
  const range = slider.querySelector("input[type=range]");
  let number = slider.querySelector(".slider-head input[type=number]");
  if (!number) {
    number = Object.assign(document.createElement("input"), {type: "number", hidden: true});
    number.setAttribute("aria-label", slider.querySelector("label")?.textContent + " — точное значение");
    slider.querySelector(".slider-head").append(number);
  }
  return {range, number, pill: slider.querySelector(".slider-value")};
}

function renderSlider(slider) {
  const {range, pill} = sliderParts(slider);
  const value = Number(range.value), min = Number(range.min), max = Number(range.max);
  range.style.setProperty("--fill", ((value - min) / ((max - min) || 1) * 100) + "%");
  const decimals = Number(slider.dataset.decimals || 0);
  const shown = slider.dataset.trim ? String(Number(value.toFixed(decimals))) : value.toFixed(decimals);
  pill.textContent = slider.dataset.of ? `${value} из ${max}` : (slider.dataset.prefix || "") + shown + (slider.dataset.suffix || "");
}
const refreshSliders = () => document.querySelectorAll(".slider").forEach(renderSlider);

function setupSliders() {
  document.querySelectorAll(".slider").forEach(slider => {
    const {range, number, pill} = sliderParts(slider);
    const close = commit => {
      if (number.hidden) return;
      if (commit) {
        const value = Math.min(Number(range.max), Math.max(Number(range.min), Number(number.value)));
        if (Number.isFinite(value)) {
          number.value = range.value = value;
          const target = slider.dataset.source === "number" ? number : range;
          target.dispatchEvent(new Event("input", {bubbles: true}));
          target.dispatchEvent(new Event("change", {bubbles: true}));
        }
      }
      number.hidden = true; pill.hidden = false;
      renderSlider(slider);
    };
    pill.onclick = () => {
      Object.assign(number, {min: range.min, max: range.max, step: range.step || 1, value: range.value});
      pill.hidden = true; number.hidden = false;
      number.focus(); number.select();
    };
    number.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); close(true); } if (e.key === "Escape") close(false); });
    number.addEventListener("blur", () => close(true));
    range.addEventListener("input", () => renderSlider(slider));
    range.addEventListener("pointerdown", () => slider.classList.add("dragging"));
    addEventListener("pointerup", () => slider.classList.remove("dragging"));
    renderSlider(slider);
  });
}

// ---------- Свотчи и окно цвета ----------
const COLOR_PRESETS = ["#ffffff", "#fff1b8", "#ffd166", "#ffaf75", "#ff8494", "#ff92c2", "#edcaff", "#c9deff", "#7cc8ff", "#62e6b5", "#b8f0dd", "#101014"];
let colorPop = null;

function closeColorPop() {
  colorPop?.remove(); colorPop = null;
  document.querySelectorAll(".swatch.open").forEach(s => s.classList.remove("open"));
}

function openColorPop(input, swatch) {
  const reopen = swatch.classList.contains("open");
  closeColorPop();
  if (reopen) return;
  swatch.classList.add("open");
  const pop = colorPop = document.createElement("div");
  pop.className = "color-pop";
  pop.setAttribute("role", "dialog");
  pop.setAttribute("aria-label", input.getAttribute("aria-label") || "Цвет");
  pop.innerHTML = `<div class="grid-colors">${COLOR_PRESETS.map(c => `<button type="button" data-color="${c}" style="background:${c}" aria-label="${c}"></button>`).join("")}</div>
    <div class="hex-row"><input type="text" maxlength="7" value="${input.value}" aria-label="Код цвета"><button type="button" class="btn sm main">Готово</button></div>`;
  const apply = value => {
    if (!/^#[0-9a-f]{6}$/i.test(value)) return;
    input.value = value.toLowerCase();
    input.dispatchEvent(new Event("input", {bubbles: true}));
    input.dispatchEvent(new Event("change", {bubbles: true}));
    refreshSwatches();
  };
  pop.onclick = e => {
    const color = e.target.closest("[data-color]")?.dataset.color;
    if (color) { apply(color); closeColorPop(); }
    if (e.target.closest(".btn")) { apply(pop.querySelector("input").value.trim()); closeColorPop(); }
  };
  pop.querySelector("input").onkeydown = e => { if (e.key === "Enter") { apply(e.target.value.trim()); closeColorPop(); } };
  document.body.append(pop);
  const box = swatch.getBoundingClientRect(), width = pop.offsetWidth;
  pop.style.top = (scrollY + box.bottom + 8) + "px";
  pop.style.left = Math.max(8, Math.min(scrollX + box.left, scrollX + innerWidth - width - 8)) + "px";
}

function refreshSwatches() {
  document.querySelectorAll(".swatch[data-for]").forEach(swatch => { swatch.style.background = document.getElementById(swatch.dataset.for).value; });
}

function setupSwatches() {
  document.querySelectorAll("input[type=color]").forEach((input, i) => {
    input.id ||= "color-" + i;
    const swatch = document.createElement("button");
    swatch.type = "button"; swatch.className = "swatch"; swatch.dataset.for = input.id;
    swatch.setAttribute("aria-label", input.getAttribute("aria-label") || "Выбрать цвет");
    const block = input.closest(".subtitle-palette") ? [...input.parentElement.querySelectorAll("input[type=color]")].indexOf(input) + 1 : 0;
    if (block) swatch.innerHTML = `<span>${block}</span>`;
    swatch.onclick = e => { e.stopPropagation(); openColorPop(input, swatch); };
    input.insertAdjacentElement("afterend", swatch);
  });
  document.addEventListener("click", e => { if (colorPop && !colorPop.contains(e.target)) closeColorPop(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeColorPop(); });
  refreshSwatches();
}
