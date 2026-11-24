let draftSession = null;
const draft = byId("publish");

function draftCard() {
  const data = Object.fromEntries(new FormData(draft));
  const result = {
    duration: current.duration,
    challenge: data.challenge.trim(),
    announcement: data.announcement.trim(),
  };
  if (data.moment) result.moment = current.marks.find(item => item.id === Number(data.moment));
  if (data.question) result.question = current.questions.find(item => item.id === Number(data.question));
  return result;
}

function renderPublication() {
  const ready = current && current.session.ended !== null;
  byId("publication").hidden = !ready;
  if (!ready) return;
  if (draftSession !== current.session.id) {
    draft.reset();
    byId("publish-status").textContent = "";
    draftSession = current.session.id;
  }
  const choices = [
    [draft.elements.moment, current.marks, item => time(item.seconds) + " · " + item.label],
    [draft.elements.question, current.questions, item => item.nick + " · " + item.body],
  ];
  for (const [select, items, label] of choices) {
    const previous = select.value;
    select.replaceChildren(option("", "Не показывать"), ...items.map(item => option(String(item.id), label(item))));
    select.value = items.some(item => String(item.id) === previous) ? previous : "";
  }
  showCard(byId("preview"), draftCard());
}
draft.addEventListener("input", () => showCard(byId("preview"), draftCard()));
form("publish", async data => {
  await action("publish", {
    moment: data.moment ? Number(data.moment) : null,
    question: data.question ? Number(data.question) : null,
    challenge: data.challenge,
    announcement: data.announcement
  });
  byId("publish-status").textContent = "Карточка опубликована.";
});
draft.addEventListener("input", () => {
  byId("publish-status").textContent = "";
});
