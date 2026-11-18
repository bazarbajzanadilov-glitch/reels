async function postJob(id,action,data) {
  const response=await fetch(`/api/jobs/${id}/${action}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
  const result=await response.json();
  if (!response.ok || result.error) throw new Error(result.error||"Операция не выполнена");
  return result;
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
    if (dlg.open) dlg.close();
    $("#script-title").value=data.title||job.topic;
    $("#script-scenes").innerHTML=data.scenes.map((scene,i)=>`<section class="editor-scene" data-scene="${i}"><h3>Сцена ${i+1}</h3><label>Текст озвучки<textarea data-field="text" maxlength="1200">${esc(scene.text)}</textarea></label><label>Описание кадра<textarea data-field="image" maxlength="2400">${esc(scene.image)}</textarea></label><label>Движение<textarea data-field="motion" maxlength="1200">${esc(scene.motion)}</textarea></label><label>Крупная подпись<input data-field="caption" maxlength="200" value="${esc(scene.caption)}"></label></section>`).join("");
    $("#script-status").textContent="";
    $("#script-dialog").showModal();
  } catch(error) { $("#err").textContent=error.message; }
}
$("#edit-script").onclick=()=>openScript(cur);
$("#script-close").onclick=()=>$("#script-dialog").close();
async function saveScript(start) {
  const button=$(start?"#script-render":"#script-save");
  if (button.disabled) return;button.disabled=true;
  try {
    const scenes=[...document.querySelectorAll("#script-scenes [data-scene]")].map((node,i)=>({...editingScript.scenes[i],...Object.fromEntries([...node.querySelectorAll("[data-field]")].map(input=>[input.dataset.field,input.value]))}));
    await postJob(editingJob.id,start?"render":"script",{title:$("#script-title").value,scenes});
    $("#script-status").textContent=start?"Сборка поставлена в очередь":"Сценарий сохранён";
    if (start) $("#script-dialog").close();
    await load();
  } catch(error) { $("#script-status").textContent=error.message; }
  finally { button.disabled=false; }
}
$("#script-save").onclick=()=>saveScript(false);$("#script-render").onclick=()=>saveScript(true);
$("#edit-subtitles").onclick=async()=>{
  try {
    const response=await fetch(`/api/jobs/${cur.id}/script`);const script=await response.json();
    if (!response.ok) throw new Error(script.error);
    editingJob=cur;$("#subtitle-srt-editor").value=script.srt||"";$("#subtitle-edit-status").textContent="";
    dlg.close();$("#subtitle-dialog").showModal();
  } catch(error) { $("#dialog-status").textContent=error.message; }
};
$("#subtitle-edit-close").onclick=()=>$("#subtitle-dialog").close();
$("#subtitle-remount").onclick=async()=>{
  if ($("#subtitle-remount").disabled) return;
  $("#subtitle-remount").disabled=true;
  try {
    if (subtitleSettings().mode==="off") throw new Error("Включите субтитры и выберите оформление в основной форме");
    await postJob(editingJob.id,"remount",{subtitles:subtitleSettings(),srt:$("#subtitle-srt-editor").value});
    $("#subtitle-dialog").close();await load();
  } catch(error) { $("#subtitle-edit-status").textContent=error.message; }
  finally { $("#subtitle-remount").disabled=false; }
};
$("#trash-job").onclick=async()=>{
  try { await postJob(cur.id,"trash",{});dlg.close();await load(); }
  catch(error) { $("#dialog-status").textContent=error.message; }
};

$("#script-trash").onclick=async()=>{
  try { await postJob(editingJob.id,"trash",{});$("#script-dialog").close();await load(); }
  catch(error) { $("#script-status").textContent=error.message; }
};
