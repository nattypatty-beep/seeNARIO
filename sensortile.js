// sensortile.js: Wearable panel. Automatic: click "Connect SensorTile.box" once and pick the board.
// Nothing else to configure. Sources, in priority order:
//   1. Raw accelerometer from the board -> YOUR trained decision tree (model.js) -> standing / walking / stumble
//   2. The board's own Activity Recognition (characteristic 00000010-...) -> standing / walking
//   3. The Raspberry Pi bridge (/api/motion) -> standing / walking / stumble
// (Web Bluetooth cannot connect without a click and the browser's device chooser. That cannot be skipped.)
(() => {
  const SPEAK_STUMBLE = true;
  const SERVICES = [
    "0000180f-0000-1000-8000-00805f9b34fb", "0000180a-0000-1000-8000-00805f9b34fb",
    "00000000-0001-11e1-9ab4-0002a5d5c51b",
  ];
  const screen = document.querySelector(".camera-screen");
  if (!screen) return;

  // ---- LOGIC START (pure functions) ----
  const ACTIVITY_MAP = { 1: "standing", 2: "walking", 3: "walking", 4: "walking" }; // ST's built-in model has no stumble class
  const ACC_BIT = 0x00800000; // BlueST "Accelerometer" feature bit
  const featureMask = (uuid) => parseInt(String(uuid).slice(0, 8), 16) >>> 0;
  const isBlueSt = (uuid) => /^[0-9a-f]{8}-0001-11e1-ac36-0002a5d5c51b$/i.test(uuid);
  function activityState(bytes) { return bytes.length > 2 ? ACTIVITY_MAP[bytes[2]] || null : null; }
  function parseAcc(bytes) { // 2-byte timestamp, then int16 x,y,z in milli-g (little-endian)
    if (bytes.length < 8) return null;
    const dv = new DataView(Uint8Array.from(bytes).buffer);
    return [dv.getInt16(2, true) / 1000, dv.getInt16(4, true) / 1000, dv.getInt16(6, true) / 1000];
  }
  const looksLikeG = (a) => { const m = Math.hypot(a[0], a[1], a[2]); return m > 0.5 && m < 4; };
  function makeWindow(buf, now, n = 50) { // buf: [{t,x,y,z}] -> n samples over the last second, or null
    if (buf.length < 10 || buf[0].t > now - 1000 || buf[buf.length - 1].t < now - 300) return null;
    const out = []; let j = 1;
    for (let i = 0; i < n; i++) {
      const t = now - 1000 + (i * 1000) / n;
      while (j < buf.length - 1 && buf[j].t < t) j++;
      const a = buf[j - 1], b = buf[j]; const f = b.t === a.t ? 0 : Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t)));
      out.push({ x: a.x + f * (b.x - a.x), y: a.y + f * (b.y - a.y), z: a.z + f * (b.z - a.z) });
    }
    return out;
  }
  // ---- LOGIC END ----

  const SHOW = { standing: "STANDING", walking: "WALKING", stumble: "STUMBLING", unknown: "no wearable data" };
  const COLOR = { standing: "#9be7a6", walking: "#8ecbff", stumble: "#ff6b6b", unknown: "#9a8fa8" };

  const bar = document.createElement("div");
  bar.style.cssText = "padding:12px 0;font-size:14px";
  bar.innerHTML =
    '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">' +
    '<strong>Wearable:</strong> <span class="st-label">not connected</span>' +
    '<button data-a="ble">Connect SensorTile.box</button>' +
    '<button data-a="sim-standing">Sim: standing</button><button data-a="sim-walking">Sim: walking</button><button data-a="sim-stumble">Sim: stumble</button></div>' +
    '<div class="st-events" style="margin-top:6px;color:#ffb4b4"></div>' +
    '<details style="margin-top:8px"><summary>Details (nothing to set up)</summary><div class="st-info" style="margin:6px 0;opacity:.8"></div></details>';
  screen.parentNode.insertBefore(bar, screen.nextSibling);
  const $b = (s) => bar.querySelector(s);
  const label = $b(".st-label"), events = $b(".st-events"), info = $b(".st-info");

  let state = "unknown", lastModel = 0, lastAct = 0, lastBoard = 0, fromPi = false;
  const stumbles = [];
  function setState(s, source) {
    if (s === state) return;
    state = s;
    label.textContent = (SHOW[s] || s) + (source ? " (" + source + ")" : "");
    label.style.fontWeight = "bold"; label.style.color = COLOR[s] || "";
    if (s === "stumble") {
      stumbles.unshift(new Date().toLocaleTimeString()); stumbles.length = Math.min(stumbles.length, 5);
      events.textContent = "⚠ Stumble detected at: " + stumbles.join(", ");
      if (source !== "via Raspberry Pi" && SPEAK_STUMBLE && "speechSynthesis" in window)
        speechSynthesis.speak(new SpeechSynthesisUtterance("Warning. Unsteady movement detected."));
    }
  }

  // ---- your trained model (model.js defines classifyMotion) ----
  let modelReady = typeof classifyMotion === "function";
  if (!modelReady) {
    const s = document.createElement("script"); s.src = "/model.js";
    s.onload = () => { modelReady = typeof classifyMotion === "function"; };
    document.head.appendChild(s);
  }

  // ---- Bluetooth ----
  const seen = {};            // uuid -> {kind, n, last}
  const accBuf = [];          // {t,x,y,z}
  let accUuid = null, prevWin = null; const sniff = {};
  function onPacket(uuid, dv) {
    const bytes = Array.from(new Uint8Array(dv.buffer, dv.byteOffset, dv.byteLength));
    const rec = (seen[uuid] = seen[uuid] || { n: 0 }); rec.n++; rec.last = bytes.map((x) => x.toString(16).padStart(2, "0")).join(" ");
    lastBoard = Date.now();
    if (!isBlueSt(uuid)) return;
    const mask = featureMask(uuid);
    if (mask === 0x10) { // Activity recognition
      rec.kind = "board activity";
      const s = activityState(bytes); lastAct = Date.now();
      if (s && Date.now() - lastModel > 3000) setState(s, "board activity");
      return;
    }
    // accelerometer: by feature bit, or by sniffing for ~1 g
    let acc = null;
    if (mask & ACC_BIT) acc = parseAcc(bytes);
    else if (uuid !== accUuid) {
      const a = parseAcc(bytes);
      if (a && looksLikeG(a)) { sniff[uuid] = (sniff[uuid] || 0) + 1; if (sniff[uuid] >= 15) acc = a; } else sniff[uuid] = 0;
    } else acc = parseAcc(bytes);
    if (acc && looksLikeG(acc)) {
      accUuid = uuid; rec.kind = "accelerometer -> your model";
      accBuf.push({ t: performance.now(), x: acc[0], y: acc[1], z: acc[2] });
      if (accBuf.length > 600) accBuf.splice(0, accBuf.length - 600);
    }
  }
  setInterval(() => { // run your model twice a second when raw accelerometer data is flowing
    if (!modelReady || !accBuf.length) return;
    const w = makeWindow(accBuf, performance.now()); if (!w) return;
    const raw = classifyMotion(w); lastModel = Date.now();
    const confirmed = raw === "stumble" ? (prevWin === "stumble" ? "stumble" : (state === "unknown" ? "standing" : state)) : raw;
    prevWin = raw;
    setState(confirmed, "your model on board data");
  }, 500);

  setInterval(() => {
    if (connectedAt && Date.now() - lastBoard > 8000 && Date.now() - connectedAt > 8000 && state === "unknown" && dev && dev.gatt.connected) {
      label.textContent = "connected, but the board is silent. Make sure its app is running (see Details)";
      bar.querySelector("details").open = true;
    }
  }, 1000);
  setInterval(() => {
    const rows = Object.entries(seen).map(([u, r]) => `${u.slice(0, 8)}… ${r.kind || "ignored"}: ${r.n} packets, last ${r.last}`);
    const silent = connectedAt && !Object.values(seen).some((r) => r.n > 0);
    info.innerHTML = (rows.length ? rows.join("<br>") : "Not connected.") +
      (silent ? "<br><br><b>No packets have arrived.</b> The board is connected but not sending. Usual causes: the ST phone app is still connected to the board (close it completely), the board's app was not started with Play, or the board needs a power cycle." : "");
  }, 1000);

  let dev = null, retry = 0, connectedAt = 0;
  async function attach() {
    label.textContent = "connecting…";
    const server = await dev.gatt.connect();
    let n = 0;
    for (const s of await server.getPrimaryServices()) {
      for (const c of await s.getCharacteristics()) {
        if (!c.properties.notify) continue;
        try {
          await c.startNotifications();
          c.addEventListener("characteristicvaluechanged", (e) => onPacket(c.uuid, e.target.value));
          n++;
          const rec = (seen[c.uuid] = seen[c.uuid] || { n: 0 });
          rec.kind = rec.kind || "subscribed, no packets yet"; rec.service = s.uuid.slice(0, 8);
          if (c.properties.read) { try { onPacket(c.uuid, await c.readValue()); } catch (e) {} }
        } catch (e) {
          seen[c.uuid] = { n: 0, kind: "could not subscribe (" + e.message + ")", last: "" };
        }
      }
    }
    retry = 0;
    state = "unknown"; connectedAt = Date.now();
    label.textContent = n ? "connected, waiting for data…" : "connected, but nothing to listen to";
  }
  async function connect() {
    try {
      if (!navigator.bluetooth) throw new Error("needs Chrome or Edge over HTTPS (not iPhone)");
      dev = await navigator.bluetooth.requestDevice({ acceptAllDevices: true, optionalServices: SERVICES });
      dev.addEventListener("gattserverdisconnected", async () => {
        state = "unknown"; label.textContent = "disconnected, reconnecting…";
        while (retry < 10 && !dev.gatt.connected) { retry++; await new Promise((r) => setTimeout(r, 3000)); try { await attach(); } catch (e) {} }
        if (!dev.gatt.connected) label.textContent = "disconnected";
      });
      await attach();
    } catch (err) { label.textContent = "connect failed (" + err.message + ")"; }
  }

  // ---- Raspberry Pi bridge fallback ----
  async function pollPi() {
    if (Date.now() - lastBoard < 5000) return; // the board's own data wins while it is flowing
    try {
      const j = await (await fetch("/api/motion", { cache: "no-store" })).json();
      if (j.state && j.age < 10) { fromPi = true; setState(j.state, "via Raspberry Pi"); }
      else if (fromPi) { fromPi = false; setState("unknown"); }
    } catch (e) {}
  }
  setInterval(pollPi, 2000); pollPi();

  bar.addEventListener("click", (e) => {
    const a = e.target.dataset && e.target.dataset.a;
    if (a === "ble") connect();
    else if (a && a.startsWith("sim-")) setState(a.slice(4), "simulated");
  });
})();
