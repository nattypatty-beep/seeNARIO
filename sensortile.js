// sensortile.js — ADD-ON ONLY. Does not touch app.js, the camera feed, or the history log.
// Adds a "Wearable" panel under the camera view that shows what the SensorTile.box detects.
(() => {
  const SPEAK_STUMBLE = true; // browser says a warning on stumble (the Pi still speaks the camera guidance)
  const CFG_KEY = "seenario_box_cfg_v2";
  const DEFAULT_CFG = {
    // Web Bluetooth can only open services listed here. Add the ones you see in nRF Connect.
    // The last one is a guess at ST's own service (unverified).
    services: "0000180f-0000-1000-8000-00805f9b34fb, 0000180a-0000-1000-8000-00805f9b34fb, 00000000-0001-11e1-9ab4-0002a5d5c51b",
    charUuid: "", byteIndex: 0, map: { standing: 0, walking: 1, stumble: 2 },
  };
  const screen = document.querySelector(".camera-screen");
  if (!screen) return;

  let cfg;
  try { const s = JSON.parse(localStorage.getItem(CFG_KEY)); cfg = { ...DEFAULT_CFG, ...s, map: { ...DEFAULT_CFG.map, ...(s && s.map) } }; }
  catch (e) { cfg = JSON.parse(JSON.stringify(DEFAULT_CFG)); }
  const saveCfg = () => { try { localStorage.setItem(CFG_KEY, JSON.stringify(cfg)); } catch (e) {} };

  function decodeState(bytes, c) {
    if (!bytes || c.byteIndex >= bytes.length) return "unknown";
    const v = bytes[c.byteIndex];
    for (const k of ["standing", "walking", "stumble"]) if (Number(c.map[k]) === v) return k;
    return "unknown";
  }
  const toBytes = (dv) => Array.from(new Uint8Array(dv.buffer, dv.byteOffset, dv.byteLength));
  const hex = (b) => b.map((x) => x.toString(16).padStart(2, "0")).join(" ");
  const normUuid = (u) => (/^0x[0-9a-f]+$/i.test(u) ? parseInt(u, 16) : u.toLowerCase());

  const bar = document.createElement("div");
  bar.style.cssText = "padding:12px 0;font-size:14px";
  bar.innerHTML =
    '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">' +
    '<strong>Wearable:</strong> <span class="st-label">not connected</span>' +
    '<button data-a="ble">Connect SensorTile.box</button>' +
    '<button data-a="sim-standing">Sim: standing</button><button data-a="sim-walking">Sim: walking</button><button data-a="sim-stumble">Sim: stumble</button></div>' +
    '<div class="st-events" style="margin-top:6px;color:#ffb4b4"></div>' +
    '<details style="margin-top:8px"><summary>Board setup</summary>' +
    '<div style="margin:6px 0">1. Service UUIDs (comma-separated), then press Connect:<br><input id="st-svc" style="width:100%"></div>' +
    '<div style="margin:6px 0">2. After connecting, pick the characteristic that changes when you move the board:<br>' +
    '<select id="st-char" style="max-width:100%"></select> <code id="st-raw"></code></div>' +
    '<div style="margin:6px 0">3. Which byte holds the activity, and what value means what:<br>' +
    'byte # <input id="st-idx" type="number" min="0" style="width:60px"> ' +
    'standing = <input id="st-m0" type="number" style="width:60px"> walking = <input id="st-m1" type="number" style="width:60px"> stumble = <input id="st-m2" type="number" style="width:60px"></div>' +
    '<button data-a="save">Use this setup</button> <small id="st-msg"></small></details>';
  screen.parentNode.insertBefore(bar, screen.nextSibling);

  const $b = (s) => bar.querySelector(s);
  const label = $b(".st-label"), events = $b(".st-events"), svcIn = $b("#st-svc"), charSel = $b("#st-char"), rawEl = $b("#st-raw"), idxIn = $b("#st-idx");
  const mapIn = { standing: $b("#st-m0"), walking: $b("#st-m1"), stumble: $b("#st-m2") };
  const msg = (t) => ($b("#st-msg").textContent = t);
  svcIn.value = cfg.services; idxIn.value = cfg.byteIndex; for (const k in mapIn) mapIn[k].value = cfg.map[k];

  let state = "unknown"; const stumbles = [];
  function setState(s) {
    if (s === state) return;
    state = s; label.textContent = s;
    if (s === "stumble") {
      stumbles.unshift(new Date().toLocaleTimeString()); stumbles.length = Math.min(stumbles.length, 5);
      events.textContent = "⚠ Stumble detected at: " + stumbles.join(", ");
      if (SPEAK_STUMBLE && "speechSynthesis" in window) speechSynthesis.speak(new SpeechSynthesisUtterance("Warning. Unsteady movement detected."));
    }
  }

  const last = {};
  function onPacket(uuid, dv) {
    const b = toBytes(dv); last[uuid] = b;
    if (charSel.value === uuid) rawEl.textContent = hex(b);
    if (uuid === cfg.charUuid) setState(decodeState(b, cfg));
  }

  async function connect() {
    try {
      if (!navigator.bluetooth) throw new Error("Web Bluetooth needs Chrome or Edge over HTTPS (not iPhone)");
      cfg.services = svcIn.value; saveCfg();
      const services = cfg.services.split(",").map((s) => s.trim()).filter(Boolean).map(normUuid);
      const dev = await navigator.bluetooth.requestDevice({ acceptAllDevices: true, optionalServices: services });
      dev.addEventListener("gattserverdisconnected", () => { state = "unknown"; label.textContent = "disconnected"; });
      label.textContent = "connecting…";
      const server = await dev.gatt.connect();
      charSel.innerHTML = "";
      for (const s of await server.getPrimaryServices()) {
        for (const c of await s.getCharacteristics()) {
          if (!c.properties.notify) continue;
          await c.startNotifications();
          c.addEventListener("characteristicvaluechanged", (e) => onPacket(c.uuid, e.target.value));
          const o = document.createElement("option"); o.value = c.uuid; o.textContent = c.uuid; charSel.appendChild(o);
        }
      }
      if (!charSel.options.length) { label.textContent = "connected, but no notifying characteristics found"; msg("Add the board's service UUIDs in step 1 (see nRF Connect) and reconnect."); return; }
      if (cfg.charUuid && [...charSel.options].some((o) => o.value === cfg.charUuid)) charSel.value = cfg.charUuid;
      label.textContent = cfg.charUuid ? "connected (waiting for data)" : "connected. Open Board setup to pick the characteristic";
      msg(charSel.options.length + " notifying characteristics found. Move the board and watch the raw bytes.");
      bar.querySelector("details").open = !cfg.charUuid;
    } catch (err) { label.textContent = "connect failed (" + err.message + ")"; }
  }

  charSel.addEventListener("change", () => { rawEl.textContent = last[charSel.value] ? hex(last[charSel.value]) : ""; });
  setInterval(() => { if (last[charSel.value]) rawEl.textContent = hex(last[charSel.value]); }, 300);
  bar.addEventListener("click", (e) => {
    const a = e.target.dataset && e.target.dataset.a;
    if (a === "ble") connect();
    else if (a === "save") {
      cfg.charUuid = charSel.value; cfg.byteIndex = Number(idxIn.value) || 0; cfg.services = svcIn.value;
      for (const k in mapIn) cfg.map[k] = Number(mapIn[k].value);
      saveCfg(); msg("Saved. The wearable label now follows this characteristic.");
      if (last[cfg.charUuid]) setState(decodeState(last[cfg.charUuid], cfg));
    } else if (a && a.startsWith("sim-")) setState(a.slice(4));
  });
})();
