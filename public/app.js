"use strict";
const root = document.querySelector("#root");
let user = null,
  csrf = "",
  catalog = null,
  currentSection = "",
  epoch = 0,
  quote = null,
  orderKey = null;
const state = { offset: 0, limit: 25, q: "", category: "", ticket: null };
const esc = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const money = (x) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(Number(x || 0));
const date = (x) =>
  new Date(x).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });
const paths = {
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  plus: "M12 5v14 M5 12h14",
  layers: "m12 3 10 6-10 6L2 9z M2 14l10 6 10-6 M2 18l10 6 10-6",
  orders: "M8 3h8v4H8z M7 5H4v17h16V5h-3 M8 12h8 M8 17h5",
  wallet: "M3 6h17v15H3z M3 6V3h14v3 M15 11h7v6h-7z M18 14h1",
  history: "M3 11a9 9 0 1 1 2 7 M3 4v7h7 M12 7v6l4 2",
  support:
    "M4 14v-3a8 8 0 0 1 16 0v3 M4 12H2v7h4v-7z M20 12h2v7h-4v-7z M19 19v3h-7",
  user: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M4 22v-3a8 8 0 0 1 16 0v3",
  logout: "M9 3H3v18h6 M9 12h13 M17 7l5 5-5 5",
  arrow: "M4 12h16 M14 6l6 6-6 6",
  check: "m5 12 4 4L20 5",
  shield: "m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6z m-4 10 3 3 5-6",
  bolt: "m13 2-9 12h7l-1 8L21 9h-8z",
  chart: "M3 3v18h19 M7 15l5-5 4 3 6-8",
  clock: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M12 6v6l4 2",
  refresh:
    "M20 7a9 9 0 0 0-15-2L2 8 M2 2v6h6 M4 17a9 9 0 0 0 15 2l3-3 M22 22v-6h-6",
  menu: "M3 6h18 M3 12h18 M3 18h18",
  settings:
    "M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2",
  users:
    "M9 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M2 22v-3a7 7 0 0 1 14 0v3 M17 4a4 4 0 0 1 0 8 M18 15a5 5 0 0 1 4 5v2",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12 M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  minus: "M5 12h14",
};
function icon(n) {
  return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[n] || paths.grid}"/></svg>`;
}
function brand() {
  return '<a href="/" class="brand" data-link><span class="brand-mark">Z</span><span><strong>ZUDO</strong><small>SMM PANEL</small></span></a>';
}
function button(label, href, ic = "arrow", secondary = false) {
  return `<a href="${href}" data-link class="button${secondary ? " secondary" : ""}">${esc(label)} ${icon(ic)}</a>`;
}
function toast(text, error = false) {
  const el = document.createElement("div");
  el.className = "toast" + (error ? " error" : "");
  el.textContent = text;
  document.querySelector("#toasts").append(el);
  setTimeout(() => el.remove(), 6500);
}
async function api(url, method = "GET", data) {
  const res = await fetch("/api" + url, {
    method,
    headers: {
      ...(data ? { "Content-Type": "application/json" } : {}),
      ...(method !== "GET" ? { "x-csrf-token": csrf } : {}),
    },
    credentials: "same-origin",
    ...(data ? { body: JSON.stringify(data) } : {}),
  });
  const json = await res.json();
  if (!res.ok)
    throw Object.assign(new Error(json.error || "Request failed"), {
      status: res.status,
    });
  if (json.csrf) csrf = json.csrf;
  return json;
}
async function token() {
  csrf = (await api("/csrf")).token;
}
async function confirmAction(title, text) {
  const dlg = document.querySelector("#confirm-dialog");
  document.querySelector("#confirm-title").textContent = title;
  document.querySelector("#confirm-text").textContent = text;
  dlg.returnValue = "";
  dlg.showModal();
  return new Promise((resolve) =>
    dlg.addEventListener("close", () => resolve(dlg.returnValue === "yes"), {
      once: true,
    }),
  );
}
function navigate(url) {
  quoteEpoch++;
  clearTimeout(quoteTimer);
  history.pushState({}, "", url);
  state.offset = 0;
  state.q = "";
  state.category = "";
  state.ticket = null;
  render();
  window.scrollTo(0, 0);
}
function loading() {
  return '<div class="loading"><span class="spinner"></span> Loading your workspace…</div>';
}
function empty(
  title = "Nothing here yet",
  text = "Your activity will appear here.",
  ic = "layers",
) {
  return `<div class="empty">${icon(ic)}<strong>${esc(title)}</strong><p>${esc(text)}</p></div>`;
}
function badge(s) {
  const t = String(s).toLowerCase();
  const cls = ["completed", "approved", "active", "closed"].includes(t)
    ? "good"
    : ["failed", "rejected", "suspended", "canceled", "cancelled"].includes(t)
      ? "bad"
      : ["pending", "needs review", "submitting", "partial", "open"].includes(t)
        ? "warn"
        : "";
  return `<span class="badge ${cls}">${esc(s)}</span>`;
}
function stat(label, value, ic, note = "Updated from your account") {
  return `<div class="panel stat"><div class="stat-top">${esc(label)}<span class="stat-icon">${icon(ic)}</span></div><div class="stat-value">${esc(value)}</div><div class="stat-note">${esc(note)}</div></div>`;
}
function title(h, p, action = "") {
  return `<div class="page-title"><div><h1>${esc(h)}</h1><p>${esc(p)}</p></div>${action}</div>`;
}
function field(label, name, type = "text", attrs = "", help = "") {
  return `<div class="field"><label for="${name}">${esc(label)}</label>${type === "textarea" ? `<textarea id="${name}" name="${name}" ${attrs}></textarea>` : `<input id="${name}" name="${name}" type="${type}" ${attrs}>`}${help ? `<small>${esc(help)}</small>` : ""}</div>`;
}
function pass(label, name, autocomplete = "current-password") {
  return `<div class="field"><label for="${name}">${label}</label><div class="password-wrap"><input type="password" name="${name}" id="${name}" required autocomplete="${autocomplete}" minlength="10" maxlength="72"><button class="password-toggle" type="button" data-action="toggle-password" data-target="${name}" aria-label="Show password">${icon("eye")}</button></div></div>`;
}
function landing() {
  document.title = "ZUDO SMM PANEL — Social, elevated.";
  root.innerHTML = `<div class="landing"><nav class="landing-nav">${brand()}<div class="nav-links"><a href="#features">The platform</a><a href="/login" data-link>Sign in</a>${button("Get started", "/register")}</div></nav><main id="main" class="landing-main"><span class="pill hero-badge"><span class="dot"></span> YOUR NEXT CHAPTER IN SOCIAL</span><h1 class="hero-title">Big ambitions.<br><span class="gradient-text">One powerful panel.</span></h1><p class="hero-copy">Your social operations deserve better. Discover services, manage orders, and stay in control — all from one beautifully simple workspace.</p><div class="row hero-actions">${button("Create your account", "/register", "arrow")}${button("Explore the platform", "#features", "layers", true)}</div><p class="hero-fine">Transparent pricing · Secure wallet · Dedicated support</p><div class="product-preview" aria-label="Illustrative preview of the ZUDO workspace"><div class="preview-top"><span class="window-dot"></span><span class="window-dot"></span><span class="window-dot"></span><span class="sr-only">Illustrative dashboard</span><span> &nbsp; ZUDO / Your workspace</span></div><div class="preview-grid"><div class="preview-side">${brand()}<p class="active">◈ &nbsp; Dashboard</p><p>＋ &nbsp; New order</p><p>▤ &nbsp; Services</p><p>◷ &nbsp; My orders</p><p>▣ &nbsp; My wallet</p></div><div class="preview-body"><div class="row between"><h2>Your growth, organized.</h2><span class="pill">Workspace preview</span></div><div class="preview-stats"><div class="preview-stat"><small>YOUR WALLET</small><strong>₹0.00</strong></div><div class="preview-stat"><small>YOUR ORDERS</small><strong>0</strong></div><div class="preview-stat"><small>READY WHEN YOU ARE</small><strong>Let's go ↗</strong></div></div><div class="preview-chart" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div><p class="preview-note">Illustrative interface — not customer results or performance claims.</p></div></div></div><div class="trust-row"><span>◇ &nbsp; Secure by design</span><span>↗ &nbsp; Live service catalogue</span><span>◎ &nbsp; Clear order tracking</span><span>▧ &nbsp; INR wallet</span></div></main><section class="features" id="features"><div class="section-heading"><span class="eyebrow">BUILT FOR YOUR WORKFLOW</span><h2>Less busywork. <span class="gradient-text">More control.</span></h2><p>Everything you need, without the complexity.</p></div><div class="features-grid"><article class="panel feature"><span class="feature-icon">${icon("bolt")}</span><h3>From discovery to delivery.</h3><p>Browse a live catalogue, find the right service, and place an order with a clear, upfront quote.</p></article><article class="panel feature"><span class="feature-icon">${icon("wallet")}</span><h3>Your wallet. Your visibility.</h3><p>Fund your wallet with UPI. Track each verified deposit, order charge, and balance adjustment in one place.</p></article><article class="panel feature"><span class="feature-icon">${icon("shield")}</span><h3>A workspace you can trust.</h3><p>Protected accounts, transparent order statuses, and a support conversation whenever you need assistance.</p></article></div></section><section class="cta"><span class="eyebrow">YOUR WORKSPACE IS WAITING</span><h2>Make your next move a better one.</h2><p>Create your account, explore available services, and take charge of your social workflow.</p>${button("Start with ZUDO", "/register")}</section><footer class="footer">${brand()}<span>© ${new Date().getFullYear()} ZUDO SMM PANEL. All rights reserved.</span><a href="/owner-login" data-link>Owner access ↗</a></footer></div>`;
  // Decorative bars use static CSS classes rather than inline styles under CSP.
  root.querySelectorAll(".preview-chart i").forEach((el, i) => {
    el.removeAttribute("style");
    el.className = "bar-" + i;
  });
}
function authPage(mode) {
  const owner = mode === "owner",
    register = mode === "register";
  document.title =
    (owner ? "Owner access" : register ? "Create account" : "Sign in") +
    " — ZUDO";
  root.innerHTML = `<main id="main" class="auth"><section class="auth-art">${brand()}<div class="auth-message"><span class="pill"><span class="dot"></span> A BETTER WAY TO WORK</span><h2>Everything social.<br><span class="gradient-text">One workspace.</span></h2><p>Less friction. More visibility.<br>A premium panel built around your workflow.</p><div class="row wrap auth-pills"><span class="pill">${icon("shield")} Secure accounts</span><span class="pill">${icon("wallet")} INR wallet</span></div></div><p class="api-note">ZUDO SMM PANEL &nbsp; / &nbsp; Social, elevated.</p></section><section class="auth-body"><div class="auth-card"><span class="eyebrow">${owner ? "RESTRICTED WORKSPACE" : register ? "WELCOME TO ZUDO" : "YOUR WORKSPACE AWAITS"}</span><h1>${owner ? "Owner access" : register ? "Start something great." : "Welcome back."}</h1><p>${owner ? "Sign in securely to manage your platform." : register ? "One account. Your entire social workflow." : "Sign in to pick up where you left off."}</p><form id="auth-form" data-mode="${mode}">${field("Username", "username", "text", 'required minlength="3" maxlength="32" pattern="[A-Za-z0-9_]+" autocomplete="username" placeholder="Your username"')}${pass("Password", "password", register ? "new-password" : "current-password")}${register ? pass("Confirm password", "confirmPassword", "new-password") : ""}${register ? '<p class="api-note">Use 10–72 characters. Choose a unique password you don’t use elsewhere.</p>' : ""}<button class="button block" type="submit">${owner ? "Enter owner workspace" : register ? "Create account" : "Sign in"} ${icon("arrow")}</button></form><p class="auth-bottom">${owner ? '<a href="/login" data-link>← Back to customer sign in</a>' : register ? 'Already have an account? <a href="/login" data-link>Sign in</a>' : 'New to ZUDO? <a href="/register" data-link>Create an account</a>'}</p>${!owner ? '<p class="auth-bottom"><a href="/" data-link>← Back to home</a></p>' : ""}</div></section></main>`;
}
const userNav = [
  ["dashboard", "Dashboard", "grid"],
  ["new-order", "New Order", "plus"],
  ["services", "Services", "layers"],
  ["orders", "My Orders", "orders"],
  ["funds", "Add Funds", "wallet"],
  ["transactions", "Transaction History", "history"],
  ["support", "Support", "support"],
  ["profile", "Profile", "user"],
];
const ownerNav = [
  ["dashboard", "Overview", "grid"],
  ["users", "User Management", "users"],
  ["wallet", "Wallet Management", "wallet"],
  ["orders", "All Orders", "orders"],
  ["deposits", "Deposit Requests", "history"],
  ["profit", "Profit Settings", "chart"],
  ["services", "Service Catalogue", "layers"],
  ["support", "Support Inbox", "support"],
  ["logs", "Audit Log", "shield"],
  ["profile", "Profile", "user"],
];
function shell() {
  const owner = user.role === "owner",
    base = owner ? "/owner" : "/app",
    nav = owner ? ownerNav : userNav;
  root.innerHTML = `<div class="shell"><div class="sidebar-shade" data-action="close-menu"></div><aside class="sidebar">${brand()}<p class="nav-caption">${owner ? "OWNER WORKSPACE" : "YOUR WORKSPACE"}</p><nav aria-label="Main navigation">${nav.map(([key, label, ic]) => `<a href="${base}/${key}" data-link class="nav-item ${key === currentSection ? "active" : ""}">${icon(ic)} ${label}</a>`).join("")}</nav><div class="sidebar-bottom"><div class="sidebar-help"><h3>Let's keep you moving.</h3><p>Your support workspace is just a click away.</p><a href="${base}/support" data-link class="button secondary small block">${icon("support")} Contact support</a></div><button type="button" class="nav-item" data-action="logout">${icon("logout")} Sign out</button></div></aside><div class="shell-body"><header class="topbar"><div class="row"><button type="button" class="icon-button mobile-menu" data-action="open-menu" aria-label="Open navigation">${icon("menu")}</button><div class="breadcrumb">Workspace <span>/ &nbsp; ${esc(nav.find((n) => n[0] === currentSection)?.[1] || "Overview")}</span></div></div><div class="row"><span class="online"><span class="dot"></span> &nbsp; Secure session</span><a href="${base}/${owner ? "wallet" : "funds"}" data-link class="balance-chip">${owner ? "Owner console" : "Wallet"} ${owner ? "" : `<strong>${money(user.balance)}</strong>`}</a><div class="avatar">${esc(user.username.slice(0, 2).toUpperCase())}</div><div><div class="top-name">${esc(user.username)}</div><div class="top-role">${owner ? "Platform owner" : "Member account"}</div></div></div></header><main class="content" id="main"><div id="page">${loading()}</div><footer class="app-footer"><span>© ${new Date().getFullYear()} ZUDO SMM PANEL</span><span>Your workspace. Beautifully connected.</span></footer></main></div></div>`;
}
function pager(data) {
  return `<div class="pagination"><span>${data.total ? data.offset + 1 : 0}–${Math.min(data.offset + data.limit, data.total)} of ${data.total} records</span><div class="pager-buttons"><button class="button secondary small" data-action="page-prev" ${data.offset <= 0 ? "disabled" : ""}>Previous</button><button class="button secondary small" data-action="page-next" ${data.offset + data.limit >= data.total ? "disabled" : ""}>Next</button></div></div>`;
}
function table(headers, rows, none = "No records yet") {
  return rows.length
    ? `<div class="table-wrap"><table><thead><tr>${headers.map((h) => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`
    : empty(none);
}
function txTable(rows) {
  return table(
    ["Transaction", "Date", "Amount", "Balance"],
    rows.map(
      (t) =>
        `<tr><td><span class="table-title">${esc(t.reason)}</span><span class="table-sub">#${esc(t.id)} · ${esc(t.type.replaceAll("_", " "))}</span></td><td>${date(t.created_at)}</td><td class="${Number(t.amount) > 0 ? "positive" : "negative"}">${Number(t.amount) > 0 ? "+" : ""}${money(t.amount)}</td><td>${money(t.balance_after)}</td></tr>`,
    ),
    "No transactions yet",
  );
}
function orderTable(rows, owner = false) {
  return table(
    [
      "Order / Service",
      ...(owner ? ["User", "Provider ID"] : []),
      "Quantity",
      "Charge",
      ...(owner ? ["Provider cost", "Profit snapshot"] : []),
      "Status",
      "Date",
      "Actions",
    ],
    rows.map(
      (o) =>
        `<tr><td><span class="table-title">#${esc(o.id)} · ${esc(o.service_name)}</span><span class="table-sub">${esc(o.link)}</span>${Number(o.refunded) > 0 ? `<br><span class="positive">Refunded ${money(o.refunded)}</span>` : ""}</td>${owner ? `<td>${esc(o.username || o.user_id)}</td><td class="mono">${esc(o.provider_order_id || "Not linked")}</td>` : ""}<td>${esc(o.quantity)}</td><td>${money(o.selling_price)}</td>${owner ? `<td>${money(o.provider_cost)}</td><td>${esc(o.profit_percentage)}%</td>` : ""}<td>${badge(o.status)}</td><td>${date(o.created_at)}</td><td>${o.provider_order_id ? `<button class="button secondary small" data-action="refresh-order" data-id="${esc(o.id)}">${icon("refresh")} Refresh</button>` : owner && ["Needs review", "Submitting"].includes(o.status) ? `<button class="button secondary small" data-action="reconcile-order" data-id="${esc(o.id)}">Review</button>` : '<span class="table-sub">' + (o.status === "Failed" ? "Refunded" : "Owner review") + "</span>"}</td></tr>`,
    ),
    "No orders yet",
  );
}
function listUrl(path) {
  return (
    path +
    "?" +
    new URLSearchParams({
      offset: state.offset,
      limit: state.limit,
      q: state.q,
    })
  );
}
async function loadPage() {
  const owner = user.role === "owner";
  let html = "";
  switch (currentSection) {
    case "dashboard": {
      if (owner) {
        const d = await api("/admin/stats"),
          s = d.stats;
        html =
          title(
            "The big picture.",
            "Your platform, at a glance. Real data. Clear decisions.",
            button("Manage deposits", "/owner/deposits", "wallet"),
          ) +
          `<div class="welcome-banner"><div><span class="eyebrow">OWNER COMMAND CENTER</span><h2>Welcome back, ${esc(user.username)}.</h2><p>Manage your community, keep payments moving, and monitor platform operations from one place.</p></div><span class="welcome-orb" aria-hidden="true">✧</span></div><div class="stats-grid">${stat("Registered users", s.total_users, "users", "Customer accounts")}${stat("Total orders", s.total_orders, "orders", "All submitted orders")}${stat("Net order revenue", money(s.total_revenue), "chart", "After customer refunds")}${stat("Estimated gross profit", money(s.total_profit), "bolt", "Excludes external fees")}</div><div class="stats-grid">${stat("Estimated provider cost", money(s.total_provider_cost), "layers", "Provider charge snapshots")}${stat("Pending deposits", s.pending_deposits, "clock", "Awaiting bank verification")}${stat("Approved deposits", s.approved_deposits, "check", "Verified wallet credits")}${stat("Rejected deposits", s.rejected_deposits, "shield", "No wallet credit")}</div><div class="grid-equal"><section class="panel"><div class="panel-head"><h3>Provider connection</h3>${badge(d.provider.error ? "Needs attention" : "Active")}</div>${d.provider.error ? `<p class="notice warn">${esc(d.provider.error)}</p>` : `<div class="key-value"><div><span>Provider balance</span><strong>${esc(d.provider.balance)} ${esc(d.provider.currency)}</strong></div><div><span>Default markup</span><strong>${esc(d.profit_percentage)}%</strong></div></div>`}<p class="api-note">Estimated costs use the immutable price at checkout and proportional refunds. Compare provider charges in the provider portal for accounting reconciliation.</p></section><section class="panel"><h3>Quick actions</h3>${quick("Credit or deduct a wallet", "Make a fully audited adjustment.", "/owner/wallet", "wallet")}${quick("Review deposit requests", "Only credit independently verified payments.", "/owner/deposits", "history")}${quick("Manage your markup", "Updates apply to future orders only.", "/owner/profit", "chart")}</section></div>`;
      } else {
        const d = await api("/dashboard");
        user = d.user;
        html =
          title(
            `Good to see you, ${user.username}.`,
            "Here’s what’s happening in your workspace today.",
            button("New order", "/app/new-order", "plus"),
          ) +
          `<div class="welcome-banner"><div><span class="eyebrow">YOUR NEXT MOVE STARTS HERE</span><h2>Less managing. More momentum.</h2><p>Discover services, keep an eye on your orders, and stay in control of every transaction.</p></div><span class="welcome-orb" aria-hidden="true">✧</span></div><div class="stats-grid">${stat("Wallet balance", money(user.balance), "wallet", "Available for your next order")}${stat("Total orders", d.stats.total, "orders", "Your complete order history")}${stat("Pending orders", d.stats.pending, "clock", "We’re keeping track for you")}${stat("Completed orders", d.stats.completed, "check", "Delivered by the provider")}</div><div class="grid-2"><section class="panel table-panel"><div class="panel-head"><div><h3>Recent transactions</h3><p>Every movement, accounted for.</p></div><a href="/app/transactions" data-link class="count-label">View all ↗</a></div>${txTable(d.transactions)}</section><section class="panel"><div class="panel-head"><div><h3>Make your next move</h3><p>Shortcuts to the things that matter.</p></div></div>${quick("Place a new order", "Find your service. Set your quantity. Go.", "/app/new-order", "plus")}${quick("Top up your wallet", "Secure UPI deposits, verified by our team.", "/app/funds", "wallet")}${quick("We’re here to help", "Open a conversation with support.", "/app/support", "support")}</section></div>`;
      }
      break;
    }
    case "services": {
      catalog = await api("/services");
      html =
        title(
          "The service catalogue.",
          "Live services. Transparent pricing. Find your next move.",
          owner
            ? '<button class="button secondary" data-action="sync-services">' +
                icon("refresh") +
                " Sync provider</button>"
            : "",
        ) +
        `${catalog.warning ? `<p class="notice warn">${esc(catalog.warning)} Showing the last cached catalogue.</p>` : ""}<section class="panel table-panel"><div class="panel-head"><h3>Discover services</h3><span class="count-label">${catalog.services.length} available services</span></div><div class="service-toolbar"><label class="sr-only" for="service-search">Search services</label><input class="search" id="service-search" placeholder="Search by name or service ID…"><label class="sr-only" for="category-filter">Service category</label><select class="search" id="category-filter"><option value="">All categories</option>${[...new Set(catalog.services.map((s) => s.category))].map((c) => `<option>${esc(c)}</option>`).join("")}</select></div><div id="services-table"></div></section>`;
      break;
    }
    case "new-order": {
      catalog = await api("/services");
      html =
        title(
          "Your next order.",
          "Choose a service. Get a quote. You’re in control.",
        ) +
        `<div class="grid-2"><section class="panel"><div class="panel-head"><h3>Order details</h3><span class="badge">Step 01 / Configure</span></div><form id="order-form"><div class="field"><label for="order-category">Category</label><select id="order-category"><option value="">All categories</option>${[...new Set(catalog.services.filter((s) => s.orderable).map((s) => s.category))].map((c) => `<option>${esc(c)}</option>`).join("")}</select></div>${field("Find a service", "order-search", "search", 'placeholder="Search by name or ID"')}<div class="field"><label for="service">Service</label><select name="service" id="service" required></select></div>${field("Link to your page or post", "link", "url", 'required maxlength="2000" placeholder="https://…"')}${field("Quantity", "quantity", "number", 'required min="1" max="1000000000" step="1" placeholder="Enter quantity"')}<div id="media-field" hidden>${field("Media URL to scrape likers from", "media", "url", 'placeholder="https://…"')}</div><div class="quote row between"><span><small>YOUR TOTAL</small><br><strong id="order-total">—</strong></span><span class="table-sub">INR · No hidden markup</span></div><p id="quote-note" class="api-note">Select a service and quantity to calculate your price.</p><label class="check"><input type="checkbox" name="confirmed" required> I have checked the link and quantity. I am authorized to submit this order and will comply with the relevant platform rules.</label><button class="button block" type="submit" id="place-order" disabled>${icon("plus")} Confirm & place order</button></form></section><aside class="stack"><section class="panel"><div class="panel-head"><h3>Service intelligence</h3>${icon("layers")}</div><div id="service-info">${empty("Choose your service", "Details and limits will appear here.")}</div></section><p class="notice">${icon("shield")} &nbsp; Your wallet is charged only after server-side validation. If the provider explicitly rejects your order, the charge is automatically refunded. Uncertain submissions are reviewed before any retry.</p></aside></div>`;
      break;
    }
    case "orders": {
      const d = await api(listUrl(owner ? "/admin/orders" : "/orders"));
      html =
        title(
          owner ? "Every order. One view." : "Your orders.",
          "Track progress and inspect the details that matter.",
          !owner ? button("New order", "/app/new-order", "plus") : "",
        ) +
        `<section class="panel table-panel"><div class="panel-head"><h3>${owner ? "Platform orders" : "Order history"}</h3><input class="search" id="table-search" aria-label="Search orders" placeholder="Search orders…" value="${esc(state.q)}"></div>${orderTable(d.items, owner)}${pager(d)}</section>`;
      break;
    }
    case "transactions": {
      const d = await api(listUrl("/transactions"));
      html =
        title(
          "Every rupee. Accounted for.",
          "Your complete wallet ledger, from the first deposit onward.",
        ) +
        `<section class="panel table-panel"><div class="panel-head"><h3>Transaction history</h3><span class="pill">${icon("shield")} Wallet ledger</span></div>${txTable(d.items)}${pager(d)}</section>`;
      break;
    }
    case "funds": {
      const [me, d] = await Promise.all([
        api("/me"),
        api(listUrl("/deposits")),
      ]);
      html =
        title(
          "Fuel your next move.",
          "Add funds with UPI. Your wallet is credited after payment verification.",
        ) +
        `<div class="grid-equal"><section class="panel"><div class="panel-head"><h3>Make a UPI payment</h3>${icon("wallet")}</div><p>Send your payment to the UPI ID below. Then submit the exact amount and bank reference.</p><div class="upi-box"><span class="eyebrow">PAY VIA UPI</span><strong>${esc(me.upi_id)}</strong><button class="button secondary small" data-action="copy-upi" data-upi="${esc(me.upi_id)}">Copy UPI ID</button></div><p class="notice warn">Verify the recipient in your payment app before sending. We never ask for your UPI PIN or OTP. A submitted UTR is not proof of receipt; only independently verified payments are approved.</p></section><section class="panel"><div class="panel-head"><h3>Submit payment details</h3><span class="badge">Manual verification</span></div><form id="deposit-form">${field("Amount paid (INR)", "amount", "number", 'required min="0.01" max="10000000" step="0.01" placeholder="500.00"')}${field("UTR / Transaction ID", "utr", "text", 'required minlength="6" maxlength="80" pattern="(?:[A-Za-z0-9]|-)+" placeholder="Your bank transaction reference"')}<label class="check"><input type="checkbox" required> I have completed this payment and the details are accurate.</label><button class="button block" type="submit">Submit for verification ${icon("arrow")}</button></form></section></div><section class="panel table-panel"><div class="panel-head"><h3>Your deposit requests</h3></div>${depositTable(d.items, false)}${pager(d)}</section>`;
      break;
    }
    case "profile": {
      const me = (await api("/me")).user;
      html =
        title(
          "Your account. Your space.",
          "Keep your account details and security in check.",
        ) +
        `<div class="grid-equal"><section class="panel"><h3>Account overview</h3><div class="key-value"><div><span>Username</span><strong>${esc(me.username)}</strong></div><div><span>Account role</span>${badge(me.role)}</div><div><span>Member since</span><strong>${date(me.created_at)}</strong></div><div><span>Wallet balance</span><strong>${money(me.balance)}</strong></div></div></section><section class="panel"><h3>Account security</h3>${owner ? '<p class="notice">Your owner password is managed securely through the OWNER_PASSWORD environment variable in Render. Redeploy after changing it to invalidate previous sessions.</p>' : `<form id="password-form">${pass("Current password", "currentPassword")}${pass("New password", "password", "new-password")}${pass("Confirm new password", "confirmPassword", "new-password")}<button class="button" type="submit">Update password ${icon("shield")}</button></form>`}</section></div>`;
      break;
    }
    case "users": {
      const d = await api(listUrl("/admin/users"));
      html =
        title("Your community.", "Manage accounts, balances, and access.") +
        `<section class="panel table-panel"><div class="panel-head"><h3>Registered users</h3><input class="search" id="table-search" aria-label="Search users" placeholder="Search username…" value="${esc(state.q)}"></div>${table(
          ["Username", "Balance", "Status", "Joined", "Actions"],
          d.items.map(
            (u) =>
              `<tr><td><strong>${esc(u.username)}</strong><span class="table-sub"> · #${esc(u.id)}</span></td><td>${money(u.balance)}</td><td>${badge(u.suspended ? "Suspended" : "Active")}</td><td>${date(u.created_at)}</td><td><div class="row"><button class="button secondary small" data-action="user-details" data-id="${esc(u.id)}">View history</button><button class="button ${u.suspended ? "secondary" : "danger"} small" data-action="suspend-user" data-id="${esc(u.id)}" data-suspended="${u.suspended}" data-username="${esc(u.username)}">${u.suspended ? "Restore" : "Suspend"}</button></div></td></tr>`,
          ),
          "No registered users yet",
        )}${pager(d)}</section><div id="user-detail"></div>`;
      break;
    }
    case "wallet":
      html =
        title(
          "Wallet control. Without compromise.",
          "Every adjustment is atomic, recorded, and linked to your owner account.",
        ) +
        `<div class="grid-equal">${walletForm("add")}${walletForm("deduct")}</div><div class="notice">${icon("shield")} &nbsp; Balances cannot go negative. Confirm the username and amount before submitting. If a request times out, retry without changing the form to safely reuse its operation reference.</div>`;
      break;
    case "deposits": {
      const d = await api(listUrl("/admin/deposits"));
      html =
        title(
          "Verify. Approve. Move forward.",
          "Compare every request against your bank or UPI statement before crediting a wallet.",
        ) +
        `<p class="notice warn">Never approve based only on a submitted UTR or screenshot. Confirm settled funds in your own bank account, match the exact amount, and use the reference to prevent duplicate credits.</p><section class="panel table-panel"><div class="panel-head"><h3>Deposit requests</h3></div>${depositTable(d.items, true)}${pager(d)}</section>`;
      break;
    }
    case "profit": {
      const d = await api("/admin/settings");
      html =
        title(
          "Pricing that works for you.",
          "Set your platform markup. Existing orders keep their original prices.",
        ) +
        `<div class="grid-equal"><section class="panel"><div class="panel-head"><h3>Default profit markup</h3><span class="badge">Future orders only</span></div><form id="profit-form">${field("Profit percentage", "profitPercentage", "number", `required min="0" max="1000" step="0.0001" value="${esc(d.profit_percentage)}"`)}<button class="button" type="submit">Save markup ${icon("check")}</button></form></section><section class="panel"><span class="eyebrow">HOW IT WORKS</span><h2>Transparent by design.</h2><p class="api-note">Customer price = Provider cost × (1 + markup ÷ 100). Prices are calculated on the server and rounded up to the nearest paise.</p><div class="key-value"><div><span>Example provider cost</span><strong>₹100.00</strong></div><div><span>Current markup</span><strong>${esc(d.profit_percentage)}%</strong></div><div><span>Example customer price</span><strong>${money(100 * (1 + Number(d.profit_percentage) / 100))}</strong></div></div><p class="api-note">Every setting change is recorded in your audit log.</p></section></div>`;
      break;
    }
    case "support": {
      if (state.ticket) {
        html = await ticketView(state.ticket);
        break;
      }
      const d = await api(listUrl(owner ? "/admin/tickets" : "/tickets"));
      html =
        title(
          owner
            ? "Support, with a human touch."
            : "A little help goes a long way.",
          owner
            ? "Read, respond, and resolve customer conversations."
            : "Start a conversation. We’ll keep everything together.",
        ) +
        `${!owner ? `<section class="panel"><h3>Open a support ticket</h3><form id="ticket-form">${field("Subject", "subject", "text", 'required minlength="3" maxlength="180" placeholder="How can we help?"')}${field("Message", "body", "textarea", 'required minlength="10" maxlength="5000" placeholder="Include your order ID or payment reference where relevant. Never share passwords or OTPs."')}<button class="button" type="submit">Send message ${icon("arrow")}</button></form></section>` : ""}<section class="panel table-panel"><div class="panel-head"><h3>${owner ? "Customer conversations" : "Your conversations"}</h3></div>${table(
          [
            "Ticket",
            "Subject",
            ...(owner ? ["Username"] : []),
            "Status",
            "Updated",
            "",
          ],
          d.items.map(
            (t) =>
              `<tr><td>#${esc(t.id)}</td><td>${esc(t.subject)}</td>${owner ? `<td>${esc(t.username)}</td>` : ""}<td>${badge(t.status)}</td><td>${date(t.updated_at)}</td><td><button class="button secondary small" data-action="open-ticket" data-id="${esc(t.id)}">Open conversation</button></td></tr>`,
          ),
          "No conversations yet",
        )}${pager(d)}</section>`;
      break;
    }
    case "logs": {
      const d = await api(listUrl("/admin/logs"));
      html =
        title(
          "A clear trail. Always.",
          "Your owner actions, recorded permanently for accountability.",
        ) +
        `<section class="panel table-panel"><div class="panel-head"><h3>Owner audit log</h3></div>${table(
          ["ID", "Action", "Target", "Details", "Date"],
          d.items.map(
            (l) =>
              `<tr><td>#${esc(l.id)}</td><td>${badge(l.action)}</td><td>${esc(l.target)}</td><td><span class="table-title" title="${esc(JSON.stringify(l.details))}">${esc(JSON.stringify(l.details))}</span></td><td>${date(l.created_at)}</td></tr>`,
          ),
          "No owner actions yet",
        )}${pager(d)}</section>`;
      break;
    }
    default:
      html = title("Page not found.", "Choose a section from the sidebar.");
  }
  return html;
}
function quick(h, p, url, ic) {
  return `<a class="quick-link" href="${url}" data-link><span class="quick-icon">${icon(ic)}</span><span><strong>${esc(h)}</strong><p>${esc(p)}</p></span>${icon("arrow")}</a>`;
}
function depositTable(rows, owner) {
  return table(
    [
      "Reference",
      ...(owner ? ["Username"] : []),
      "Amount",
      "UTR",
      "Status",
      "Submitted",
      ...(owner ? ["Actions"] : ["Review note"]),
    ],
    rows.map(
      (d) =>
        `<tr><td>#${esc(d.id)}</td>${owner ? `<td>${esc(d.username)}</td>` : ""}<td>${money(d.amount)}</td><td class="mono">${esc(d.utr)}</td><td>${badge(d.status)}</td><td>${date(d.created_at)}</td><td>${owner && d.status === "pending" ? `<div class="row"><button class="button small" data-action="approve-deposit" data-id="${esc(d.id)}" data-amount="${esc(d.amount)}" data-utr="${esc(d.utr)}">Approve</button><button class="button danger small" data-action="reject-deposit" data-id="${esc(d.id)}">Reject</button></div>` : esc(d.note || "—")}</td></tr>`,
    ),
    "No deposit requests yet",
  );
}
async function showUserHistory(uid, offset = 0) {
  const d = await api("/admin/users/" + uid + "?limit=25&offset=" + offset);
  const total = Math.max(d.orders.total, d.transactions.total);
  document.querySelector("#user-detail").innerHTML =
    `<section class="panel"><h2>${esc(d.user.username)}</h2><p>Current balance ${money(d.user.balance)} · ${d.orders.total} orders · ${d.transactions.total} transactions</p><div class="pagination"><span>History records ${total ? offset + 1 : 0}–${Math.min(offset + 25, total)} of ${total}</span><div class="pager-buttons"><button class="button secondary small" data-action="user-history-prev" data-id="${esc(uid)}" data-offset="${Math.max(0, offset - 25)}" ${offset === 0 ? "disabled" : ""}>Previous history</button><button class="button secondary small" data-action="user-history-next" data-id="${esc(uid)}" data-offset="${offset + 25}" ${offset + 25 >= total ? "disabled" : ""}>Next history</button></div></div><h3>Order history</h3>${orderTable(d.orders.items, true)}<h3>Wallet history</h3>${txTable(d.transactions.items)}</section>`;
  document.querySelector("#user-detail").scrollIntoView({ behavior: "smooth" });
}
function walletForm(op) {
  return `<section class="panel"><div class="panel-head"><h3>${op === "add" ? "Add balance" : "Deduct balance"}</h3><span class="stat-icon">${icon(op === "add" ? "plus" : "minus")}</span></div><form class="wallet-form" data-operation="${op}">${field("Registered username", op + "-username", "text", 'required minlength="3" maxlength="32" placeholder="Exact username"')}${field("Amount (INR)", op + "-amount", "number", 'required min="0.01" max="10000000" step="0.01" placeholder="0.00"')}${field("Reason for adjustment", op + "-reason", "textarea", 'required minlength="3" maxlength="500" placeholder="A clear reason for the audit trail"')}<label class="check"><input type="checkbox" name="confirmed" required> I confirm this ${op === "add" ? "credit" : "deduction"} and have checked the recipient.</label><button class="button ${op === "deduct" ? "danger" : ""} block" type="submit">${icon(op === "add" ? "plus" : "minus")} ${op === "add" ? "Add balance" : "Deduct balance"}</button><p class="wallet-result api-note" role="status"></p></form></section>`;
}
async function ticketView(tid) {
  const d = await api("/tickets/" + tid);
  return (
    title(
      d.ticket.subject,
      `Ticket #${d.ticket.id} · ${d.ticket.status}`,
      '<button class="button secondary small" data-action="back-tickets">← All conversations</button>',
    ) +
    `<section class="panel">${d.messages.map((m) => `<article class="ticket-message ${m.role === "owner" ? "owner" : ""}"><div class="row between"><strong>${esc(m.username)} ${m.role === "owner" ? "· Support" : ""}</strong><small>${date(m.created_at)}</small></div><p>${esc(m.body)}</p></article>`).join("")}${d.ticket.status === "open" ? `<form id="reply-form" data-id="${esc(tid)}">${field("Your reply", "body", "textarea", 'required maxlength="5000"')}<button class="button" type="submit">Send reply ${icon("arrow")}</button></form>` : '<p class="notice">This conversation is closed.</p>'}${user.role === "owner" ? `<p class="api-note"><button class="button secondary small" data-action="ticket-status" data-id="${esc(tid)}" data-status="${d.ticket.status === "open" ? "closed" : "open"}">${d.ticket.status === "open" ? "Close" : "Reopen"} ticket</button></p>` : ""}</section>`
  );
}
function renderServices() {
  const search = (
      document.querySelector("#service-search")?.value || ""
    ).toLowerCase(),
    category = document.querySelector("#category-filter")?.value || "";
  const services = catalog.services.filter(
    (s) =>
      (!category || s.category === category) &&
      (s.name.toLowerCase().includes(search) || s.id.includes(search)),
  );
  const slice = services.slice(state.offset, state.offset + state.limit);
  document.querySelector("#services-table").innerHTML =
    table(
      ["ID / Service", "Category", "Price", "Min / Max", "Type", ""],
      slice.map(
        (s) =>
          `<tr><td><span class="table-title" title="${esc(s.description)}">#${esc(s.id)} · ${esc(s.name)}</span></td><td><span class="table-title">${esc(s.category)}</span></td><td>${money(s.rate)} <span class="table-sub">/ ${s.type === "Package" ? "package" : "1,000"}</span></td><td>${esc(s.min)} / ${esc(s.max)}</td><td>${badge(s.type)}</td><td>${s.orderable ? `<button class="button secondary small" data-action="${user.role === "owner" ? "view-service" : "select-service"}" data-id="${esc(s.id)}">${user.role === "owner" ? "View details" : "View / Order ↗"}</button>` : '<span class="table-sub" title="The provider does not publish a supported subscription checkout contract.">Recurring checkout unavailable</span>'}</td></tr>`,
      ),
      "No matching services",
    ) +
    pager({ offset: state.offset, limit: state.limit, total: services.length });
}
function setServiceOptions() {
  const sel = document.querySelector("#service");
  if (!sel) return;
  const prev = sel.value,
    cat = document.querySelector("#order-category").value,
    search = document.querySelector("#order-search").value.toLowerCase();
  const rows = catalog.services.filter(
    (s) =>
      s.orderable &&
      (!cat || s.category === cat) &&
      (s.name.toLowerCase().includes(search) || s.id.includes(search)),
  );
  sel.innerHTML =
    '<option value="">Choose a service…</option>' +
    rows
      .map(
        (s) =>
          `<option value="${esc(s.id)}">#${esc(s.id)} — ${esc(s.name)} · ${money(s.rate)} / ${s.type === "Package" ? "package" : "1,000"}</option>`,
      )
      .join("");
  if (rows.some((s) => s.id === prev)) sel.value = prev;
  serviceChanged();
}
function serviceChanged() {
  quoteEpoch++;
  quote = null;
  document.querySelector("#place-order").disabled = true;
  document.querySelector("#order-total").textContent = "—";
  const s = catalog.services.find(
    (s) => s.id === document.querySelector("#service").value,
  );
  const qty = document.querySelector("#quantity");
  document.querySelector("#media-field").hidden =
    s?.type !== "Mentions Media Likers";
  document.querySelector("#media").required =
    s?.type === "Mentions Media Likers";
  if (!s) {
    document.querySelector("#service-info").innerHTML = empty(
      "Choose your service",
      "Details and limits will appear here.",
    );
    return;
  }
  qty.disabled = s.type === "Package";
  qty.min = s.type === "Package" ? 1 : s.min;
  qty.max = s.type === "Package" ? 1 : s.max;
  if (s.type === "Package") qty.value = 1;
  else if (
    Number(qty.value) < Number(s.min) ||
    Number(qty.value) > Number(s.max)
  )
    qty.value = s.min;
  document.querySelector("#service-info").innerHTML =
    `<span class="eyebrow">SERVICE #${esc(s.id)}</span><h3>${esc(s.name)}</h3><div class="service-meta"><div><small>PRICE / ${s.type === "Package" ? "PACKAGE" : "1,000"}</small>${money(s.rate)}</div><div><small>TYPE</small>${esc(s.type)}</div><div><small>MINIMUM</small>${esc(s.min)}</div><div><small>MAXIMUM</small>${esc(s.max)}</div></div><div class="service-description">${esc(s.description)}</div>`;
  updateQuote();
}
let quoteTimer,
  quoteEpoch = 0;
