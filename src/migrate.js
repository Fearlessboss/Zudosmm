"use strict";
const fs = require("node:fs"),
  path = require("node:path"),
  bcrypt = require("bcryptjs");
const { pool } = require("./db");
async function migrate() {
  const c = await pool.connect();
  try {
    await c.query("SELECT pg_advisory_lock(713931224)");
    await c.query(
      "CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    );
    for (const f of fs
      .readdirSync(path.join(__dirname, "../migrations"))
      .filter((f) => f.endsWith(".sql"))
      .sort()) {
      if (
        (await c.query("SELECT 1 FROM schema_migrations WHERE name=$1", [f]))
          .rowCount
      )
        continue;
      await c.query("BEGIN");
      try {
        await c.query(
          fs.readFileSync(path.join(__dirname, "../migrations", f), "utf8"),
        );
        await c.query("INSERT INTO schema_migrations(name) VALUES($1)", [f]);
        await c.query("COMMIT");
      } catch (e) {
        await c.query("ROLLBACK");
        throw e;
      }
    }
    const username = (process.env.OWNER_USERNAME || "").toLowerCase(),
      password = process.env.OWNER_PASSWORD;
    if (
      !/^[a-z0-9_]{3,32}$/.test(username) ||
      !password ||
      password.length < 10 ||
      Buffer.byteLength(password) > 72
    )
      throw Error(
        "Set a valid OWNER_USERNAME and OWNER_PASSWORD (10–72 bytes)",
      );
    const current = (
      await c.query("SELECT * FROM users WHERE role=$1", ["owner"])
    ).rows[0];
    if (current) {
      if (current.username !== username)
        throw Error(
          "OWNER_USERNAME does not match provisioned owner; change the owner account through a controlled database migration",
        );
      if (!(await bcrypt.compare(password, current.password_hash)))
        await c.query("UPDATE users SET password_hash=$1 WHERE id=$2", [
          await bcrypt.hash(password, 12),
          current.id,
        ]);
    } else
      await c.query(
        "INSERT INTO users(username,password_hash,role) VALUES($1,$2,$3)",
        [username, await bcrypt.hash(password, 12), "owner"],
      );
    console.log("Database migrations and owner provisioning complete");
  } finally {
    await c.query("SELECT pg_advisory_unlock(713931224)").catch(() => {});
    c.release();
  }
}
if (require.main === module)
  migrate()
    .then(() => pool.end())
    .catch(async (e) => {
      console.error(e.message);
      await pool.end();
      process.exitCode = 1;
    });
module.exports = { migrate };
