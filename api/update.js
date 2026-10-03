const URL_ = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).end();
  if (!process.env.PI_SECRET || req.headers["x-api-key"] !== process.env.PI_SECRET) {
    return res.status(401).json({ error: "bad key" });
  }
  const { rows, image } = req.body || {};
  if (!Array.isArray(rows)) return res.status(400).json({ error: "missing rows" });

  const state = JSON.stringify({ rows, image: image || null, updated: Date.now() });
  const r = await fetch(URL_, {
    method: "POST",
    headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(["SET", "visionnav_state", state]),
  });
  const out = await r.json();
  res.status(r.ok ? 200 : 500).json(out);
};
