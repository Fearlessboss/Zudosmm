"use strict";
const express = require("express"),
  session = require("express-session"),
  PgSession = require("connect-pg-simple")(session),
  helmet = require("helmet"),
  { rateLimit } = require("express-rate-limit"),
  bcrypt = require("bcryptjs"),
  crypto = require("node:crypto"),
  path = require("node:path"),
  { z } = require("zod"),
  Decimal = require("decimal.js");
const { pool, tx } = require("./db");
const P = require("./provider");
const { AppError } = P;
const username = z
  .string()
  .trim()
  .toLowerCase()
  .regex(
    /^[a-z0-9_]{3,32}$/,
    "Username must be 3–32 letters, numbers or underscores",
  );
const password = z
  .string()
  .min(10)
  .refine(
    (s) => Buffer.byteLength(s) <= 72,
    "Password must not exceed 72 bytes",
  );
const amount = z
  .union([z.string(), z.number()])
  .transform(String)
  .refine(
    (s) =>
      /^\d{1,8}(\.\d{1,2})?$/.test(s) &&
      new Decimal(s).gt(0) &&
      new Decimal(s).lte(10000000),
    "Enter an amount from 0.01 to 10000000 with at most two decimals",
  );
const uuid = z.string().uuid(),
  reason = z.string().trim().min(3).max(500);
const parse = (schema, data) => schema.parse(data);
const id = (x) => parse(z.string().regex(/^[1-9]\d{0,17}$/), String(x));
const wrap = (f) => (req, res, next) =>
  Promise.resolve(f(req, res, next)).catch(next);
