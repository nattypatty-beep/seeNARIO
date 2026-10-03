const URL_ = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  try {
    if (!URL_ || !TOKEN) {
      return res.status(500).json({ error: "Redis variables missing. Connect Upstash Redis in Vercel Storage and redeploy." });
    }
    const r = await fetch(URL_, {
      method: "POST",
      headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
      body: JSON.stringify(["GET", "visionnav_state"]),
    });
    const out = await r.json();
    if (!out.result) return res.status(200).json({ rows: [], age: 9999, image: null });
    const s = JSON.parse(out.result);
    res.status(200).json({ rows: s.rows, age: (Date.now() - s.updated) / 1000, image: s.image });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
};
