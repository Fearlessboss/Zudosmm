const fs = require("node:fs"),
  cp = require("node:child_process");
for (const d of ["src", "public", "scripts", "tests"])
  for (const f of fs.readdirSync(d))
    if (/\.(js|cjs)$/.test(f))
      cp.execFileSync(process.execPath, ["--check", d + "/" + f], {
        stdio: "inherit",
      });
for (const f of [
  "public/index.html",
  "public/style.css",
  "migrations/001_initial.sql",
  "render.yaml",
  ".env.example",
])
  if (!fs.statSync(f).size) throw Error("Empty " + f);
console.log("Production asset and syntax checks passed");
