"use strict";
const { test, before, after } = require("node:test"),
  assert = require("node:assert/strict"),
  request = require("supertest"),
  crypto = require("node:crypto");
const { providerFixture } = require("./provider-fixture.cjs");
if (!process.env.TEST_DATABASE_URL)
  throw Error(
    "Set TEST_DATABASE_URL to an empty dedicated PostgreSQL database. Tests reset all application data.",
  );
if (!/test/i.test(new URL(process.env.TEST_DATABASE_URL).pathname))
  throw Error("Test database name must contain test");
Object.assign(process.env, {
  NODE_ENV: "test",
  DATABASE_URL: process.env.TEST_DATABASE_URL,
  DATABASE_SSL: "disable",
  SESSION_SECRET: "integration-test-session-secret-32-plus",
  OWNER_USERNAME: "testowner",
  OWNER_PASSWORD: "test-owner-password-only",
  SMM_API_KEY: "test-fixture-only",
});
let app,
  pool,
  fixture,
  owner,
  a,
  b,
  csrfOwner,
  csrfA,
  csrfB,
  uid,
  firstOrder,
  deposit,
  ticket;
const post = (agent, path, token, data) =>
  agent
    .post("/api" + path)
    .set("x-csrf-token", token)
    .send(data);
const key = () => crypto.randomUUID();
before(async () => {
  fixture = await providerFixture();
  process.env.SMM_API_URL = fixture.url;
  ({ pool } = require("../src/db"));
  await pool.query("DROP SCHEMA public CASCADE;CREATE SCHEMA public");
  await require("../src/migrate").migrate();
  app = require("../src/app").createApp();
  owner = request.agent(app);
  a = request.agent(app);
  b = request.agent(app);
  csrfOwner = (await owner.get("/api/csrf")).body.token;
  csrfA = (await a.get("/api/csrf")).body.token;
  csrfB = (await b.get("/api/csrf")).body.token;
});
after(async () => {
  await fixture?.close();
  await pool?.end();
});
test("health, static assets, separate login pages, protected routes and missing routes", async () => {
  for (const url of [
    "/health",
    "/",
    "/login",
    "/register",
    "/owner-login",
    "/app/orders",
    "/owner/wallet",
    "/style.css",
    "/app.js",
    "/favicon.svg",
  ])
    assert.equal((await request(app).get(url)).status, 200, url);
  assert.equal((await request(app).get("/api/me")).status, 401);
  assert.equal((await request(app).get("/not-a-page")).status, 404);
});
test("CSRF rejects missing tokens and forged origins", async () => {
  assert.equal((await a.post("/api/auth/register").send({})).status, 403);
  process.env.APP_ORIGIN = "https://example.com";
  assert.equal(
    (
      await post(a, "/auth/login", csrfA, {}).set(
        "Origin",
        "https://evil.example",
      )
    ).status,
    403,
  );
  delete process.env.APP_ORIGIN;
});
test("registration validates passwords and uniqueness; cannot register reserved owner", async () => {
  assert.equal(
    (
      await post(a, "/auth/register", csrfA, {
        username: "alice",
        password: "strong-pass-123",
        confirmPassword: "mismatch",
      })
    ).status,
    400,
  );
  assert.equal(
    (
      await post(a, "/auth/register", csrfA, {
        username: "testowner",
        password: "strong-pass-123",
        confirmPassword: "strong-pass-123",
      })
    ).status,
    409,
  );
  let r = await post(a, "/auth/register", csrfA, {
    username: "Alice",
    password: "strong-pass-123",
    confirmPassword: "strong-pass-123",
  });
  assert.equal(r.status, 201);
  csrfA = r.body.csrf;
  uid = r.body.user.id;
  assert.equal(r.body.user.username, "alice");
  assert.equal(r.body.user.balance, "0.00");
  r = await post(b, "/auth/register", csrfB, {
    username: "alice",
    password: "strong-pass-123",
    confirmPassword: "strong-pass-123",
  });
  assert.equal(r.status, 409);
  r = await post(b, "/auth/register", csrfB, {
    username: "bob",
    password: "strong-pass-123",
    confirmPassword: "strong-pass-123",
  });
  assert.equal(r.status, 201);
  csrfB = r.body.csrf;
  const hash = (
    await pool.query("SELECT password_hash FROM users WHERE id=$1", [uid])
  ).rows[0].password_hash;
  assert.ok(hash.startsWith("$2"));
  assert.equal((await a.get("/api/admin/stats")).status, 403);
});
test("owner authentication is separate and role-based", async () => {
  assert.equal(
    (
      await post(owner, "/auth/login", csrfOwner, {
        username: "testowner",
        password: "test-owner-password-only",
      })
    ).status,
    401,
  );
  assert.equal(
    (
      await post(owner, "/auth/owner", csrfOwner, {
        username: "testowner",
        password: "wrong",
      })
    ).status,
    401,
  );
  const r = await post(owner, "/auth/owner", csrfOwner, {
    username: "testowner",
    password: "test-owner-password-only",
  });
  assert.equal(r.status, 200);
  csrfOwner = r.body.csrf;
  assert.equal(r.body.user.role, "owner");
  assert.equal((await owner.get("/api/admin/stats")).status, 200);
});
test("owner add balance is atomic, audited and idempotent", async () => {
  const body = {
    username: "alice",
    amount: "1000.00",
    reason: "Integration credit",
    confirmed: true,
    idempotencyKey: key(),
  };
  const rs = await Promise.all([
    post(owner, "/admin/wallet/add", csrfOwner, body),
    post(owner, "/admin/wallet/add", csrfOwner, body),
  ]);
  rs.forEach((r) => assert.equal(r.status, 200));
  assert.equal((await a.get("/api/me")).body.user.balance, "1000.00");
  assert.equal(
    (
      await pool.query("SELECT count(*) FROM transactions WHERE reference=$1", [
        "admin:" + body.idempotencyKey,
      ])
    ).rows[0].count,
    "1",
  );
  assert.equal(
    (
      await post(owner, "/admin/wallet/add", csrfOwner, {
        ...body,
        amount: "1001",
      })
    ).status,
    409,
  );
  assert.equal(
    (
      await post(owner, "/admin/wallet/add", csrfOwner, {
        ...body,
        idempotencyKey: key(),
        confirmed: false,
      })
    ).status,
    400,
  );
  assert.equal(
    (
      await post(owner, "/admin/wallet/add", csrfOwner, {
        ...body,
        idempotencyKey: key(),
        username: "nobody",
      })
    ).status,
    404,
  );
});
test("deductions never allow negative balances including concurrent operations", async () => {
  const body = {
    username: "alice",
    amount: "700",
    reason: "Concurrent deduction",
    confirmed: true,
  };
  const rs = await Promise.all([
    post(owner, "/admin/wallet/deduct", csrfOwner, {
      ...body,
      idempotencyKey: key(),
    }),
    post(owner, "/admin/wallet/deduct", csrfOwner, {
      ...body,
      idempotencyKey: key(),
    }),
  ]);
  assert.deepEqual(rs.map((r) => r.status).sort(), [200, 409]);
  assert.equal((await a.get("/api/me")).body.user.balance, "300.00");
});
test("UPI deposit submission persists and rejects duplicate UTR across users", async () => {
  let r = await post(a, "/deposits", csrfA, {
    amount: "500",
    utr: "bankref123456",
  });
  assert.equal(r.status, 201);
  deposit = r.body.deposit;
  assert.equal(deposit.utr, "BANKREF123456");
  assert.equal((await a.get("/api/me")).body.user.balance, "300.00");
  assert.equal(
    (await post(b, "/deposits", csrfB, { amount: "500", utr: "BANKREF123456" }))
      .status,
    409,
  );
  assert.equal((await a.get("/api/deposits")).body.total, 1);
});
test("concurrent deposit approvals credit exactly once", async () => {
  const rs = await Promise.all([
    post(owner, "/admin/deposits/" + deposit.id + "/approve", csrfOwner, {
      confirmed: true,
      note: "Verified bank statement",
    }),
    post(owner, "/admin/deposits/" + deposit.id + "/approve", csrfOwner, {
      confirmed: true,
    }),
  ]);
  assert.deepEqual(rs.map((r) => r.status).sort(), [200, 409]);
  assert.equal((await a.get("/api/me")).body.user.balance, "800.00");
  assert.equal(
    (
      await post(
        owner,
        "/admin/deposits/" + deposit.id + "/reject",
        csrfOwner,
        { confirmed: true },
      )
    ).status,
    409,
  );
});
test("rejection never credits funds", async () => {
  const dep = (
    await post(a, "/deposits", csrfA, { amount: "90", utr: "rejectref123456" })
  ).body.deposit;
  assert.equal(
    (
      await post(owner, "/admin/deposits/" + dep.id + "/reject", csrfOwner, {
        confirmed: true,
        note: "Not received",
      })
    ).status,
    200,
  );
  assert.equal((await a.get("/api/me")).body.user.balance, "800.00");
  assert.equal((await owner.get("/api/admin/deposits")).body.total, 2);
});
test("dynamic catalogue and 60 percent server-side pricing", async () => {
  const d = await a.get("/api/services");
  assert.equal(d.status, 200);
  assert.equal(d.body.services.length, 4);
  assert.equal(d.body.services.find((s) => s.id === "1").rate, "160.00");
  assert.equal(d.body.services.find((s) => s.id === "3").orderable, false);
  const q = await post(a, "/orders/quote", csrfA, {
    service: "1",
    quantity: 1000,
  });
  assert.equal(q.body.total, "160.00");
  assert.equal(
    (await post(a, "/orders/quote", csrfA, { service: "1", quantity: 1 }))
      .status,
    400,
  );
  assert.equal(
    (await post(a, "/orders/quote", csrfA, { service: "3", quantity: 1000 }))
      .status,
    400,
  );
  assert.equal(
    (await post(owner, "/admin/services/sync", csrfOwner, {})).status,
    200,
  );
});
test("order charge, immutable snapshot and duplicate-order protection", async () => {
  const body = {
    service: "1",
    link: "https://example.com/post",
    quantity: 1000,
    expectedTotal: "160.00",
    idempotencyKey: key(),
  };
  const calls = fixture.calls();
  const rs = await Promise.all([
    post(a, "/orders", csrfA, body),
    post(a, "/orders", csrfA, body),
  ]);
  assert.ok(
    rs.every((r) => [200, 201].includes(r.status)),
    JSON.stringify(rs.map((r) => r.body)),
  );
  assert.equal(fixture.calls(), calls + 1);
  firstOrder = rs.find((r) => r.body.order.provider_order_id)?.body.order;
  assert.ok(firstOrder);
  assert.equal(firstOrder.provider_cost, "100.000000");
  assert.equal(firstOrder.selling_price, "160.00");
  assert.equal((await a.get("/api/me")).body.user.balance, "640.00");
  assert.equal(
    (await post(b, "/orders/" + firstOrder.id + "/refresh", csrfB, {})).status,
    404,
  );
  assert.equal((await a.get("/api/orders?q=Default")).body.total, 1);
});
test("new markup changes future quotes but not past orders; stale quotes rejected", async () => {
  assert.equal(
    (
      await post(owner, "/admin/settings", csrfOwner, {
        profitPercentage: "75",
      })
    ).status,
    200,
  );
  assert.equal(
    (
      await post(owner, "/admin/settings", csrfOwner, {
        profitPercentage: "-10",
      })
    ).status,
    400,
  );
  assert.equal(
    (await a.get("/api/orders")).body.items[0].selling_price,
    "160.00",
  );
  const q = await post(a, "/orders/quote", csrfA, {
    service: "1",
    quantity: 1000,
  });
  assert.equal(q.body.total, "175.00");
  assert.equal(
    (
      await post(a, "/orders", csrfA, {
        service: "1",
        link: "https://example.com",
        quantity: 1000,
        expectedTotal: "160.00",
        idempotencyKey: key(),
      })
    ).status,
    409,
  );
  assert.equal(
    (await owner.get("/api/admin/settings")).body.profit_percentage,
    "75",
  );
});
test("status refresh and terminal idempotency", async () => {
  fixture.setStatus({ status: "Completed", remains: "0" });
  assert.equal(
    (await post(a, "/orders/" + firstOrder.id + "/refresh", csrfA, {})).body
      .order.status,
    "Completed",
  );
  assert.equal(
    (
      await post(
        owner,
        "/admin/orders/" + firstOrder.id + "/refresh",
        csrfOwner,
        {},
      )
    ).status,
    200,
  );
  assert.equal((await a.get("/api/dashboard")).body.stats.completed, "1");
});
test("explicit provider rejection refunds exactly once", async () => {
  fixture.setMode("reject");
  const body = {
    service: "1",
    link: "https://example.com",
    quantity: 1000,
    expectedTotal: "175.00",
    idempotencyKey: key(),
  };
  const r = await post(a, "/orders", csrfA, body);
  assert.equal(r.status, 201);
  assert.equal(r.body.order.status, "Failed");
  assert.equal(r.body.order.refunded, "175.00");
  await post(a, "/orders", csrfA, body);
  assert.equal((await a.get("/api/me")).body.user.balance, "640.00");
  fixture.setMode("ok");
});
test("ambiguous response reserves funds and requires audited owner reconciliation", async () => {
  fixture.setMode("ambiguous");
  const r = await post(a, "/orders", csrfA, {
    service: "1",
    link: "https://example.com",
    quantity: 1000,
    expectedTotal: "175.00",
    idempotencyKey: key(),
  });
  assert.equal(r.body.order.status, "Needs review");
  assert.equal((await a.get("/api/me")).body.user.balance, "465.00");
  const oid = r.body.order.id;
  assert.equal(
    (
      await post(owner, "/admin/orders/" + oid + "/reconcile", csrfOwner, {
        action: "refund",
        reason: "Verified absent at provider",
        confirmed: true,
      })
    ).status,
    200,
  );
  assert.equal(
    (
      await post(owner, "/admin/orders/" + oid + "/reconcile", csrfOwner, {
        action: "refund",
        reason: "Verified absent at provider",
        confirmed: true,
      })
    ).status,
    409,
  );
  assert.equal((await a.get("/api/me")).body.user.balance, "640.00");
  fixture.setMode("ok");
});
test("package order uses a one-time rate, not a per-1000 calculation", async () => {
  const r = await post(a, "/orders", csrfA, {
    service: "2",
    link: "https://example.com/package",
    quantity: 1000,
    expectedTotal: "35.00",
    idempotencyKey: key(),
  });
  assert.equal(r.status, 201);
  assert.equal(r.body.order.quantity, "1");
  assert.equal(r.body.order.provider_cost, "20.000000");
  assert.equal(r.body.order.selling_price, "35.00");
});
test("partial provider fulfillment gives an atomic proportional refund", async () => {
  const r = await post(a, "/orders", csrfA, {
    service: "1",
    link: "https://example.com/partial",
    quantity: 1000,
    expectedTotal: "175.00",
    idempotencyKey: key(),
  });
  const oid = r.body.order.id;
  fixture.setStatus({ status: "Partial", remains: "250", charge: "75.00" });
  const rs = await Promise.all([
    post(a, "/orders/" + oid + "/refresh", csrfA, {}),
    post(a, "/orders/" + oid + "/refresh", csrfA, {}),
  ]);
  assert.ok(rs.every((r) => r.status === 200));
  assert.equal(rs[0].body.order.refunded, "43.75");
  assert.equal(
    (
      await pool.query("SELECT count(*) FROM transactions WHERE reference=$1", [
        "refund:status:" + oid,
      ])
    ).rows[0].count,
    "1",
  );
  fixture.setStatus({ status: "Completed", remains: "0" });
});
test("support ticket messages, owner response, role isolation and closure", async () => {
  const r = await post(a, "/tickets", csrfA, {
    subject: "My test support request",
    body: "Please help with my order status.",
  });
  assert.equal(r.status, 201);
  ticket = r.body.ticket;
  assert.equal((await b.get("/api/tickets/" + ticket.id)).status, 404);
  assert.equal(
    (
      await post(owner, "/tickets/" + ticket.id + "/messages", csrfOwner, {
        body: "We are reviewing this.",
      })
    ).status,
    201,
  );
  assert.equal(
    (await a.get("/api/tickets/" + ticket.id)).body.messages.length,
    2,
  );
  assert.equal((await a.get("/api/tickets")).body.total, 1);
  assert.equal((await owner.get("/api/admin/tickets")).body.total, 1);
  assert.equal(
    (
      await post(owner, "/admin/tickets/" + ticket.id + "/status", csrfOwner, {
        status: "closed",
      })
    ).status,
    200,
  );
  assert.equal(
    (
      await post(a, "/tickets/" + ticket.id + "/messages", csrfA, {
        body: "Reply",
      })
    ).status,
    409,
  );
});
test("owner user search, per-user histories, audit logs, totals and transaction ledger", async () => {
  assert.equal((await owner.get("/api/admin/users?q=alice")).body.total, 1);
  const d = await owner.get("/api/admin/users/" + uid);
  assert.equal(d.status, 200);
  assert.ok(d.body.transactions.total > 0);
  assert.ok(d.body.orders.total > 0);
  assert.equal((await owner.get("/api/admin/orders")).status, 200);
  assert.ok((await owner.get("/api/admin/logs")).body.total >= 7);
  assert.equal((await a.get("/api/transactions")).status, 200);
  const actual = (await a.get("/api/me")).body.user.balance;
  const sum = (
    await pool.query(
      "SELECT sum(amount)::numeric(20,2) balance FROM transactions WHERE user_id=$1",
      [uid],
    )
  ).rows[0].balance;
  assert.equal(actual, sum);
  assert.equal(
    (await owner.get("/api/admin/stats")).body.stats.total_users,
    "2",
  );
});
test("suspension invalidates active sessions and prevents login", async () => {
  assert.equal(
    (
      await post(owner, "/admin/users/" + uid + "/suspend", csrfOwner, {
        suspended: true,
        reason: "Security test",
      })
    ).status,
    200,
  );
  assert.equal((await a.get("/api/me")).status, 401);
  csrfA = (await a.get("/api/csrf")).body.token;
  assert.equal(
    (
      await post(a, "/auth/login", csrfA, {
        username: "alice",
        password: "strong-pass-123",
      })
    ).status,
    403,
  );
  await post(owner, "/admin/users/" + uid + "/suspend", csrfOwner, {
    suspended: false,
    reason: "Restoring test access",
  });
  const r = await post(a, "/auth/login", csrfA, {
    username: "alice",
    password: "strong-pass-123",
  });
  assert.equal(r.status, 200);
  csrfA = r.body.csrf;
});
test("password update invalidates other sessions; owner password is env-only", async () => {
  const other = request.agent(app),
    t = (await other.get("/api/csrf")).body.token;
  assert.equal(
    (
      await post(other, "/auth/login", t, {
        username: "alice",
        password: "strong-pass-123",
      })
    ).status,
    200,
  );
  assert.equal(
    (
      await post(a, "/profile/password", csrfA, {
        currentPassword: "strong-pass-123",
        password: "new-strong-pass-123",
        confirmPassword: "new-strong-pass-123",
      })
    ).status,
    200,
  );
  assert.equal((await other.get("/api/me")).status, 401);
  assert.equal(
    (
      await post(owner, "/profile/password", csrfOwner, {
        currentPassword: "test-owner-password-only",
        password: "new-strong-pass-123",
        confirmPassword: "new-strong-pass-123",
      })
    ).status,
    400,
  );
  assert.equal((await a.get("/api/me")).status, 200);
});
test("insufficient funds, quantity bounds, missing media and unsafe links are rejected", async () => {
  assert.equal(
    (
      await post(b, "/orders", csrfB, {
        service: "1",
        link: "https://example.com",
        quantity: 1000,
        expectedTotal: "175.00",
        idempotencyKey: key(),
      })
    ).status,
    409,
  );
  assert.equal(
    (await post(a, "/orders/quote", csrfA, { service: "1", quantity: 100001 }))
      .status,
    400,
  );
  assert.equal(
    (
      await post(a, "/orders", csrfA, {
        service: "4",
        link: "https://example.com",
        quantity: 10,
        expectedTotal: "0.18",
        idempotencyKey: key(),
      })
    ).status,
    400,
  );
  assert.equal(
    (
      await post(a, "/orders", csrfA, {
        service: "1",
        link: "javascript:alert(1)",
        quantity: 1000,
        expectedTotal: "175.00",
        idempotencyKey: key(),
      })
    ).status,
    400,
  );
});
test("media-likers payload, paise rounding and canceled-order refund are correct", async () => {
  const before = (await a.get("/api/me")).body.user.balance;
  const r = await post(a, "/orders", csrfA, {
    service: "4",
    link: "https://example.com/mentions",
    media: "https://example.com/source",
    quantity: 10,
    expectedTotal: "0.18",
    idempotencyKey: key(),
  });
  assert.equal(r.status, 201);
  assert.equal(
    r.body.order.request_payload.media,
    "https://example.com/source",
  );
  assert.equal(r.body.order.selling_price, "0.18");
  fixture.setStatus({ status: "Canceled", remains: "10", charge: "0.00" });
  const refund = await post(
    a,
    "/orders/" + r.body.order.id + "/refresh",
    csrfA,
    {},
  );
  assert.equal(refund.body.order.refunded, "0.18");
  await post(a, "/orders/" + r.body.order.id + "/refresh", csrfA, {});
  assert.equal((await a.get("/api/me")).body.user.balance, before);
  fixture.setStatus({ status: "Completed", remains: "0", charge: "100.00" });
});
test("owner can link an uncertain order after verification and refresh its status", async () => {
  fixture.setMode("ambiguous");
  const r = await post(a, "/orders", csrfA, {
    service: "2",
    link: "https://example.com/reconcile",
    quantity: 1,
    expectedTotal: "35.00",
    idempotencyKey: key(),
  });
  assert.equal(r.body.order.status, "Needs review");
  const linked = await post(
    owner,
    "/admin/orders/" + r.body.order.id + "/reconcile",
    csrfOwner,
    {
      action: "attach",
      providerOrderId: "900000",
      reason: "Verified matching service and link in provider history",
      confirmed: true,
    },
  );
  assert.equal(linked.status, 200);
  assert.equal(linked.body.order.provider_order_id, "900000");
  assert.equal(
    (
      await post(
        owner,
        "/admin/orders/" + r.body.order.id + "/refresh",
        csrfOwner,
        {},
      )
    ).body.order.status,
    "Completed",
  );
  fixture.setMode("ok");
  assert.equal(
    (await owner.get("/api/admin/users/" + uid + "?offset=1&limit=1")).body
      .transactions.items.length,
    1,
  );
  assert.equal((await a.get("/api/orders?limit=2.5&offset=0.5")).status, 200);
});
test("SQL injection and markup input cannot alter queries; logout destroys session", async () => {
  assert.equal(
    (await owner.get("/api/admin/users?q=%27%20OR%201=1--")).body.total,
    0,
  );
  assert.equal(
    (
      await post(a, "/deposits", csrfA, {
        amount: "1; DROP TABLE users",
        utr: "anything123",
      })
    ).status,
    400,
  );
  assert.equal((await a.get("/api/unknown")).status, 404);
  assert.equal((await post(a, "/auth/logout", csrfA, {})).status, 200);
  assert.equal((await a.get("/api/me")).status, 401);
});
