"use strict";
require("dotenv").config({ quiet: true });
const { Pool } = require("pg");
const url = process.env.DATABASE_URL;
if (!url) throw Error("DATABASE_URL is required");
const host = new URL(url).hostname;
const internal =
  host === "localhost" ||
  host === "127.0.0.1" ||
  !host.includes(".") ||
  host.endsWith(".internal");
const sslMode = process.env.DATABASE_SSL || "auto";
const pool = new Pool({
  connectionString: url,
  ssl:
    sslMode === "disable" || (sslMode === "auto" && internal)
      ? false
      : { rejectUnauthorized: true },
  max: 15,
  connectionTimeoutMillis: 10000,
  idleTimeoutMillis: 30000,
});
pool.on("error", () => console.error("Database pool connection error"));
async function tx(fn) {
  const c = await pool.connect();
  try {
    await c.query("BEGIN");
    const r = await fn(c);
    await c.query("COMMIT");
    return r;
  } catch (e) {
    await c.query("ROLLBACK");
    throw e;
  } finally {
    c.release();
  }
}
module.exports = { pool, tx };
