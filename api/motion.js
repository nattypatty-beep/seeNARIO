// Stores and returns the wearable's motion state (standing / walking / stumble).
// POST (from the Raspberry Pi, needs x-api-key = PI_SECRET) and GET (from the website).
const URL_ = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
const ALLOWED_KEYS = [process.env.PI_SECRET].filter(Boolean);
const VALID = ["standing", "walking", "stumble"];

async function redis(cmd) {
  const r = await fetch(URL_, {
    method: "POST",
    headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(cmd),
  });
  return r.json();
}

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  try {
    if (!URL_ || !TOKEN) return res.status(500).json({ error: "Redis variables missing" });
    if (req.method === "POST") {
      if (!ALLOWED_KEYS.includes(req.headers["x-api-key"])) return res.status(401).json({ error: "bad key" });
      const { state, stumbles } = req.body || {};
      if (!VALID.includes(state)) return res.status(400).json({ error: "bad state" });
      await redis(["SET", "motion_state", JSON.stringify({ state, stumbles: Number(stumbles) || 0, updated: Date.now() })]);
      return res.status(200).json({ ok: true });
    }
    if (req.method === "GET") {
      const out = await redis(["GET", "motion_state"]);
      if (!out.result) return res.status(200).json({ state: null, age: 9999, stumbles: 0 });
      const s = JSON.parse(out.result);
      return res.status(200).json({ state: s.state, stumbles: s.stumbles, age: (Date.now() - s.updated) / 1000 });
    }
    return res.status(405).end();
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
};
