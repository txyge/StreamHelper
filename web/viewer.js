const cardElement = document.getElementById("viewer-card");
const connection = document.getElementById("viewer-status");
let snapshot;
async function update() {
  try {
    const response = await fetch("/api/viewer", {cache: "no-store", signal: AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error("Сервер недоступен.");
    const card = await response.json();
    const next = JSON.stringify(card);
    if (snapshot !== next) {
      showCard(cardElement, card);
      snapshot = next;
    }
    connection.textContent = "";
  } catch {
    connection.textContent = "Связь с панелью потеряна. Повторяем подключение.";
  } finally {
    setTimeout(update, 1500);
  }
}
update();
