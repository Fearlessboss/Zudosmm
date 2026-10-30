"use strict";
// Non-spending browser smoke test. Run against your LOCAL verification deployment only.
const { chromium, expect } = require("@playwright/test");
const fs = require("node:fs");
const base = process.env.TEST_BASE_URL || "https://localhost:3443";
if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(base))
  throw Error("Browser tests only run against a local verification deployment");
async function main() {
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox"],
  });
  const ctx = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1080 },
  });
  const page = await ctx.newPage(),
    errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !/401|Failed to load resource/.test(m.text()))
      errors.push(m.text());
  });
  const results = [];
  const username = "browser_" + Date.now().toString().slice(-10),
    password = "browser-test-password-123";
  const check = async (name, fn) => {
    await fn();
    results.push({ name, status: "passed" });
    console.log("PASS", name);
  };
  const visit = async (path) => {
    await page.goto(base + path);
    await expect(page.locator(".loading")).toHaveCount(0, { timeout: 45000 });
    await expect(page.locator(".error-box")).toHaveCount(0);
  };
  const responsive = async (width) => {
    await page.setViewportSize({ width, height: width < 600 ? 844 : 1080 });
    await page.waitForTimeout(100);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth + 1,
    );
    expect(overflow, "No page-wide horizontal overflow at " + width).toBe(
      false,
    );
  };
  await check(
    "Landing renders on desktop and mobile without CSP errors",
    async () => {
      await visit("/");
      await expect(page.locator("h1")).toContainText("Big ambitions");
      fs.mkdirSync(
        process.env.TEST_ARTIFACT_DIR ||
          require("node:path").resolve("test-results"),
        { recursive: true },
      );
      await page.screenshot({
        path:
          (process.env.TEST_ARTIFACT_DIR ||
            require("node:path").resolve("test-results")) +
          "/landing-desktop.png",
        fullPage: true,
      });
      for (const w of [1440, 1024, 768, 390, 320]) await responsive(w);
      await page.setViewportSize({ width: 1440, height: 1080 });
    },
  );
  await check(
    "Registration creates a real PostgreSQL account and secure session",
    async () => {
      await visit("/register");
      await page.getByLabel("Username", { exact: true }).fill(username);
      await page.getByLabel("Password", { exact: true }).fill(password);
      await page.getByLabel("Confirm password", { exact: true }).fill(password);
      await page
        .getByRole("button", { name: "Create account", exact: true })
        .click();
      await expect(page.locator("h1")).toContainText("Good to see you");
      const cookies = await ctx.cookies();
      const sid = cookies.find((c) => c.name === "__Host-zudo.sid");
      expect(sid).toBeTruthy();
      expect(sid.secure).toBe(true);
      expect(sid.httpOnly).toBe(true);
      await page.screenshot({
        path:
          (process.env.TEST_ARTIFACT_DIR ||
            require("node:path").resolve("test-results")) +
          "/dashboard-desktop.png",
        fullPage: true,
      });
    },
  );
  await check("Dashboard mobile navigation and all user sections", async () => {
    await responsive(390);
    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(page.locator(".sidebar")).toHaveClass(/open/);
    await page.locator('.sidebar nav a[href="/app/orders"]').click();
    await expect(page.locator("h1")).toContainText("Your orders");
    for (const section of [
      "dashboard",
      "transactions",
      "profile",
      "orders",
      "support",
      "funds",
    ]) {
      await visit("/app/" + section);
      await responsive(390);
    }
    await visit("/app/dashboard");
    await page.screenshot({
      path:
        (process.env.TEST_ARTIFACT_DIR ||
          require("node:path").resolve("test-results")) +
        "/dashboard-mobile.png",
      fullPage: true,
    });
    await page.setViewportSize({ width: 1440, height: 1080 });
  });
  await check(
    "Live catalogue, search, filters and server-side quote (no paid order)",
    async () => {
      await visit("/app/services");
      await expect(
        page.locator("#services-table tbody tr").first(),
      ).toBeVisible({ timeout: 45000 });
      const search = page.locator("#service-search");
      await search.fill("does-not-exist-very-specific");
      await expect(page.locator("#services-table")).toContainText(
        "No matching services",
      );
      await search.fill("");
      const category = page.locator("#category-filter");
      const selectedCategory =
        (await category.locator("option").nth(1).getAttribute("value")) ||
        (await category.locator("option").nth(1).textContent());
      await category.selectOption({ label: selectedCategory });
      const visibleCategories = await page
        .locator("#services-table tbody tr td:nth-child(2)")
        .allTextContents();
      expect(visibleCategories.length).toBeGreaterThan(0);
      expect(
        visibleCategories.every(
          (text) => text.trim() === selectedCategory.trim(),
        ),
      ).toBe(true);
      await category.selectOption("");
      await page.locator('[data-action="select-service"]').first().click();
      await expect(page.locator("#order-total")).not.toHaveText("—", {
        timeout: 30000,
      });
      await expect(page.locator("#order-total")).not.toHaveText(
        "Calculating…",
        { timeout: 30000 },
      );
      await expect(page.locator("#place-order")).toBeEnabled();
      await responsive(390);
      await page.setViewportSize({ width: 1440, height: 1080 });
      await page.screenshot({
        path:
          (process.env.TEST_ARTIFACT_DIR ||
            require("node:path").resolve("test-results")) +
          "/new-order-desktop.png",
        fullPage: true,
      });
    },
  );
  await check(
    "Deposit submission and support forms persist without crediting unverified funds",
    async () => {
      await visit("/app/funds");
      await page.getByLabel("Amount paid (INR)").fill("50.00");
      await page.getByLabel("UTR / Transaction ID").fill("LOCAL" + Date.now());
      await page.locator('#deposit-form input[type="checkbox"]').check();
      await page
        .getByRole("button", { name: "Submit for verification" })
        .click();
      await expect(page.locator("tbody")).toContainText("pending");
      await visit("/app/support");
      await page
        .getByLabel("Subject", { exact: true })
        .fill("Browser verification ticket");
      await page
        .getByLabel("Message", { exact: true })
        .fill("Local verification only. No real payment has been sent.");
      await page
        .getByRole("button", { name: "Send message", exact: true })
        .click();
      await expect(page.locator("tbody")).toContainText(
        "Browser verification ticket",
      );
    },
  );
  const ownerCtx = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1440, height: 1080 },
    }),
    op = await ownerCtx.newPage();
  op.on("pageerror", (e) => errors.push(e.message));
  await check(
    "Separate owner login with environment-supplied credentials",
    async () => {
      if (!process.env.OWNER_PASSWORD)
        throw Error("OWNER_PASSWORD is required for browser smoke testing");
      await op.goto(base + "/owner-login");
      await op
        .getByLabel("Username", { exact: true })
        .fill(process.env.OWNER_USERNAME || "zudo");
      await op
        .getByLabel("Password", { exact: true })
        .fill(process.env.OWNER_PASSWORD);
      await op.getByRole("button", { name: "Enter owner workspace" }).click();
      await expect(op.locator("h1")).toContainText("The big picture", {
        timeout: 30000,
      });
      await op.screenshot({
        path:
          (process.env.TEST_ARTIFACT_DIR ||
            require("node:path").resolve("test-results")) +
          "/owner-desktop.png",
        fullPage: true,
      });
    },
  );
  await check(
    "Owner add and deduct balance forms and confirmation dialog",
    async () => {
      await op.goto(base + "/owner/wallet");
      const add = op.locator('.wallet-form[data-operation="add"]');
      await add.locator('input[name="add-username"]').fill(username);
      await add.locator('input[name="add-amount"]').fill("100");
      await add.locator("textarea").fill("Local browser verification credit");
      await add.locator('input[type="checkbox"]').check();
      await add
        .getByRole("button", { name: "Add balance", exact: true })
        .click();
      await op.locator('#confirm-dialog button[value="yes"]').click();
      await expect(add.locator(".wallet-result")).toContainText("100.00");
      const deduct = op.locator('.wallet-form[data-operation="deduct"]');
      await deduct.locator('input[name="deduct-username"]').fill(username);
      await deduct.locator('input[name="deduct-amount"]').fill("25");
      await deduct
        .locator("textarea")
        .fill("Local browser verification deduction");
      await deduct.locator('input[type="checkbox"]').check();
      await deduct
        .getByRole("button", { name: "Deduct balance", exact: true })
        .click();
      await op.locator('#confirm-dialog button[value="yes"]').click();
      await expect(deduct.locator(".wallet-result")).toContainText("75.00");
    },
  );
  await check(
    "Owner deposit rejection, support response and all owner pages",
    async () => {
      await op.goto(base + "/owner/deposits");
      await op.locator('[data-action="reject-deposit"]').first().click();
      await op
        .getByLabel("Review note")
        .fill("Local browser test: no real payment");
      await op.locator('#deposit-action-form input[type="checkbox"]').check();
      await op.locator('#deposit-action-form button[type="submit"]').click();
      await expect(op.locator("tbody")).toContainText("rejected");
      for (const s of [
        "dashboard",
        "users",
        "orders",
        "profit",
        "services",
        "support",
        "logs",
        "profile",
      ]) {
        await op.goto(base + "/owner/" + s);
        await expect(op.locator(".loading")).toHaveCount(0, { timeout: 45000 });
        await expect(op.locator(".error-box")).toHaveCount(0);
        await op.setViewportSize({ width: 390, height: 844 });
        expect(
          await op.evaluate(
            () => document.documentElement.scrollWidth > innerWidth + 1,
          ),
          s + " mobile overflow",
        ).toBe(false);
        await op.setViewportSize({ width: 1440, height: 1080 });
      }
      await op.goto(base + "/owner/support");
      await op.locator('[data-action="open-ticket"]').first().click();
      await op
        .getByLabel("Your reply")
        .fill("Local verification completed successfully.");
      await op.getByRole("button", { name: "Send reply", exact: true }).click();
      await expect(op.locator(".ticket-message")).toHaveCount(2);
    },
  );
  await check("Refresh persistence and logout", async () => {
    await visit("/app/dashboard");
    await expect(page.locator(".stat-value").first()).toContainText("75.00");
    await page.reload();
    await expect(page.locator("h1")).toContainText("Good to see you");
    await page.locator('[data-action="logout"]').click();
    await expect(page.locator("h1")).toContainText("Big ambitions");
    await page.goto(base + "/app/dashboard");
    await expect(page.locator("h1")).toContainText("Welcome back");
  });
  expect(errors, "Browser runtime or CSP errors").toEqual([]);
  const out =
    process.env.TEST_ARTIFACT_DIR ||
    require("node:path").resolve("test-results");
  fs.writeFileSync(
    out + "/browser-results.json",
    JSON.stringify(
      { tests: results, browserErrors: errors, liveOrdersPlaced: 0 },
      null,
      2,
    ),
  );
  await browser.close();
  console.log("All browser checks passed; no live orders were placed.");
}
main().catch((e) => {
  console.error(e);
  process.exit(1);
});
