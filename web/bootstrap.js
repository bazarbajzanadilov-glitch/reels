"use strict";
init().then(()=>{$("#project-history").hidden=true;connectJobEvents();balance();}).catch(()=>{$("#err").textContent="Не удалось загрузить настройки. Обновите страницу.";});
