"use strict";
require("dotenv").config({ quiet: true });
const { pool } = require("./db"),
  { createApp, refreshOrder } = require("./app");
if (
  (process.env.SMM_API_URL || "https://mysmm.org/api/v2") !==
    "https://mysmm.org/api/v2" &&
  process.env.NODE_ENV !== "test"
)
  throw Error("SMM_API_URL must be https://mysmm.org/api/v2");
if (!process.env.SMM_API_KEY) throw Error("SMM_API_KEY is required");
if ((process.env.PROVIDER_CURRENCY || "INR") !== "INR")
  throw Error("Only INR provider accounts are supported");
const port = Number(process.env.PORT || 3000);
const app = createApp();
let busy = false;
const server = app.listen(port, "0.0.0.0", () =>
  console.log("ZUDO SMM PANEL listening on port " + port),
);
async function tick() {
  if (busy) return;
  busy = true;
  const c = await pool.connect().catch(() => null);
  if (!c) {
    busy = false;
    return;
  }
  let locked = false;
  try {
    locked = (await c.query("SELECT pg_try_advisory_lock(713931225) locked"))
      .rows[0].locked;
    if (!locked) return;
    await c.query(
      "UPDATE orders SET status='Needs review',provider_error='Server interrupted during submission. Verify provider history before reconciliation.',updated_at=now() WHERE status='Submitting' AND created_at < now()-interval '2 minutes'",
    );
    const rows = (
      await c.query(
        "SELECT id FROM orders WHERE provider_order_id IS NOT NULL AND status IN ('Pending','Processing','In progress') ORDER BY updated_at ASC LIMIT 30",
      )
    ).rows;
    for (const r of rows) {
      try {
        await refreshOrder(r.id, { role: "owner" });
      } catch {
        console.warn("Order status sync deferred for local order " + r.id);
      }
    }
  } catch {
    console.warn("Background order reconciliation deferred");
  } finally {
    if (locked)
      await c.query("SELECT pg_advisory_unlock(713931225)").catch(() => {});
    c.release();
    busy = false;
  }
}
const timer = setInterval(tick, 60000);
timer.unref();
let stopping = false;
function shutdown() {
  if (stopping) return;
  stopping = true;
  clearInterval(timer);
  server.close(async () => {
    await pool.end();
    process.exit(0);
  });
  setTimeout(() => process.exit(1), 25000).unref();
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
