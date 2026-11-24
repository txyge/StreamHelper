function renderPublication() {
  const section = byId("publication");
  section.hidden = !current;
  if (!current) return;
  const live = current.session.ended === null;
  byId("publish").hidden = live;
  byId("publish-hint").textContent = live
    ? "Итоги можно опубликовать после завершения эфира."
    : "Карточка собрана из данных сессии. Публикация отправит этот снимок на экран зрителей.";
  showCard(byId("preview"), current.card);
}

form("publish", async () => {
  await action("publish", {});
  byId("publish-status").textContent = "Карточка опубликована.";
});