async function updateQuote() {
  const version = ++quoteEpoch;
  quote = null;
  const btn = document.querySelector("#place-order");
  if (!btn) return;
  btn.disabled = true;
  const service = document.querySelector("#service").value,
    quantity = Number(document.querySelector("#quantity").value);
  if (!service || quantity <= 0) return;
  document.querySelector("#order-total").textContent = "Calculating…";
  try {
    const d = await api("/orders/quote", "POST", { service, quantity });
    if (version !== quoteEpoch || !document.querySelector("#place-order"))
      return;
    quote = d;
    document.querySelector("#order-total").textContent = money(d.total);
    document.querySelector("#quote-note").textContent =
      "Price confirmed by the server. Your wallet will be charged this amount.";
    btn.disabled = false;
  } catch (e) {
    if (version !== quoteEpoch) return;
    document.querySelector("#order-total").textContent = "—";
    document.querySelector("#quote-note").textContent = e.message;
  }
}
async function render() {
  const version = ++epoch;
  const path = location.pathname.replace(/\/$/, "") || "/";
  if (path === "/") {
    landing();
    return;
  }
  if (["/login", "/register", "/owner-login"].includes(path)) {
    authPage(
      path === "/register"
        ? "register"
        : path === "/owner-login"
          ? "owner"
          : "login",
    );
    return;
  }
  if (!user) {
    try {
      user = (await api("/me")).user;
    } catch {
      navigate(path.startsWith("/owner") ? "/owner-login" : "/login");
      return;
    }
  }
  if (version !== epoch) return;
  const owner = path.startsWith("/owner");
  if (owner && user.role !== "owner") {
    navigate("/app/dashboard");
    return;
  }
  if (!owner && user.role === "owner") {
    navigate("/owner/dashboard");
    return;
  }
  currentSection = path.split("/")[2] || "dashboard";
  document.title =
    (owner ? ownerNav : userNav).find((n) => n[0] === currentSection)?.[1] +
    " — ZUDO";
  shell();
  try {
    const html = await loadPage();
    if (version !== epoch) return;
    document.querySelector("#page").innerHTML = html;
    document.querySelector("#page").className = "stack";
    if (currentSection === "services") renderServices();
    if (currentSection === "new-order") {
      setServiceOptions();
      const selected = sessionStorage.getItem("zudo:selectedService");
      if (selected) {
        sessionStorage.removeItem("zudo:selectedService");
        document.querySelector("#service").value = selected;
        serviceChanged();
      }
    }
  } catch (e) {
    if (version !== epoch) return;
    if (e.status === 401) {
      user = null;
      navigate(owner ? "/owner-login" : "/login");
      return;
    }
    document.querySelector("#page").innerHTML =
      `<section class="panel error-box"><h2>Let’s try that again.</h2><p>${esc(e.message)}</p><button class="button secondary" data-action="reload">Reload workspace</button></section>`;
  }
}
document.addEventListener("click", async (e) => {
  const link = e.target.closest("a[data-link]");
  if (link) {
    const href = link.getAttribute("href");
    if (href.startsWith("#")) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(href);
    return;
  }
  const b = e.target.closest("[data-action]");
  if (!b) return;
  const a = b.dataset.action;
  if (b.disabled) return;
  try {
    switch (a) {
      case "toggle-password": {
        const input = document.getElementById(b.dataset.target);
        input.type = input.type === "password" ? "text" : "password";
        b.setAttribute(
          "aria-label",
          input.type === "password" ? "Show password" : "Hide password",
        );
        return;
      }
      case "open-menu":
        document.querySelector(".sidebar").classList.add("open");
        document.querySelector(".sidebar-shade").classList.add("open");
        return;
      case "close-menu":
        document.querySelector(".sidebar").classList.remove("open");
        document.querySelector(".sidebar-shade").classList.remove("open");
        return;
      case "logout":
        await api("/auth/logout", "POST", {});
        user = null;
        catalog = null;
        sessionStorage.removeItem("zudo:order");
        await token();
        navigate("/");
        return;
      case "reload":
        render();
        return;
      case "page-next":
        state.offset += state.limit;
        currentSection === "services" ? renderServices() : render();
        return;
      case "page-prev":
        state.offset = Math.max(0, state.offset - state.limit);
        currentSection === "services" ? renderServices() : render();
        return;
      case "view-service": {
        const s = catalog.services.find((s) => s.id === b.dataset.id);
        if (!s) return;
        const el = document.createElement("section");
        el.className = "panel";
        el.innerHTML = `<span class="eyebrow">SERVICE #${esc(s.id)}</span><h2>${esc(s.name)}</h2><p class="api-note">${esc(s.category)} · ${esc(s.type)} · ${money(s.rate)} / ${s.type === "Package" ? "package" : "1,000"}</p><p class="service-description">${esc(s.description)}</p>`;
        document.querySelector("#page").prepend(el);
        el.scrollIntoView({ behavior: "smooth" });
        return;
      }
      case "select-service":
        sessionStorage.setItem("zudo:selectedService", b.dataset.id);
        navigate("/app/new-order");
        return;
      case "sync-services":
        b.disabled = true;
        await api("/admin/services/sync", "POST", {});
        toast("Service catalogue refreshed");
        render();
        return;
      case "refresh-order":
        b.disabled = true;
        await api(
          (user.role === "owner" ? "/admin" : "") +
            "/orders/" +
            b.dataset.id +
            "/refresh",
          "POST",
          {},
        );
        toast("Order status updated");
        render();
        return;
      case "copy-upi":
        await navigator.clipboard.writeText(b.dataset.upi);
        toast("UPI ID copied");
        return;
      case "open-ticket":
        state.ticket = b.dataset.id;
        render();
        return;
      case "back-tickets":
        state.ticket = null;
        render();
        return;
      case "ticket-status":
        await api("/admin/tickets/" + b.dataset.id + "/status", "POST", {
          status: b.dataset.status,
        });
        toast("Ticket updated");
        render();
        return;
      case "user-details":
      case "user-history-prev":
      case "user-history-next": {
        await showUserHistory(b.dataset.id, Number(b.dataset.offset || 0));
        return;
      }
      case "suspend-user": {
        const suspend = b.dataset.suspended !== "true";
        showActionForm(
          `${suspend ? "Suspend" : "Restore"} ${b.dataset.username}`,
          "user-action-form",
          field(
            "Reason",
            "reason",
            "textarea",
            'required minlength="3" maxlength="500"',
          ),
          { id: b.dataset.id, suspended: suspend },
        );
        return;
      }
      case "approve-deposit":
      case "reject-deposit": {
        const approve = a === "approve-deposit";
        showActionForm(
          approve ? "Verify & approve payment" : "Reject deposit",
          "deposit-action-form",
          `<p class="notice warn">${approve ? `Confirm you independently verified ${money(b.dataset.amount)} in settled funds. Reference: ${esc(b.dataset.utr)}.` : "No wallet credit will be issued."}</p>${field("Review note", "note", "textarea", 'maxlength="500"')}`,
          { id: b.dataset.id, action: approve ? "approve" : "reject" },
        );
        return;
      }
      case "reconcile-order": {
        showActionForm(
          "Resolve uncertain submission",
          "reconcile-form",
          `<p class="notice warn">Inspect the provider’s own order history first. Never refund or re-submit an uncertain order without verifying whether the provider accepted it. Attaching an unrelated provider ID can corrupt order accounting.</p><div class="field"><label for="action">Resolution</label><select name="action" id="action"><option value="attach">Attach verified provider order ID</option><option value="refund">Verified absent in provider history — refund</option></select></div>${field("Provider order ID (required for attach)", "providerOrderId", "text", 'pattern="[0-9]+"')}${field("Verification and reason", "reason", "textarea", 'required minlength="3" maxlength="500"')}`,
          { id: b.dataset.id },
        );
        return;
      }
    }
  } catch (err) {
    toast(err.message, true);
  } finally {
    if (document.contains(b)) b.disabled = false;
  }
});
function showActionForm(h, form, body, data) {
  const page = document.querySelector("#page");
  const old = document.querySelector("#action-panel");
  if (old) old.remove();
  const el = document.createElement("section");
  el.className = "panel";
  el.id = "action-panel";
  el.innerHTML = `<h2>${esc(h)}</h2><form id="${form}">${body}<label class="check"><input type="checkbox" name="confirmed" required> I have verified the details and confirm this action.</label><div class="row"><button class="button" type="submit">Confirm action ${icon("check")}</button><button class="button secondary" type="button" id="cancel-action">Cancel</button></div></form>`;
  el.querySelector("form").actionData = data;
  el.querySelector("#cancel-action").onclick = () => el.remove();
  page.prepend(el);
  el.scrollIntoView({ behavior: "smooth" });
}
document.addEventListener("submit", async (e) => {
  const form = e.target;
  if (!(form instanceof HTMLFormElement) || form.closest("dialog")) return;
  e.preventDefault();
  const btn = form.querySelector('button[type="submit"]');
  if (btn?.disabled) return;
  const d = Object.fromEntries(new FormData(form));
  if (btn) btn.disabled = true;
  try {
    switch (form.id) {
      case "auth-form": {
        const mode = form.dataset.mode;
        const result = await api(
          "/auth/" +
            (mode === "owner"
              ? "owner"
              : mode === "register"
                ? "register"
                : "login"),
          "POST",
          d,
        );
        user = result.user;
        sessionStorage.removeItem("zudo:order");
        navigate(user.role === "owner" ? "/owner/dashboard" : "/app/dashboard");
        toast(mode === "register" ? "Your workspace is ready" : "Welcome back");
        break;
      }
      case "order-form": {
        if (!quote) throw new Error("Please obtain a fresh quote first");
        if (
          !(await confirmAction(
            "Place this order?",
            `${money(quote.total)} will be deducted from your wallet. Check your link and quantity before confirming.`,
          ))
        )
          break;
        const payload = {
          service: d.service,
          quantity: quote.quantity,
          link: d.link,
          ...(d.media ? { media: d.media } : {}),
          expectedTotal: quote.total,
        };
        const fingerprint = JSON.stringify(payload);
        let saved;
        try {
          saved = JSON.parse(sessionStorage.getItem("zudo:order"));
        } catch {}
        orderKey =
          saved?.fingerprint === fingerprint ? saved.key : crypto.randomUUID();
        sessionStorage.setItem(
          "zudo:order",
          JSON.stringify({ fingerprint, key: orderKey }),
        );
        const result = await api("/orders", "POST", {
          ...payload,
          idempotencyKey: orderKey,
        });
        sessionStorage.removeItem("zudo:order");
        user = (await api("/me")).user;
        navigate("/app/orders");
        toast(
          result.order.status === "Failed"
            ? "Provider rejected the order; your wallet was refunded"
            : result.order.status === "Needs review"
              ? "Submission needs owner review. Do not place a duplicate order."
              : "Order submitted successfully",
          result.order.status === "Failed",
        );
        break;
      }
      case "deposit-form":
        await api("/deposits", "POST", d);
        toast(
          "Payment submitted for verification. Your balance will update after approval.",
        );
        render();
        break;
      case "password-form":
        await api("/profile/password", "POST", d);
        form.reset();
        toast("Password updated. Other sessions have been invalidated.");
        break;
      case "profit-form":
        if (
          !(await confirmAction(
            "Update platform pricing?",
            `Future orders will use a ${d.profitPercentage}% markup. Existing orders will not change.`,
          ))
        )
          break;
        await api("/admin/settings", "POST", d);
        catalog = null;
        toast("Markup saved and audited");
        render();
        break;
      case "ticket-form":
        await api("/tickets", "POST", d);
        toast("Support ticket created");
        render();
        break;
      case "reply-form":
        await api("/tickets/" + form.dataset.id + "/messages", "POST", d);
        toast("Reply sent");
        render();
        break;
      case "user-action-form":
        await api("/admin/users/" + form.actionData.id + "/suspend", "POST", {
          suspended: form.actionData.suspended,
          reason: d.reason,
        });
        toast("Account access updated");
        render();
        break;
      case "deposit-action-form":
        await api(
          "/admin/deposits/" +
            form.actionData.id +
            "/" +
            form.actionData.action,
          "POST",
          { note: d.note || "", confirmed: true },
        );
        toast(
          "Deposit " +
            (form.actionData.action === "approve"
              ? "approved and credited"
              : "rejected"),
        );
        render();
        break;
      case "reconcile-form":
        await api(
          "/admin/orders/" + form.actionData.id + "/reconcile",
          "POST",
          {
            ...d,
            confirmed: true,
            ...(d.providerOrderId ? {} : { providerOrderId: undefined }),
          },
        );
        toast("Order resolution recorded");
        render();
        break;
      default:
        if (form.classList.contains("wallet-form")) {
          const op = form.dataset.operation,
            body = {
              username: d[op + "-username"],
              amount: d[op + "-amount"],
              reason: d[op + "-reason"],
              confirmed: true,
            };
          if (
            !(await confirmAction(
              op === "add" ? "Add wallet balance?" : "Deduct wallet balance?",
              `${op === "add" ? "Credit" : "Deduct"} ${money(body.amount)} ${op === "add" ? "to" : "from"} ${body.username}. This action is permanently recorded.`,
            ))
          )
            break;
          const fp = JSON.stringify(body);
          if (form.operationFingerprint !== fp) {
            form.operationKey = crypto.randomUUID();
            form.operationFingerprint = fp;
          }
          const result = await api("/admin/wallet/" + op, "POST", {
            ...body,
            idempotencyKey: form.operationKey,
          });
          form.operationKey = null;
          form.operationFingerprint = null;
          form.querySelector(".wallet-result").textContent =
            `${body.username} · Updated balance: ${money(result.balance)}`;
          toast(
            "Balance " +
              (op === "add" ? "credited" : "deducted") +
              " and recorded",
          );
          form.reset();
        }
    }
  } catch (err) {
    toast(err.message, true);
    if (err.status === 403 && /token/.test(err.message)) await token();
  } finally {
    if (btn && document.contains(btn)) btn.disabled = false;
  }
});
let searchTimer;
document.addEventListener("input", (e) => {
  if (e.target.id === "table-search") {
    const input = e.target;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.q = input.value;
      state.offset = 0;
      render();
    }, 450);
  }
  if (e.target.id === "service-search") {
    state.offset = 0;
    renderServices();
  }
  if (e.target.id === "order-search") setServiceOptions();
  if (e.target.id === "quantity") {
    quoteEpoch++;
    clearTimeout(quoteTimer);
    quote = null;
    document.querySelector("#place-order").disabled = true;
    quoteTimer = setTimeout(updateQuote, 250);
  }
});
document.addEventListener("change", (e) => {
  if (e.target.id === "category-filter") {
    state.offset = 0;
    renderServices();
  }
  if (e.target.id === "order-category") setServiceOptions();
  if (e.target.id === "service") serviceChanged();
});
window.addEventListener("popstate", () => {
  quoteEpoch++;
  clearTimeout(quoteTimer);
  state.offset = 0;
  state.q = "";
  state.ticket = null;
  render();
});
(async () => {
  try {
    await token();
    await render();
  } catch (e) {
    root.innerHTML = `<main id="main" class="error-box"><h1>Connection unavailable.</h1><p>${esc(e.message)}</p><button class="button" data-action="reload">Try again</button></main>`;
  }
})();
