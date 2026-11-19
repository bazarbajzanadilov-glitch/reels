"use strict";

/*
 * Экран прогресса. progressRequest защищает от гонок: ответы старого job
 * игнорируются. Веса этапов ниже дают примерную готовность до финального статуса.
 * При переносе на React это отдельный ProgressScreen с теми же stage-ключами.
 */
let progressId = null, progressScriptId = null, progressRequest = 0;
const stageNames = {script:"Сценарий",voice:"Озвучка",images:"Кадры",animation:"Анимация",render:"Монтаж",cover:"Обложка",texts:"Тексты"};
const stageStates = {waiting:"Ожидание",running:"Создаётся",done:"Готово",skipped:"Не выбрано",error:"Ошибка"};

function showProgress(id) {
  progressId=id; progressScriptId=null; progressRequest++;
  $("#create").hidden=true; $("#project-history").hidden=true; $("#progress-page").hidden=false;
  $("#progress-texts").innerHTML="<p>Появятся после создания сценария</p>";
  refreshProgress(); window.scrollTo({top:0,behavior:"smooth"});
}

async function progressScript(job) {
  if (progressScriptId===job.id || !(job.stages?.script?.state==="done" || ["draft","done"].includes(job.status))) return;
  progressScriptId=job.id; const request=++progressRequest;
  try {
    const response=await fetch(`/api/jobs/${job.id}/script`); if(!response.ok) throw Error();
    const data=await response.json(); if(request!==progressRequest || progressId!==job.id) return;
    const social=data.social||{}, yt=social.youtube||{}, ig=social.instagram||{}, tt=social.tiktok||{}, fb=social.facebook||{};
    const networks=[["YouTube",yt.title||data.title,yt.description,yt.tags],["Instagram",data.title,ig.caption,ig.hashtags],["TikTok",data.title,tt.caption,tt.hashtags],["Facebook",fb.title||data.title,fb.text,fb.hashtags]];
    $("#progress-texts").innerHTML=networks.map(([name,title,description,tags])=>`<details class="progress-network" ${name==="YouTube"?"open":""}><summary>${esc(name)}</summary><dl><dt>Заголовок</dt><dd>${esc(title||"—")}</dd><dt>Описание</dt><dd>${esc(description||"—")}</dd><dt>Теги</dt><dd>${esc(Array.isArray(tags)?tags.map(x=>"#"+x.replace(/^#/,"")).join(" "):tags||"—")}</dd></dl></details>`).join("");
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches && !sessionStorage.getItem("progress.revealed."+job.id)) {
      const nodes=[...$("#progress-texts").querySelectorAll("dd")], values=nodes.map(n=>n.textContent); nodes.forEach(n=>n.textContent="");
      let index=0, offset=0; const step=()=>{ if(progressId!==job.id || request!==progressRequest) return; if(index>=nodes.length){sessionStorage.setItem("progress.revealed."+job.id,"1"); return;} offset+=12; nodes[index].textContent=values[index].slice(0,offset); if(offset>=values[index].length){index++;offset=0;} requestAnimationFrame(step); }; requestAnimationFrame(step);
    }
  } catch { progressScriptId=null; }
}

function refreshProgress() {
  if (!progressId || $("#progress-page").hidden) return;
  const job=jobs.find(j=>j.id===progressId); if(!job) return;
  $("#progress-title").textContent=job.title||job.topic;
  $("#progress-message").textContent=job.status==="draft"?"Сценарий готов к проверке":job.status==="done"?"Ваш комплект готов":(job.progress||STATUS_LABELS[job.status]||"Ожидание");
  const stages=job.stages||{};
  const weights={script:8,voice:12,images:20,animation:25,render:25,cover:7,texts:3};
  let estimate=0; for(const [key,weight] of Object.entries(weights)){const s=stages[key]; if(s?.state==="done" || s?.state==="skipped" || (key==="animation" && job.animate==="none")) estimate+=weight; else if(s?.total) estimate+=weight*Math.min(1,s.completed/s.total);}
  $("#progress-estimate").textContent=job.status==="done"?"Готовность: 100%":Object.keys(stages).length?`Примерная готовность: ${Math.round(estimate)}%`:"";
  $("#progress-stages").innerHTML=Object.entries(stageNames).map(([key,label])=>{
    let stage=stages[key]||{state:job.status==="done"?"done":"waiting"};
    if(key==="animation" && job.animate==="none") stage={state:"skipped"};
    const count=stage.total?` ${stage.completed}/${stage.total}`:"";
    return `<div class="progress-stage ${esc(stage.state)}"><span class="stage-dot"></span><span><b>${label}</b><small>${stageStates[stage.state]||"Ожидание"}${count}</small></span></div>`;
  }).join("");
  const ready=job.status==="done", coverReady=ready||stages.cover?.state==="done", f=`/files/${job.id}/`;
  const stopped=["error","cancelled"].includes(job.status), indicator=stopped?"":'<span class="asset-spinner"></span>';
  const videoMarkup=ready?`<video controls playsinline poster="${f}cover.jpg" src="${f}video.mp4"></video><a class="btn" href="${f}video.mp4?download=1" download>Скачать MP4</a>`:`${indicator}<span>${stopped?"Не готово":job.status==="draft"?"После проверки сценария":"Ожидает монтажа"}</span>`;
  const coverMarkup=coverReady?`<img src="${f}cover.jpg" alt="Обложка ролика"><a class="btn" href="${f}cover.jpg?download=1" download>Скачать JPG</a>`:`${indicator}<span>${stopped?"Не готово":job.status==="draft"?"После проверки сценария":"Ожидает создания"}</span>`;
  if($("#progress-video").dataset.markup!==videoMarkup){ $("#progress-video").innerHTML=videoMarkup; $("#progress-video").dataset.markup=videoMarkup; }
  if($("#progress-cover").dataset.markup!==coverMarkup){ $("#progress-cover").innerHTML=coverMarkup; $("#progress-cover").dataset.markup=coverMarkup; }
  $("#progress-open").hidden=!ready; $("#progress-review").hidden=job.status!=="draft"; $("#progress-retry").hidden=!["error","cancelled"].includes(job.status);
  $("#progress-open").onclick=()=>openJob(job.id); $("#progress-review").onclick=()=>openScript(job); $("#progress-retry").onclick=()=>openJob(job.id);
  progressScript(job);
}
$("#progress-back").onclick=()=>document.querySelector('[data-worktab="create"]').click();
