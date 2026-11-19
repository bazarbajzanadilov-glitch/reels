/*
 * Редактор сценария и действия с job.
 * API: GET /api/jobs/:id/script, POST /api/jobs/:id/{script,render,trash,retry,cancel}.
 * editingJob/editingScript — локальное состояние модалки до сохранения.
 */
async function postJob(id,action,data={}) {
  const response=await fetch(`/api/jobs/${id}/${action}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
  const result=await response.json();
  if (!response.ok || result.error) throw new Error(result.error||"Операция не выполнена");
  return result;
}

// Подтверждение в собственном диалоге: возвращает true, если пользователь согласился.
function confirmAction(title,text,ok) {
  const dialog=$("#confirm-dialog");
  $("#confirm-title").textContent=title; $("#confirm-text").textContent=text; $("#confirm-ok").textContent=ok;
  return new Promise(resolve=>{
    const done=value=>{ dialog.onclose=null; dialog.close(); resolve(value); };
    $("#confirm-ok").onclick=()=>done(true);
    $("#confirm-cancel").onclick=()=>done(false);
    dialog.onclose=()=>resolve(false);
    dialog.showModal();
  });
}

async function deleteJob(id) {
  const job=jobs.find(j=>j.id===id);
  if (!job || !await confirmAction("Удалить ролик?",`«${job.title||job.topic}» переместится в корзину — его можно восстановить через фильтр «Корзина».`,"Удалить")) return false;
  await postJob(id,"trash");
  await load();
  return true;
}

$("#history-search").oninput=$("#history-status").onchange=()=>{historyVisible=48;renderHistory();};
$("#history-more").onclick=()=>{historyVisible+=48;renderHistory();};

let editingJob,editingScript;
async function openScript(job) {
  try {
    const response=await fetch(`/api/jobs/${job.id}/script`);
    const data=await response.json();
    if (!response.ok) throw new Error(data.error||"Сценарий недоступен");
    editingJob=job;editingScript=data;
    if (kit.open) kit.close();
    $("#script-title").value=data.title||job.topic;    $("#script-scenes").innerHTML=data.scenes.map((scene,i)=>`<section class="editor-scene" data-scene="${i}"><h3>Сцена ${i+1}</h3>
      <label>Текст озвучки<textarea data-field="text" maxlength="1200">${esc(scene.text)}</textarea></label>
      <label>Крупная подпись<input data-field="caption" maxlength="200" value="${esc(scene.caption)}"></label>
      <div class="scene-advanced"><label>Описание кадра <small>для генерации картинки, на английском</small><textarea data-field="image" maxlength="2400">${esc(scene.image)}</textarea></label>
      <label>Движение <small>для анимации, на английском</small><textarea data-field="motion" maxlength="1200">${esc(scene.motion)}</textarea></label></div></section>`).join("");
    $("#script-status").textContent="";
    $("#script-dialog").showModal();
    $(".editor-body").scrollTop=0;
  } catch(error) { $("#err").textContent=error.message; }
}
$("#script-advanced").onchange=()=>$("#script-scenes").classList.toggle("show-advanced",$("#script-advanced").checked);
$("#script-close").onclick=()=>$("#script-dialog").close();
async function saveScript(start) {
  const button=$(start?"#script-render":"#script-save");
  if (button.disabled) return;button.disabled=true;
  try {
    const scenes=[...document.querySelectorAll("#script-scenes [data-scene]")].map((node,i)=>({...editingScript.scenes[i],...Object.fromEntries([...node.querySelectorAll("[data-field]")].map(input=>[input.dataset.field,input.value]))}));
    const saved=await postJob(editingJob.id,start?"render":"script",{title:$("#script-title").value,scenes});
    $("#script-status").textContent=start?"":"Сценарий сохранён";
    await load();
    if (start) {
      $("#script-dialog").close();
      if (!jobs.some(j=>j.id===saved.id)) jobs.unshift(saved);
      openKit(saved.id);
    }
  } catch(error) { $("#script-status").textContent=error.message; }
  finally { button.disabled=false; }
}
$("#script-save").onclick=()=>saveScript(false);$("#script-render").onclick=()=>saveScript(true);
$("#script-trash").onclick=async()=>{
  try { if (await deleteJob(editingJob.id)) $("#script-dialog").close(); }
  catch(error) { $("#script-status").textContent=error.message; }
};