const publicUser = (u) => ({
  id: u.id,
  username: u.username,
  role: u.role,
  balance: u.balance,
  suspended: u.suspended,
  created_at: u.created_at,
});
async function audit(c, owner, action, target, details = {}) {
  await c.query(
    "INSERT INTO admin_logs(owner_id,action,target,details) VALUES($1,$2,$3,$4)",
    [owner, action, String(target), JSON.stringify(details)],
  );
}
async function wallet(c, userId, delta, type, note, reference) {
  const user = (
    await c.query("SELECT * FROM users WHERE id=$1 FOR UPDATE", [userId])
  ).rows[0];
  if (!user) throw new AppError(404, "User not found");
  const next = new Decimal(user.balance).plus(delta);
  if (next.lt(0)) throw new AppError(409, "Insufficient wallet balance");
  if (next.gt("999999999999999999.99"))
    throw new AppError(409, "Balance limit exceeded");
  const balance = P.money(next);
  await c.query("UPDATE users SET balance=$1 WHERE id=$2", [balance, userId]);
  await c.query(
    "INSERT INTO transactions(user_id,amount,balance_after,type,reason,reference) VALUES($1,$2,$3,$4,$5,$6)",
    [userId, P.money(delta), balance, type, note, reference],
  );
  return balance;
}
function paging(req) {
  return {
    limit: Math.trunc(
      Math.min(100, Math.max(1, Number(req.query.limit) || 25)),
    ),
    offset: Math.trunc(
      Math.max(0, Math.min(1000000, Number(req.query.offset) || 0)),
    ),
    q: String(req.query.q || "").slice(0, 100),
  };
}
async function list(req, table, select, where = [], params = []) {
  const { limit, offset } = paging(req);
  const clause = where.length ? " WHERE " + where.join(" AND ") : "";
  const total = (
    await pool.query(`SELECT count(*) FROM ${table}${clause}`, params)
  ).rows[0].count;
  const rows = (
    await pool.query(
      `SELECT ${select} FROM ${table}${clause} ORDER BY ${table.split(" ")[1] || table}.id DESC LIMIT $${params.length + 1} OFFSET $${params.length + 2}`,
      [...params, limit, offset],
    )
  ).rows;
  return { items: rows, total: Number(total), limit, offset };
}
function createApp() {
  const app = express(),
    production = process.env.NODE_ENV === "production";
  if (!process.env.SESSION_SECRET || process.env.SESSION_SECRET.length < 32)
    throw Error("SESSION_SECRET must contain at least 32 characters");
  app.disable("x-powered-by");
  app.set("trust proxy", 1);
  app.use(
    helmet({
      contentSecurityPolicy: {
        directives: {
          defaultSrc: ["'self'"],
          scriptSrc: ["'self'"],
          styleSrc: ["'self'"],
          fontSrc: ["'self'"],
          imgSrc: ["'self'", "data:"],
          connectSrc: ["'self'"],
          upgradeInsecureRequests: production ? [] : null,
        },
      },
      strictTransportSecurity: production ? undefined : false,
    }),
  );
  app.use(express.json({ limit: "40kb" }));
  app.get(
    "/health",
    wrap(async (req, res) => {
      await pool.query("SELECT 1");
      res.json({ status: "ok" });
    }),
  );
  app.use(
    "/api",
    rateLimit({
      windowMs: 60000,
      limit: 300,
      standardHeaders: "draft-7",
      legacyHeaders: false,
      message: { error: "Too many requests. Please wait a minute." },
    }),
  );
  app.use(
    "/api",
    session({
      name: production ? "__Host-zudo.sid" : "zudo.sid",
      secret: process.env.SESSION_SECRET,
      resave: false,
      saveUninitialized: false,
      rolling: true,
      store: new PgSession({
        pool,
        tableName: "sessions",
        createTableIfMissing: false,
        pruneSessionInterval: 900,
      }),
      cookie: {
        httpOnly: true,
        secure: production,
        sameSite: "lax",
        maxAge: 8 * 60 * 60 * 1000,
        path: "/",
      },
    }),
  );
  app.use("/api", (req, res, next) => {
    res.set("Cache-Control", "no-store");
    next();
  });
  app.get("/api/csrf", (req, res) => {
    if (!req.session.csrf)
      req.session.csrf = crypto.randomBytes(32).toString("hex");
    res.json({ token: req.session.csrf });
  });
  app.use("/api", (req, res, next) => {
    if (["GET", "HEAD", "OPTIONS"].includes(req.method)) return next();
    const token = req.get("x-csrf-token") || "",
      valid = req.session.csrf || "";
    if (
      !valid ||
      Buffer.byteLength(token) !== Buffer.byteLength(valid) ||
      !crypto.timingSafeEqual(Buffer.from(token), Buffer.from(valid))
    )
      return res
        .status(403)
        .json({ error: "Invalid security token. Refresh and try again." });
    const origin = req.get("origin"),
      expected =
        process.env.APP_ORIGIN ||
        (process.env.RENDER_EXTERNAL_HOSTNAME
          ? "https://" + process.env.RENDER_EXTERNAL_HOSTNAME
          : null);
    if (origin && expected && origin !== expected)
      return res.status(403).json({ error: "Origin not permitted" });
    next();
  });
  const authLimit = rateLimit({
    windowMs: 15 * 60000,
    limit: 20,
    skipSuccessfulRequests: true,
    standardHeaders: "draft-7",
    legacyHeaders: false,
    message: { error: "Too many login attempts. Try again in 15 minutes." },
  });
  async function startSession(req, user) {
    await new Promise((resolve, reject) =>
      req.session.regenerate((e) => (e ? reject(e) : resolve())),
    );
    req.session.userId = user.id;
    req.session.authVersion = user.password_hash.slice(-20);
    req.session.csrf = crypto.randomBytes(32).toString("hex");
    await new Promise((resolve, reject) =>
      req.session.save((e) => (e ? reject(e) : resolve())),
    );
  }
  app.post(
    "/api/auth/register",
    authLimit,
    wrap(async (req, res) => {
      const d = parse(
        z
          .object({ username, password, confirmPassword: z.string() })
          .refine((d) => d.password === d.confirmPassword, {
            message: "Passwords do not match",
          }),
        req.body,
      );
      if (d.username === (process.env.OWNER_USERNAME || "").toLowerCase())
        throw new AppError(409, "Username is unavailable");
      const hash = await bcrypt.hash(d.password, 12);
      const u = (
        await pool.query(
          "INSERT INTO users(username,password_hash) VALUES($1,$2) RETURNING *",
          [d.username, hash],
        )
      ).rows[0];
      await startSession(req, u);
      res.status(201).json({ user: publicUser(u), csrf: req.session.csrf });
    }),
  );
  async function login(req, res, owner) {
    const d = parse(
      z.object({ username, password: z.string().min(1).max(200) }),
      req.body,
    );
    const u = (
      await pool.query("SELECT * FROM users WHERE username=$1", [d.username])
    ).rows[0];
    const hash =
      u?.password_hash ||
      "$2b$12$C6UzMDM.H6dfI/f/IKcEe.4XzsQm6hwmT7QYJsj4J7XjD9NUp66bW";
    const valid = await bcrypt.compare(d.password, hash);
    if (!u || !valid || u.role !== (owner ? "owner" : "user"))
      throw new AppError(401, "Invalid username or password");
    if (u.suspended)
      throw new AppError(403, "Your account is suspended. Contact support.");
    await startSession(req, u);
    res.json({ user: publicUser(u), csrf: req.session.csrf });
  }
  app.post(
    "/api/auth/login",
    authLimit,
    wrap((req, res) => login(req, res, false)),
  );
  app.post(
    "/api/auth/owner",
    authLimit,
    wrap((req, res) => login(req, res, true)),
  );
  app.post(
    "/api/auth/logout",
    wrap(async (req, res) => {
      await new Promise((resolve, reject) =>
        req.session.destroy((e) => (e ? reject(e) : resolve())),
      );
      res.clearCookie(production ? "__Host-zudo.sid" : "zudo.sid", {
        path: "/",
        httpOnly: true,
        secure: production,
        sameSite: "lax",
      });
      res.json({ ok: true });
    }),
  );
  app.use(
    "/api",
    wrap(async (req, res, next) => {
      if (!req.session.userId) throw new AppError(401, "Please sign in");
      const u = (
        await pool.query("SELECT * FROM users WHERE id=$1", [
          req.session.userId,
        ])
      ).rows[0];
      if (
        !u ||
        u.suspended ||
        req.session.authVersion !== u.password_hash.slice(-20)
      ) {
        req.session.destroy(() => {});
        throw new AppError(401, "Session expired or account suspended");
      }
      req.user = u;
      next();
    }),
  );
  app.get("/api/me", (req, res) =>
    res.json({
      user: publicUser(req.user),
      upi_id: process.env.UPI_ID || "Fearlessaditya@fam",
    }),
  );
  app.post(
    "/api/profile/password",
    wrap(async (req, res) => {
      if (req.user.role === "owner")
        throw new AppError(
          400,
          "Owner password is managed through OWNER_PASSWORD in Render environment variables",
        );
      const d = parse(
        z
          .object({
            currentPassword: z.string(),
            password,
            confirmPassword: z.string(),
          })
          .refine((x) => x.password === x.confirmPassword, {
            message: "Passwords do not match",
          }),
        req.body,
      );
      if (!(await bcrypt.compare(d.currentPassword, req.user.password_hash)))
        throw new AppError(401, "Current password is incorrect");
      const h = await bcrypt.hash(d.password, 12);
      await pool.query("UPDATE users SET password_hash=$1 WHERE id=$2", [
        h,
        req.user.id,
      ]);
      req.session.authVersion = h.slice(-20);
      res.json({ ok: true });
    }),
  );
  app.get(
    "/api/dashboard",
    wrap(async (req, res) => {
      const stats = (
        await pool.query(
          `SELECT count(*) AS total,count(*) FILTER(WHERE status='Completed') AS completed,count(*) FILTER(WHERE status NOT IN ('Completed','Canceled','Cancelled','Failed','Partial')) AS pending FROM orders WHERE user_id=$1`,
          [req.user.id],
        )
      ).rows[0];
      const transactions = (
        await pool.query(
          "SELECT * FROM transactions WHERE user_id=$1 ORDER BY id DESC LIMIT 6",
          [req.user.id],
        )
      ).rows;
      res.json({ user: publicUser(req.user), stats, transactions });
    }),
  );
  app.get(
    "/api/services",
    wrap(async (req, res) => res.json(await P.catalogue())),
  );
  app.post(
    "/api/orders/quote",
    wrap(async (req, res) => {
      const d = parse(
        z.object({
          service: z.string().min(1),
          quantity: z.coerce.number().int().positive().max(1000000000),
        }),
        req.body,
      );
      await P.syncServices();
      const s = (
        await pool.query(
          "SELECT payload FROM services_cache WHERE service_id=$1 AND active=true",
          [d.service],
        )
      ).rows[0]?.payload;
      if (!s) throw new AppError(404, "Service not found");
      if (!P.supported.has(s.type))
        throw new AppError(
          400,
          "Recurring subscription ordering is not documented by the provider and is not available",
        );
      const qty = s.type === "Package" ? 1 : d.quantity;
      if (s.type !== "Package" && (qty < Number(s.min) || qty > Number(s.max)))
        throw new AppError(
          400,
          `Quantity must be between ${s.min} and ${s.max}`,
        );
      const profit = (
        await pool.query(
          "SELECT value FROM settings WHERE key='profit_percentage'",
        )
      ).rows[0].value;
      res.json({
        quantity: qty,
        total: P.price(s, qty, profit).selling,
        currency: "INR",
        profit_percentage: profit,
      });
    }),
  );
  app.post(
    "/api/orders",
    wrap(async (req, res) => {
      const d = parse(
        z.object({
          service: z.string().min(1),
          quantity: z.coerce.number().int().positive().max(1000000000),
          link: z
            .string()
            .url()
            .max(2000)
            .refine((s) => /^https?:\/\//.test(s), "Use an HTTP or HTTPS link"),
          media: z.string().url().max(2000).optional(),
          idempotencyKey: uuid,
          expectedTotal: amount,
        }),
        req.body,
      );
      const existing = (
        await pool.query(
          "SELECT * FROM orders WHERE user_id=$1 AND idempotency_key=$2",
          [req.user.id, d.idempotencyKey],
        )
      ).rows[0];
      if (existing) return res.json({ order: existing, replayed: true });
      await P.syncServices();
      await P.verifyCurrency();
      let order;
      try {
        order = await tx(async (c) => {
          const user = (
            await c.query("SELECT * FROM users WHERE id=$1 FOR UPDATE", [
              req.user.id,
            ])
          ).rows[0];
          if (user.suspended) throw new AppError(403, "Account suspended");
          const old = (
            await c.query(
              "SELECT * FROM orders WHERE user_id=$1 AND idempotency_key=$2",
              [req.user.id, d.idempotencyKey],
            )
          ).rows[0];
          if (old) return { ...old, replayed: true };
          const s = (
            await c.query(
              "SELECT payload FROM services_cache WHERE service_id=$1 AND active=true FOR SHARE",
              [d.service],
            )
          ).rows[0]?.payload;
          if (!s) throw new AppError(404, "Service not found");
          if (!P.supported.has(s.type))
            throw new AppError(
              400,
              "Provider has not documented ordering for this service type",
            );
          const quantity = s.type === "Package" ? 1 : d.quantity;
          if (
            s.type !== "Package" &&
            (quantity < Number(s.min) || quantity > Number(s.max))
          )
            throw new AppError(
              400,
              `Quantity must be between ${s.min} and ${s.max}`,
            );
          if (s.type === "Mentions Media Likers" && !d.media)
            throw new AppError(400, "Media URL is required");
          const profit = (
            await c.query(
              "SELECT value FROM settings WHERE key='profit_percentage' FOR SHARE",
            )
          ).rows[0].value;
          const pricing = P.price(s, quantity, profit);
          if (!new Decimal(pricing.selling).eq(d.expectedTotal))
            throw new AppError(
              409,
              "Price changed. Request a new quote before confirming.",
            );
          if (new Decimal(pricing.selling).lte(0))
            throw new AppError(
              400,
              "Service price is below the minimum billable amount",
            );
          const payload = {
            service: d.service,
            link: d.link,
            ...(s.type !== "Package" ? { quantity: String(quantity) } : {}),
            ...(s.type === "Mentions Media Likers" ? { media: d.media } : {}),
          };
          const row = (
            await c.query(
              "INSERT INTO orders(user_id,idempotency_key,service_id,service_name,service_type,link,quantity,provider_cost,selling_price,profit_percentage,request_payload) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING *",
              [
                user.id,
                d.idempotencyKey,
                d.service,
                s.name,
                s.type,
                d.link,
                quantity,
                pricing.cost,
                pricing.selling,
                profit,
                JSON.stringify(payload),
              ],
            )
          ).rows[0];
          await wallet(
            c,
            user.id,
            new Decimal(pricing.selling).negated().toFixed(2),
            "order",
            "Order #" + row.id,
            "order:" + row.id,
          );
          return row;
        });
      } catch (e) {
        throw e;
      }
      if (order.replayed) return res.json({ order, replayed: true });
      try {
        const result = await P.call("add", order.request_payload);
        if (!result.order)
          throw new AppError(502, "Unrecognized provider response");
        order = (
          await pool.query(
            "UPDATE orders SET provider_order_id=$1,status='Pending',updated_at=now() WHERE id=$2 RETURNING *",
            [String(result.order), order.id],
          )
        ).rows[0];
      } catch (e) {
        if (e instanceof P.ProviderRejected) {
          order = await tx(async (c) => {
            const row = (
              await c.query("SELECT * FROM orders WHERE id=$1 FOR UPDATE", [
                order.id,
              ])
            ).rows[0];
            await wallet(
              c,
              row.user_id,
              row.selling_price,
              "refund",
              "Provider rejected order #" + row.id,
              "refund:rejection:" + row.id,
            );
            return (
              await c.query(
                "UPDATE orders SET status='Failed',refunded=selling_price,provider_error=$1,updated_at=now() WHERE id=$2 RETURNING *",
                [e.message, row.id],
              )
            ).rows[0];
          });
        } else {
          order = (
            await pool.query(
              "UPDATE orders SET status='Needs review',provider_error=$1,updated_at=now() WHERE id=$2 RETURNING *",
              [e.message, order.id],
            )
          ).rows[0];
        }
      }
      res.status(201).json({ order });
    }),
  );
  app.get(
    "/api/orders",
    wrap(async (req, res) => {
      const { q } = paging(req),
        p = [req.user.id],
        w = ["o.user_id=$1"];
      if (q) {
        p.push("%" + q + "%");
        w.push(
          `(o.id::text ILIKE $2 OR o.service_name ILIKE $2 OR o.status ILIKE $2)`,
        );
      }
      res.json(await list(req, "orders o", "o.*", w, p));
    }),
  );
  app.post(
    "/api/orders/:id/refresh",
    wrap(async (req, res) =>
      res.json({ order: await refreshOrder(id(req.params.id), req.user) }),
    ),
  );
  app.get(
    "/api/transactions",
    wrap(async (req, res) =>
      res.json(
        await list(req, "transactions", "*", ["user_id=$1"], [req.user.id]),
      ),
    ),
  );
  app.get(
    "/api/deposits",
    wrap(async (req, res) =>
      res.json(await list(req, "deposits", "*", ["user_id=$1"], [req.user.id])),
    ),
  );
  app.post(
    "/api/deposits",
    wrap(async (req, res) => {
      const d = parse(
        z.object({
          amount,
          utr: z
            .string()
            .trim()
            .toUpperCase()
            .regex(
              /^[A-Z0-9-]{6,80}$/,
              "UTR must be 6–80 letters, numbers or hyphens",
            ),
        }),
        req.body,
      );
      const dep = (
        await pool.query(
          "INSERT INTO deposits(user_id,amount,utr) VALUES($1,$2,$3) RETURNING *",
          [req.user.id, d.amount, d.utr],
        )
      ).rows[0];
      res.status(201).json({ deposit: dep });
    }),
  );
  app.get(
    "/api/tickets",
    wrap(async (req, res) =>
      res.json(await list(req, "tickets", "*", ["user_id=$1"], [req.user.id])),
    ),
  );
  app.post(
    "/api/tickets",
    wrap(async (req, res) => {
      const d = parse(
        z.object({
          subject: z.string().trim().min(3).max(180),
          body: z.string().trim().min(10).max(5000),
        }),
        req.body,
      );
      const t = await tx(async (c) => {
        const row = (
          await c.query(
            "INSERT INTO tickets(user_id,subject) VALUES($1,$2) RETURNING *",
            [req.user.id, d.subject],
          )
        ).rows[0];
        await c.query(
          "INSERT INTO ticket_messages(ticket_id,user_id,body) VALUES($1,$2,$3)",
          [row.id, req.user.id, d.body],
        );
        return row;
      });
      res.status(201).json({ ticket: t });
    }),
  );
  app.get(
    "/api/tickets/:id",
    wrap(async (req, res) => {
      const t = (
        await pool.query("SELECT * FROM tickets WHERE id=$1", [
          id(req.params.id),
        ])
      ).rows[0];
      if (!t || (req.user.role !== "owner" && t.user_id !== req.user.id))
        throw new AppError(404, "Ticket not found");
      const messages = (
        await pool.query(
          "SELECT m.*,u.username,u.role FROM ticket_messages m JOIN users u ON u.id=m.user_id WHERE ticket_id=$1 ORDER BY m.id",
          [t.id],
        )
      ).rows;
      res.json({ ticket: t, messages });
    }),
  );
  app.post(
    "/api/tickets/:id/messages",
    wrap(async (req, res) => {
      const d = parse(
        z.object({ body: z.string().trim().min(1).max(5000) }),
        req.body,
      );
      await tx(async (c) => {
        const t = (
          await c.query("SELECT * FROM tickets WHERE id=$1 FOR UPDATE", [
            id(req.params.id),
          ])
        ).rows[0];
        if (!t || (req.user.role !== "owner" && t.user_id !== req.user.id))
          throw new AppError(404, "Ticket not found");
        if (t.status === "closed") throw new AppError(409, "Ticket is closed");
        await c.query(
          "INSERT INTO ticket_messages(ticket_id,user_id,body) VALUES($1,$2,$3)",
          [t.id, req.user.id, d.body],
        );
        await c.query("UPDATE tickets SET updated_at=now() WHERE id=$1", [
          t.id,
        ]);
        if (req.user.role === "owner")
          await audit(c, req.user.id, "ticket.reply", t.id);
      });
      res.status(201).json({ ok: true });
    }),
  );
  app.use("/api/admin", (req, res, next) =>
    req.user.role === "owner"
      ? next()
      : res.status(403).json({ error: "Owner access required" }),
  );
  app.get(
    "/api/admin/stats",
    wrap(async (req, res) => {
      const stats = (
        await pool.query(
          `SELECT (SELECT count(*) FROM users WHERE role='user') total_users,(SELECT count(*) FROM orders) total_orders,(SELECT COALESCE(sum(selling_price-refunded),0) FROM orders) total_revenue,(SELECT COALESCE(sum(CASE WHEN status='Failed' THEN 0 WHEN status IN ('Canceled','Cancelled','Partial') AND refunded>0 THEN provider_cost*(1-refunded/NULLIF(selling_price,0)) ELSE provider_cost END),0) FROM orders) total_provider_cost,(SELECT count(*) FROM deposits WHERE status='pending') pending_deposits,(SELECT count(*) FROM deposits WHERE status='approved') approved_deposits,(SELECT count(*) FROM deposits WHERE status='rejected') rejected_deposits`,
        )
      ).rows[0];
      stats.total_profit = P.money(
        new Decimal(stats.total_revenue).minus(stats.total_provider_cost),
      );
      let provider;
      try {
        provider = await P.call("balance");
      } catch (e) {
        provider = { error: e.message };
      }
      res.json({
        stats,
        provider,
        profit_percentage: (
          await pool.query(
            "SELECT value FROM settings WHERE key='profit_percentage'",
          )
        ).rows[0].value,
      });
    }),
  );
  app.get(
    "/api/admin/users",
    wrap(async (req, res) => {
      const { q } = paging(req);
      res.json(
        await list(
          req,
          "users",
          "id,username,role,balance,suspended,created_at",
          q ? ["role='user'", "username ILIKE $1"] : ["role='user'"],
          q ? ["%" + q + "%"] : [],
        ),
      );
    }),
  );
  app.get(
    "/api/admin/users/:id",
    wrap(async (req, res) => {
      const uid = id(req.params.id),
        user = (
          await pool.query(
            "SELECT id,username,balance,suspended,created_at FROM users WHERE id=$1 AND role='user'",
            [uid],
          )
        ).rows[0];
      if (!user) throw new AppError(404, "User not found");
      res.json({
        user,
        orders: await list(req, "orders", "*", ["user_id=$1"], [uid]),
        transactions: await list(
          req,
          "transactions",
          "*",
          ["user_id=$1"],
          [uid],
        ),
      });
    }),
  );
  app.post(
    "/api/admin/users/:id/suspend",
    wrap(async (req, res) => {
      const d = parse(z.object({ suspended: z.boolean(), reason }), req.body);
      await tx(async (c) => {
        const u = (
          await c.query(
            "UPDATE users SET suspended=$1 WHERE id=$2 AND role='user' RETURNING *",
            [d.suspended, id(req.params.id)],
          )
        ).rows[0];
        if (!u) throw new AppError(404, "User not found");
        await audit(
          c,
          req.user.id,
          d.suspended ? "user.suspend" : "user.restore",
          u.id,
          { reason: d.reason },
        );
      });
      res.json({ ok: true });
    }),
  );
  for (const operation of ["add", "deduct"])
    app.post(
      "/api/admin/wallet/" + operation,
      wrap(async (req, res) => {
        const d = parse(
          z.object({
            username,
            amount,
            reason,
            confirmed: z.literal(true),
            idempotencyKey: uuid,
          }),
          req.body,
        );
        const result = await tx(async (c) => {
          const u = (
            await c.query(
              "SELECT * FROM users WHERE username=$1 AND role='user' FOR UPDATE",
              [d.username],
            )
          ).rows[0];
          if (!u) throw new AppError(404, "Registered username not found");
          const ref = "admin:" + d.idempotencyKey;
          const previous = (
            await c.query("SELECT * FROM transactions WHERE reference=$1", [
              ref,
            ])
          ).rows[0];
          if (previous) {
            if (
              previous.user_id !== u.id ||
              previous.type !== "owner_" + operation ||
              !new Decimal(previous.amount).abs().eq(d.amount) ||
              previous.reason !== d.reason
            )
              throw new AppError(
                409,
                "Idempotency key was already used for another operation",
              );
            return { balance: u.balance, replayed: true };
          }
          const delta =
            operation === "deduct"
              ? new Decimal(d.amount).negated().toFixed(2)
              : d.amount;
          const balance = await wallet(
            c,
            u.id,
            delta,
            "owner_" + operation,
            d.reason,
            ref,
          );
          await audit(c, req.user.id, "wallet." + operation, u.id, {
            amount: d.amount,
            reason: d.reason,
            reference: ref,
          });
          return { balance };
        });
        res.json(result);
      }),
    );
  app.get(
    "/api/admin/settings",
    wrap(async (req, res) =>
      res.json({
        profit_percentage: (
          await pool.query(
            "SELECT value FROM settings WHERE key='profit_percentage'",
          )
        ).rows[0].value,
      }),
    ),
  );
  app.post(
    "/api/admin/settings",
    wrap(async (req, res) => {
      const d = parse(
        z.object({
          profitPercentage: z
            .union([z.string(), z.number()])
            .transform(String)
            .refine(
              (s) =>
                /^\d{1,4}(\.\d{1,4})?$/.test(s) && new Decimal(s).lte(1000),
              "Profit must be between 0 and 1000 percent",
            ),
        }),
        req.body,
      );
      await tx(async (c) => {
        const old = (
          await c.query(
            "SELECT value FROM settings WHERE key='profit_percentage' FOR UPDATE",
          )
        ).rows[0].value;
        await c.query(
          "UPDATE settings SET value=$1,updated_at=now() WHERE key='profit_percentage'",
          [d.profitPercentage],
        );
        await audit(c, req.user.id, "profit.update", "profit_percentage", {
          before: old,
          after: d.profitPercentage,
        });
      });
      res.json({ ok: true });
    }),
  );
  app.post(
    "/api/admin/services/sync",
    wrap(async (req, res) => {
      await P.syncServices(true);
      res.json({ ok: true });
    }),
  );
  app.get(
    "/api/admin/orders",
    wrap(async (req, res) => {
      const { q } = paging(req);
      res.json(
        await list(
          req,
          "orders o",
          "o.*,(SELECT username FROM users WHERE id=o.user_id) username",
          q
            ? [
                "(o.service_name ILIKE $1 OR o.id::text ILIKE $1 OR o.provider_order_id ILIKE $1 OR (SELECT username FROM users WHERE id=o.user_id) ILIKE $1)",
              ]
            : [],
          q ? ["%" + q + "%"] : [],
        ),
      );
    }),
  );
  app.post(
    "/api/admin/orders/:id/refresh",
    wrap(async (req, res) => {
      const order = await refreshOrder(id(req.params.id), req.user);
      await audit(pool, req.user.id, "order.refresh", order.id);
      res.json({ order });
    }),
  );
  app.post(
    "/api/admin/orders/:id/reconcile",
    wrap(async (req, res) => {
      const d = parse(
        z.object({
          action: z.enum(["attach", "refund"]),
          providerOrderId: z
            .string()
            .regex(/^\d{1,30}$/)
            .optional(),
          reason,
          confirmed: z.literal(true),
        }),
        req.body,
      );
      const oid = id(req.params.id);
      if (d.action === "attach") {
        if (!d.providerOrderId)
          throw new AppError(400, "Provider order ID required");
        await P.call("status", { order: d.providerOrderId });
      }
      const order = await tx(async (c) => {
        const o = (
          await c.query("SELECT * FROM orders WHERE id=$1 FOR UPDATE", [oid])
        ).rows[0];
        if (
          !o ||
          o.provider_order_id ||
          !["Needs review", "Submitting"].includes(o.status)
        )
          throw new AppError(
            409,
            "Only ambiguous unlinked orders can be reconciled",
          );
        if (d.action === "refund") {
          await wallet(
            c,
            o.user_id,
            o.selling_price,
            "refund",
            d.reason,
            "refund:reconcile:" + o.id,
          );
          await c.query(
            "UPDATE orders SET status='Failed',refunded=selling_price,updated_at=now() WHERE id=$1",
            [oid],
          );
        } else
          await c.query(
            "UPDATE orders SET provider_order_id=$1,status='Pending',updated_at=now() WHERE id=$2",
            [d.providerOrderId, oid],
          );
        await audit(c, req.user.id, "order.reconcile", oid, d);
        return (await c.query("SELECT * FROM orders WHERE id=$1", [oid]))
          .rows[0];
      });
      res.json({ order });
    }),
  );
  app.get(
    "/api/admin/deposits",
    wrap(async (req, res) =>
      res.json(
        await list(
          req,
          "deposits d",
          "d.*,(SELECT username FROM users WHERE id=d.user_id) username",
        ),
      ),
    ),
  );
  for (const action of ["approve", "reject"])
    app.post(
      "/api/admin/deposits/:id/" + action,
      wrap(async (req, res) => {
        const d = parse(
          z.object({
            note: z.string().trim().max(500).default(""),
            confirmed: z.literal(true),
          }),
          req.body,
        );
        const deposit = await tx(async (c) => {
          const dep = (
            await c.query("SELECT * FROM deposits WHERE id=$1 FOR UPDATE", [
              id(req.params.id),
            ])
          ).rows[0];
          if (!dep) throw new AppError(404, "Deposit not found");
          if (dep.status !== "pending")
            throw new AppError(409, "Deposit has already been reviewed");
          if (action === "approve")
            await wallet(
              c,
              dep.user_id,
              dep.amount,
              "deposit",
              "Verified UPI deposit " + dep.utr,
              "deposit:" + dep.id,
            );
          const updated = (
            await c.query(
              "UPDATE deposits SET status=$1,reviewed_by=$2,reviewed_at=now(),note=$3 WHERE id=$4 RETURNING *",
              [
                action === "approve" ? "approved" : "rejected",
                req.user.id,
                d.note,
                dep.id,
              ],
            )
          ).rows[0];
          await audit(c, req.user.id, "deposit." + action, dep.id, {
            amount: dep.amount,
            utr: dep.utr,
            note: d.note,
          });
          return updated;
        });
        res.json({ deposit });
      }),
    );
  app.get(
    "/api/admin/logs",
    wrap(async (req, res) => res.json(await list(req, "admin_logs", "*"))),
  );
  app.get(
    "/api/admin/tickets",
    wrap(async (req, res) =>
      res.json(
        await list(
          req,
          "tickets t",
          "t.*,(SELECT username FROM users WHERE id=t.user_id) username",
        ),
      ),
    ),
  );
  app.post(
    "/api/admin/tickets/:id/status",
    wrap(async (req, res) => {
      const d = parse(
        z.object({ status: z.enum(["open", "closed"]) }),
        req.body,
      );
      await tx(async (c) => {
        const r = await c.query(
          "UPDATE tickets SET status=$1,updated_at=now() WHERE id=$2 RETURNING id",
          [d.status, id(req.params.id)],
        );
        if (!r.rowCount) throw new AppError(404, "Ticket not found");
        await audit(c, req.user.id, "ticket." + d.status, req.params.id);
      });
      res.json({ ok: true });
    }),
  );
  app.use("/api", (req, res) =>
    res.status(404).json({ error: "API route not found" }),
  );
  app.use(
    express.static(path.join(__dirname, "../public"), {
      maxAge: production ? "1h" : 0,
      index: false,
    }),
  );
  app.get(
    [
      "/",
      "/login",
      "/register",
      "/owner-login",
      "/app",
      "/app/{*section}",
      "/owner",
      "/owner/{*section}",
    ],
    (req, res) => {
      res.set("Cache-Control", "no-cache");
      res.sendFile(path.join(__dirname, "../public/index.html"));
    },
  );
  app.use((req, res) => res.status(404).send("Page not found"));
  app.use((err, req, res, next) => {
    if (res.headersSent) return next(err);
    if (err instanceof z.ZodError)
      return res
        .status(400)
        .json({ error: err.issues.map((x) => x.message).join("; ") });
    if (err.code === "23505")
      return res
        .status(409)
        .json({ error: "Duplicate username, UTR, or operation reference" });
    if (err.type === "entity.parse.failed")
      return res.status(400).json({ error: "Invalid JSON body" });
    if (err.type === "entity.too.large")
      return res.status(413).json({ error: "Request too large" });
    if (!err.status) console.error("Request failed:", err.code || err.name);
    res.status(err.status || 500).json({
      error: err.status
        ? err.message
        : "An unexpected error occurred. Try again or contact support.",
    });
  });
  return app;
}
async function refreshOrder(oid, user) {
  const order = (await pool.query("SELECT * FROM orders WHERE id=$1", [oid]))
    .rows[0];
  if (!order || (user.role !== "owner" && order.user_id !== user.id))
    throw new AppError(404, "Order not found");
  if (!order.provider_order_id)
    throw new AppError(
      409,
      "Order needs owner review; no provider ID is available",
    );
  const result = await P.call("status", { order: order.provider_order_id });
  const statuses = new Set([
    "Pending",
    "Processing",
    "In progress",
    "Completed",
    "Partial",
    "Canceled",
    "Cancelled",
  ]);
  if (!statuses.has(result.status))
    throw new AppError(502, "Unrecognized provider order status");
  if (result.currency && result.currency !== "INR")
    throw new AppError(502, "Provider status currency mismatch");
  return tx(async (c) => {
    const o = (
      await c.query("SELECT * FROM orders WHERE id=$1 FOR UPDATE", [oid])
    ).rows[0];
    if (["Completed", "Canceled", "Cancelled", "Partial"].includes(o.status))
      return o;
    let refund = new Decimal(0);
    if (["Canceled", "Cancelled"].includes(result.status))
      refund = new Decimal(o.selling_price);
    if (result.status === "Partial") {
      if (
        !/^\d+$/.test(String(result.remains)) ||
        new Decimal(result.remains).gt(o.quantity)
      )
        throw new AppError(502, "Invalid remaining quantity");
      refund = new Decimal(o.selling_price)
        .mul(result.remains)
        .div(o.quantity)
        .toDecimalPlaces(2, Decimal.ROUND_DOWN);
    }
    const delta = refund.minus(o.refunded);
    if (delta.gt(0))
      await wallet(
        c,
        o.user_id,
        delta.toFixed(2),
        "refund",
        "Unfulfilled quantity refund for order #" + o.id,
        "refund:status:" + o.id,
      );
    const charge =
      result.charge !== undefined && /^\d+(\.\d+)?$/.test(String(result.charge))
        ? result.charge
        : null;
    return (
      await c.query(
        "UPDATE orders SET status=$1,start_count=$2,remains=$3,provider_charge=$4,refunded=$5,updated_at=now() WHERE id=$6 RETURNING *",
        [
          result.status,
          String(result.start_count ?? ""),
          String(result.remains ?? ""),
          charge,
          Decimal.max(refund, o.refunded).toFixed(2),
          oid,
        ],
      )
    ).rows[0];
  });
}
module.exports = { createApp, refreshOrder };
