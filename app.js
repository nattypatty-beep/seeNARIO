(() => {
  const $ = (s) => document.querySelector(s);
  const esc = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const isClear = (g) => /^path clear/i.test(g);

  const POLL_MS = 3000;
  const OFFLINE_AFTER_S = 20;

  // ---- SensorTile.box settings (fill in once the board is flashed) ----
  const BOX_SERVICE = "TODO-service-uuid";
  const BOX_CHAR = "TODO-characteristic-uuid";
  const BOX_STATES = { 0: "standing", 1: "walking", 2: "stumble" }; // 1 byte sent by the board's on-device model
  const SPEAK_IN_BROWSER = true; // set false if your capture device already speaks

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

  // ---- Wearable motion state ----
  let motion = "unknown"; // unknown | standing | walking | stumble
  let lastRows = [];
  let lastSpoken = null;
  const motionEvents = [];

  const bar = document.createElement("div");
  bar.style.cssText = "display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:12px 0;font-size:14px";
  bar.innerHTML =
    '<span class="motion-label">Wearable: not connected</span>' +
    '<button data-a="ble">Connect SensorTile.box</button>' +
    '<button data-a="0">Sim: standing</button><button data-a="1">Sim: walking</button><button data-a="2">Sim: stumble</button>';
  screen.parentNode.insertBefore(bar, screen.nextSibling);
  const motionLabel = bar.querySelector(".motion-label");

  function speak(msg) {
    if (SPEAK_IN_BROWSER && "speechSynthesis" in window) speechSynthesis.speak(new SpeechSynthesisUtterance(msg));
  }

  function setMotion(state) {
    motion = state;
    motionLabel.textContent = "Wearable: " + state;
    if (state === "stumble") {
      motionEvents.unshift({ time: new Date().toISOString().replace("T", " ").slice(0, 19) });
      motionEvents.length = Math.min(motionEvents.length, 5);
      speak("Warning. Unsteady movement detected.");
      renderHistory();
    }
  }

  async function connectBox() {
    try {
      if (!navigator.bluetooth) throw new Error("Web Bluetooth not supported (use Chrome/Edge over HTTPS)");
      const dev = await navigator.bluetooth.requestDevice({ filters: [{ services: [BOX_SERVICE] }] });
      dev.addEventListener("gattserverdisconnected", () => setMotion("unknown"));
      const server = await dev.gatt.connect();
      const chr = await (await server.getPrimaryService(BOX_SERVICE)).getCharacteristic(BOX_CHAR);
      await chr.startNotifications();
      chr.addEventListener("characteristicvaluechanged", (e) =>
        setMotion(BOX_STATES[e.target.value.getUint8(0)] || "unknown")
      );
      setMotion("standing");
    } catch (err) {
      motionLabel.textContent = "Wearable: connect failed (" + err.message + ")";
    }
  }

  bar.addEventListener("click", (e) => {
    const a = e.target.dataset && e.target.dataset.a;
    if (a === "ble") connectBox();
    else if (a in BOX_STATES) setMotion(BOX_STATES[a]);
  });

  function setStatus(online) {
    statusEl.innerHTML = '<div class="status-dot"></div>' + (online ? "SYSTEM ONLINE" : "SYSTEM OFFLINE");
    if (!online) {
      const dot = statusEl.querySelector(".status-dot");
      dot.style.background = "#6b6075";
      dot.style.boxShadow = "none";
      dot.style.animation = "none";
    }
  }

  function renderHistory() {
    const stumbles = motionEvents.map(
      (m) => `<div class="history-item">
        <div class="history-left">
          <div class="history-icon">⚠</div>
          <div>
            <div class="history-name">Stumble detected by wearable</div>
            <div class="history-time">${esc(m.time)}</div>
          </div>
        </div>
        <div class="history-status">MOTION</div>
      </div>`
    );
    const camera = lastRows
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
      });
    if (stumbles.length || camera.length) listEl.innerHTML = stumbles.concat(camera).join("");
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
        lastRows = rows;
        const last = rows[rows.length - 1];
        const alert = !isClear(last.guidance);
        // Camera + wearable together: an obstacle while the user is walking is urgent.
        const urgent = alert && motion === "walking";
        nameEl.textContent = urgent ? "STOP — " + last.guidance : last.guidance;
        nameEl.style.color = alert ? "#ffb4b4" : "#9be7a6";
        if (urgent && last.timestamp !== lastSpoken) {
          lastSpoken = last.timestamp;
          speak("Stop. " + last.guidance);
        }
        const lat = last.latency_s != null ? ` · ${last.latency_s}s latency` : "";
        confEl.textContent = last.timestamp.slice(11) + lat + (motion !== "unknown" ? ` · ${motion}` : "");
        renderHistory();
      }
    } catch (e) {
      setStatus(false);
    }
  }

  update();
  setInterval(update, POLL_MS);
})();
