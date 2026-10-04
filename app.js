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
    '<button data-a="phone">Use phone sensors</button><button data-a="0">Sim: standing</button><button data-a="1">Sim: walking</button><button data-a="2">Sim: stumble</button>';
  screen.parentNode.insertBefore(bar, screen.nextSibling);
  const motionLabel = bar.querySelector(".motion-label");

  function speak(msg) {
    if (SPEAK_IN_BROWSER && "speechSynthesis" in window) speechSynthesis.speak(new SpeechSynthesisUtterance(msg));
  }

  function setMotion(state) {
    if (state === motion) return; // only react to changes
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

  // Edge inference on the phone's own motion sensor, using the model exported by train.py (model.js).
  async function startPhone() {
    try {
      if (typeof classifyMotion !== "function") {
        await new Promise((ok, no) => {
          const sc = document.createElement("script");
          sc.src = "model.js"; sc.onload = ok; sc.onerror = () => no(new Error("model.js not found. Train first."));
          document.head.appendChild(sc);
        });
      }
      if (typeof DeviceMotionEvent !== "undefined" && DeviceMotionEvent.requestPermission) {
        if ((await DeviceMotionEvent.requestPermission()) !== "granted") throw new Error("permission denied");
      }
      let latest = null; const buf = []; let n = 0, strikes = 0;
      addEventListener("devicemotion", (e) => {
        const a = e.accelerationIncludingGravity;
        if (a && a.x != null) latest = { x: a.x / 9.80665, y: a.y / 9.80665, z: a.z / 9.80665 };
      });
      let next = performance.now();
      setInterval(() => { // clock-based 50 Hz slots, 1 s windows, 50% overlap (matches train.py)
        if (!latest) return;
        const now = performance.now();
        if (now - next > 1000) next = now; // resync after a long pause
        while (next <= now) {
          next += 20;
          buf.push(latest); if (buf.length > 50) buf.shift();
          if (buf.length === 50 && ++n % 25 === 0) {
            const c = classifyMotion(buf); // a stumble must show in 2 windows in a row, to cut false alarms
            if (c === "stumble") { if (++strikes >= 2) setMotion("stumble"); }
            else { strikes = 0; setMotion(c); }
          }
        }
      }, 20);
      motionLabel.textContent = "Wearable: phone sensors on";
    } catch (err) {
      motionLabel.textContent = "Phone mode failed (" + err.message + ")";
    }
  }

  bar.addEventListener("click", (e) => {
    const a = e.target.dataset && e.target.dataset.a;
    if (a === "ble") connectBox();
    else if (a === "phone") startPhone();
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
