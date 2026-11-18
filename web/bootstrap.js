"use strict";
init().then(()=>{connectJobEvents();balance();}).catch(()=>{$("#err").textContent="Не удалось загрузить настройки. Обновите страницу.";});
