(() => {
  const $ = (s) => document.querySelector(s);
  const esc = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const isClear = (g) => /^path clear/i.test(g);

  const POLL_MS = 3000;
  const OFFLINE_AFTER_S = 20;

  const statusEl = $(".status");
  const nameEl = $(".object-name");
  const confEl = $(".confidence");
  const listEl = $(".history-list");
  const screen = $(".camera-screen");
  const placeholder = $(".camera-placeholder");

  const img = document.createElement("img");
  img.alt = "Latest camera frame";
  img.style.cssText =
    "position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:1;display:none";
  screen.insertBefore(img, screen.firstChild);

  function setStatus(online) {
    statusEl.innerHTML = '<div class="status-dot"></div>' + (online ? "SYSTEM ONLINE" : "SYSTEM OFFLINE");
    if (!online) {
      const dot = statusEl.querySelector(".status-dot");
      dot.style.background = "#6b6075";
      dot.style.boxShadow = "none";
      dot.style.animation = "none";
    }
  }

  async function update() {
    try {
      const res = await fetch("/api/data", { cache: "no-store" });
      const { rows, age, image } = await res.json();
      setStatus(rows.length > 0 && age < OFFLINE_AFTER_S);

      if (image) {
        img.src = image;
        img.style.display = "block";
        placeholder.style.display = "none";
      }

      if (rows.length) {
        const last = rows[rows.length - 1];
        nameEl.textContent = last.guidance;
        nameEl.style.color = isClear(last.guidance) ? "#9be7a6" : "#ffb4b4";
        const lat = last.latency_s != null ? ` · ${last.latency_s}s latency` : "";
        confEl.textContent = last.timestamp.slice(11) + lat;

        listEl.innerHTML = rows
          .slice(-20)
          .reverse()
          .map((r) => {
            const clear = isClear(r.guidance);
            return `<div class="history-item">
              <div class="history-left">
                <div class="history-icon">${clear ? "◉" : "⚠"}</div>
                <div>
                  <div class="history-name">${esc(r.guidance)}</div>
                  <div class="history-time">${esc(r.timestamp)}</div>
                </div>
              </div>
              <div class="history-status">${clear ? "CLEAR" : "ALERT"}</div>
            </div>`;
          })
          .join("");
      }
    } catch (e) {
      setStatus(false);
    }
  }

  update();
  setInterval(update, POLL_MS);
})();
