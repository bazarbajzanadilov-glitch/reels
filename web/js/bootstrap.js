"use strict";

/* Точка входа: сначала /api/options, затем история, события и баланс.
   История скрыта, пока пользователь не откроет вкладку «Мои ролики». */
init()
  .then(() => {
    $("#project-history").hidden = true;
    connectJobEvents();
    balance();
    aiStatus(aiQuotaText());
  })
  .catch(() => {
    $("#err").textContent = "Не удалось загрузить настройки. Обновите страницу.";
  });
