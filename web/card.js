function showCard(element, card) {
  element.replaceChildren();
  const add = (tag, text, parent = element) => {
    const node = document.createElement(tag);
    node.textContent = text;
    parent.append(node);
    return node;
  };
  if (!card) {
    add("p", "Итоги ещё не опубликованы.");
    return;
  }
  if (card.title) add("h3", card.title);
  add("p", "Длительность " + time(card.duration));
  if (card.source === "twitch") {
    add("p", "Категории · " + (card.categories.join(" → ") || "Twitch не указал категорию."));
    group("Участники чата (" + card.audience.length + ")", card.audience, String);
    group("Самые активные в чате", card.active_chat, row => row.name + " · " + row.count + " сообщ.");
    group("Топ поддержки за эфир · Bits", card.top_bits, row => row.name + " · " + row.count + " Bits");
    group("Поддержка за день Twitch · Bits" + (card.bits_today ? " · " + card.bits_today.date : ""),
      card.bits_today?.entries, row => row.name + " · " + row.count + " Bits");
    group("Модераторы канала", card.moderators, String);
  }
  group("Клипы", card.clips || [], row => {
    const url = new URL(row.url, location.origin);
    if (!["https:", "http:"].includes(url.protocol)) return row.title;
    const link = document.createElement("a");
    link.href = url.href;
    link.textContent = row.title;
    link.target = "_blank";
    link.rel = "noopener";
    return link;
  });

  function group(title, values, format) {
    add("h4", title);
    if (!values?.length) {
      add("p", values ? "Нет данных для этого списка." : "Данные пока недоступны.");
      return;
    }
    const list = add("ul", "");
    for (const value of values) {
      const row = add("li", "", list);
      row.append(format(value));
    }
  }
}

function time(seconds) {
  const whole = Math.floor(seconds);
  return [Math.floor(whole / 3600), Math.floor(whole / 60) % 60, whole % 60]
    .map(value => String(value).padStart(2, "0")).join(":");
}
