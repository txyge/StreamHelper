function showCard(element, card) {
  element.replaceChildren();
  function line(label, value) {
    const field = document.createElement("div");
    const title = document.createElement("dt");
    const description = document.createElement("dd");
    title.textContent = label;
    description.textContent = value;
    field.append(title, description);
    return field;
  }
  if (!card) {
    const message = document.createElement("p");
    message.textContent = "Итоги ещё не опубликованы.";
    element.append(message);
    return;
  }
  const fields = document.createElement("dl");
  fields.append(line("Длительность", time(card.duration)));
  if (card.moment) fields.append(line("Момент эфира", time(card.moment.seconds) + " · " + card.moment.label));
  if (card.question) fields.append(line("Вопрос зрителя", card.question.nick + " · " + card.question.body));
  if (card.challenge) fields.append(line("Результат челленджа", card.challenge));
  if (card.announcement) fields.append(line("Следующий эфир", card.announcement));
  element.append(fields);
}

function time(seconds) {
  const whole = Math.floor(seconds);
  return [Math.floor(whole / 3600), Math.floor(whole / 60) % 60, whole % 60]
    .map(value => String(value).padStart(2, "0")).join(":");
}
