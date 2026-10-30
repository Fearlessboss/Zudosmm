"use strict";
const { pool, tx } = require("./db");
const Decimal = require("decimal.js");
class AppError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
class ProviderRejected extends AppError {
  constructor(message) {
    super(502, message);
  }
}
async function call(action, params = {}) {
  const endpoint = process.env.SMM_API_URL || "https://mysmm.org/api/v2";
  if (
    process.env.NODE_ENV !== "test" &&
    endpoint !== "https://mysmm.org/api/v2"
  )
    throw new AppError(
      503,
      "Provider endpoint must be https://mysmm.org/api/v2",
    );
  if (!process.env.SMM_API_KEY)
    throw new AppError(503, "Provider credentials are not configured");
  let response, data;
  try {
    response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        key: process.env.SMM_API_KEY,
        action,
        ...params,
      }),
      signal: AbortSignal.timeout(20000),
    });
    data = await response.json();
  } catch {
    throw new AppError(
      502,
      "Provider response unavailable; no automatic order retry will be performed",
    );
  }
  if (!response.ok) throw new AppError(502, "Provider HTTP error");
  if (data && typeof data === "object" && data.error)
    throw new ProviderRejected(
      "Provider rejected request: " + String(data.error).slice(0, 300),
    );
  return data;
}
let currencyAt = 0;
async function verifyCurrency() {
  if (Date.now() - currencyAt < 60000) return;
  const b = await call("balance");
  if (
    b.currency !== "INR" ||
    (process.env.PROVIDER_CURRENCY || "INR") !== "INR"
  )
    throw new AppError(
      503,
      "Provider currency is not INR. Ordering disabled to prevent incorrect pricing.",
    );
  currencyAt = Date.now();
}
let syncing;
async function syncServices(force = false) {
  if (syncing) return syncing;
  const age = (
    await pool.query("SELECT max(updated_at) AS stamp FROM services_cache")
  ).rows[0].stamp;
  if (!force && age && Date.now() - new Date(age).getTime() < 300000) return;
  syncing = (async () => {
    const data = await call("services");
    if (!Array.isArray(data) || !data.length)
      throw new AppError(
        502,
        "Provider returned an empty or invalid catalogue",
      );
    const rows = data.filter(
      (s) =>
        s.service &&
        s.name &&
        s.category &&
        new Decimal(s.rate || 0).isFinite() &&
        new Decimal(s.rate || 0).gte(0),
    );
    if (!rows.length) throw new AppError(502, "No valid services received");
    await tx(async (c) => {
      await c.query("UPDATE services_cache SET active=false");
      await c.query(
        `INSERT INTO services_cache(service_id,payload,active,updated_at) SELECT value->>'service',value,true,now() FROM jsonb_array_elements($1::jsonb) ON CONFLICT(service_id) DO UPDATE SET payload=EXCLUDED.payload,active=true,updated_at=now()`,
        [JSON.stringify(rows)],
      );
    });
  })().finally(() => {
    syncing = null;
  });
  return syncing;
}
const supported = new Set(["Default", "Package", "Mentions Media Likers"]);
function money(x) {
  return new Decimal(x).toDecimalPlaces(2, Decimal.ROUND_HALF_UP).toFixed(2);
}
function price(service, quantity, profit) {
  const cost = new Decimal(service.rate).mul(
    service.type === "Package" ? 1 : new Decimal(quantity).div(1000),
  );
  return {
    cost: cost.toFixed(6),
    selling: cost
      .mul(new Decimal(profit).div(100).plus(1))
      .toDecimalPlaces(2, Decimal.ROUND_CEIL)
      .toFixed(2),
  };
}
async function catalogue() {
  let warning = null;
  try {
    await syncServices();
  } catch (e) {
    warning = e.message;
  }
  const rows = (
    await pool.query(
      "SELECT payload,updated_at FROM services_cache WHERE active=true ORDER BY service_id::bigint",
    )
  ).rows;
  const profit = (
    await pool.query("SELECT value FROM settings WHERE key='profit_percentage'")
  ).rows[0].value;
  if (!rows.length && warning) throw new AppError(503, warning);
  return {
    profit_percentage: profit,
    warning,
    services: rows.map(({ payload: s, updated_at }) => ({
      id: String(s.service),
      name: s.name,
      category: s.category,
      type: s.type,
      description: String(
        s.desc ||
          s.description ||
          "No additional description supplied by provider.",
      ).replace(/<[^>]*>/g, ""),
      rate: price(s, s.type === "Package" ? 1 : 1000, profit).selling,
      min: s.min,
      max: s.max,
      orderable: supported.has(s.type),
      refill: !!s.refill,
      updated_at,
    })),
  };
}
module.exports = {
  call,
  verifyCurrency,
  syncServices,
  catalogue,
  price,
  money,
  supported,
  AppError,
  ProviderRejected,
};
