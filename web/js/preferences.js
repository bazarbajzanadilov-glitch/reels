/*
 * localStorage-схема "factory.preferences" (версия не хранится, поля читаются
 * защитно). При React-порте заменяется на controlled form + persist middleware.
 */
function preferenceData() {
  return {custom_style:$("#custom-style").value,custom_genre:$("#custom-genre").value,radios:Object.fromEntries([...document.querySelectorAll('.panel input[type="radio"]:checked, .panel select[name]')].map(input=>[input.name,input.value])),voice:$("#voice").value,minutes:mins(),clips:$("#clips").value,clipsTouched,voiceSpeed:$("#voice-speed").value,channelName:$("#channel-name").value,maxprice:$("#maxprice").value,review:$("#review-script").checked,subtitles:subtitleSettings()};
}
function restorePreferences() {
  let value;try { value=JSON.parse(localStorage.getItem("factory.preferences")||"null"); } catch { return; }
  if (!value || typeof value!=="object") return;
  for (const [name,choice] of Object.entries(value.radios||{})) { const els=[...document.getElementsByName(name)]; const sel=els.find(el=>el.tagName==="SELECT"); if (sel) { if ([...sel.options].some(o=>o.value===choice)) sel.value=choice; continue; } const input=els.find(input=>input.value===choice);if (input) input.checked=true; }
  $("#custom-style").value=typeof value.custom_style==="string"?value.custom_style:"";
  $("#custom-genre").value=typeof value.custom_genre==="string"?value.custom_genre:"";
  voices();if ([...$("#voice").options].some(option=>option.value===value.voice)) $("#voice").value=value.voice;
  if (Number.isFinite(value.minutes)) { $("#minutes").value=value.minutes;setMins(mins()); }
  if (value.clipsTouched && value.clips) { clipsTouched=true; $("#clips").value=value.clips; }
  if (value.voiceSpeed) { $("#voice-speed").value=value.voiceSpeed; $("#voice-speed").dispatchEvent(new Event("input")); }
  if (typeof value.channelName==="string") $("#channel-name").value=value.channelName;
  if (typeof value.maxprice==="string" && value.maxprice) $("#maxprice").value=value.maxprice;
  $("#review-script").checked=value.review!==false;
  if (value.subtitles) applySubtitlePreset(value.subtitles);
}
document.addEventListener("change",event=>{
  if (event.target.closest('.panel') && event.target.id!=="notes" || event.target.id==="review-script") {
    try { localStorage.setItem("factory.preferences",JSON.stringify(preferenceData())); } catch {}
  }
});
