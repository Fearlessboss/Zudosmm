"use strict";
// Test-only provider fixture. Never imported by production code.
const http = require("node:http");
async function providerFixture() {
  let mode = "ok",
    counter = 8000,
    calls = 0,
    status = {
      status: "Completed",
      charge: "100.00",
      start_count: "20",
      remains: "0",
      currency: "INR",
    };
  const server = http.createServer(async (req, res) => {
    let body = "";
    for await (const c of req) body += c;
    const p = new URLSearchParams(body);
    res.setHeader("Content-Type", "application/json");
    switch (p.get("action")) {
      case "balance":
        res.end(JSON.stringify({ balance: "10000.00", currency: "INR" }));
        break;
      case "services":
        res.end(
          JSON.stringify([
            {
              service: 1,
              name: "Test Default Service",
              category: "Test category",
              type: "Default",
              rate: "100",
              min: "10",
              max: "100000",
              desc: "Provider description",
            },
            {
              service: 2,
              name: "Test Package",
              category: "Packages",
              type: "Package",
              rate: "20",
              min: "1",
              max: "1",
            },
            {
              service: 3,
              name: "Test Subscription",
              category: "Recurring",
              type: "Subscriptions",
              rate: "3",
              min: "100",
              max: "10000",
            },
            {
              service: 4,
              name: "Test Mentions",
              category: "Mentions",
              type: "Mentions Media Likers",
              rate: "10",
              min: "10",
              max: "1000",
            },
          ]),
        );
        break;
      case "add":
        calls++;
        if (mode === "reject")
          res.end(JSON.stringify({ error: "Insufficient provider balance" }));
        else if (mode === "ambiguous") res.end("{invalid");
        else res.end(JSON.stringify({ order: ++counter }));
        break;
      case "status":
        res.end(JSON.stringify(status));
        break;
      default:
        res.end(JSON.stringify({ error: "Unknown action" }));
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    setMode: (m) => (mode = m),
    setStatus: (s) => (status = { ...status, ...s }),
    calls: () => calls,
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}
module.exports = { providerFixture };
