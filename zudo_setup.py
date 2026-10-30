#!/usr/bin/env python3
"""ZUDO SMM PANEL — complete source project in one setup script.
Run: python3 zudo_setup.py --output zudo-smm-panel --install
Requires Python 3.9+, Node.js 22+, PostgreSQL 15+.
See the generated README.md and TEST_REPORT.txt before accepting live payments.
No real API keys or owner passwords are embedded in this file.
"""
from pathlib import Path
import argparse, subprocess, sys
FILES = {}
FILES['package.json'] = r'''{
  "name": "zudo-smm-panel", "version": "1.0.0", "private": true,
  "description": "Transactional, provider-backed service management panel",
  "engines": {"node": ">=22 <25"},
  "scripts": {"start": "node server.js", "migrate": "node scripts/migrate.js", "test": "node --test --test-concurrency=1 test/integration.test.js", "test:browser": "playwright test", "check": "node scripts/check.js"},
  "dependencies": {"bcrypt": "^6.0.0", "connect-pg-simple": "^10.0.0", "decimal.js": "^10.6.0", "dotenv": "^17.2.3", "express": "^5.1.0", "express-rate-limit": "^8.2.1", "express-session": "^1.18.2", "helmet": "^8.1.0", "pg": "^8.16.3", "zod": "^4.1.12"},
  "devDependencies": {"supertest": "^7.1.4", "@playwright/test": "^1.56.1"}
}
'''
FILES['.gitignore'] = '''node_modules/\n.env\n.env.*\n!.env.example\ncoverage/\n*.log\n.DS_Store\nplaywright-report/\ntest-results/\n'''
FILES['.env.example'] = '''NODE_ENV=development
PORT=3000
DATABASE_URL=postgresql://postgres:password@localhost:5432/zudo
# Render private PostgreSQL connections: disable. External verified TLS: verify.
DATABASE_SSL=disable
SESSION_SECRET=replace-with-at-least-32-random-characters
OWNER_USERNAME=owner
# 12+ characters, lower/upper case, digit and symbol; never use 8318 in production.
OWNER_PASSWORD=
APP_ORIGIN=http://localhost:3000
SMM_API_KEY=
# Exact currency reported by provider balance; verify before accepting deposits/orders.
PROVIDER_CURRENCY=INR
# INR account verified at build time; re-check after rotating the API key.
PROVIDER_TO_INR=1
MARKUP_PERCENT=20
UPI_ID=Fearlessaditya@fam
SUPPORT_URL=https://t.me/manwithoutego
'''
FILES['render.yaml'] = '''services:
  - type: web
    name: zudo-smm-panel
    runtime: node
    plan: starter
    buildCommand: npm ci --omit=dev
    startCommand: npm start
    healthCheckPath: /healthz
    envVars:
      - key: NODE_ENV
        value: production
      - key: NODE_VERSION
        value: 22
      - key: DATABASE_URL
        fromDatabase:
          name: zudo-postgres
          property: connectionString
      - key: DATABASE_SSL
        value: disable
      - key: SESSION_SECRET
        generateValue: true
      - key: OWNER_USERNAME
        value: owner
      - key: OWNER_PASSWORD
        sync: false
      - key: SMM_API_KEY
        sync: false
      - key: PROVIDER_CURRENCY
        value: INR
      - key: PROVIDER_TO_INR
        value: 1
      - key: MARKUP_PERCENT
        value: 20
      - key: UPI_ID
        value: Fearlessaditya@fam
      - key: SUPPORT_URL
        value: https://t.me/manwithoutego
databases:
  - name: zudo-postgres
    plan: basic-256mb
    databaseName: zudo
    user: zudo
'''
FILES['migrations/001_initial.sql'] = r'''
CREATE TABLE users (
 id BIGSERIAL PRIMARY KEY, username VARCHAR(32) NOT NULL,
 password_hash TEXT NOT NULL, balance_paise BIGINT NOT NULL DEFAULT 0 CHECK(balance_paise >= 0),
 held_paise BIGINT NOT NULL DEFAULT 0 CHECK(held_paise >= 0 AND held_paise <= balance_paise),
 suspended BOOLEAN NOT NULL DEFAULT FALSE, auth_version INTEGER NOT NULL DEFAULT 1,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_username_ci ON users(lower(username));
CREATE TABLE services_cache (
 provider_service_id BIGINT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, type TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', provider_rate TEXT NOT NULL,
 retail_rate_micro BIGINT NOT NULL CHECK(retail_rate_micro > 0),
 min_quantity INTEGER NOT NULL CHECK(min_quantity > 0), max_quantity INTEGER NOT NULL CHECK(max_quantity >= min_quantity),
 enabled BOOLEAN NOT NULL DEFAULT FALSE, active BOOLEAN NOT NULL DEFAULT TRUE,
 compliance_note TEXT NOT NULL DEFAULT '', compliance_reviewed_at TIMESTAMPTZ,
 raw JSONB NOT NULL, synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX services_category_idx ON services_cache(category);
CREATE TABLE orders (
 id UUID PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
 service_id BIGINT NOT NULL REFERENCES services_cache(provider_service_id), service_name TEXT NOT NULL,
 target_url TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0), amount_paise BIGINT NOT NULL CHECK(amount_paise > 0),
 refunded_paise BIGINT NOT NULL DEFAULT 0 CHECK(refunded_paise >= 0 AND refunded_paise <= amount_paise),
 idempotency_key UUID NOT NULL, request_hash TEXT NOT NULL,
 provider_order_id VARCHAR(64) UNIQUE,
 state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','submitting','accepted','rejected','reconcile')),
 status TEXT NOT NULL DEFAULT 'Queued', provider_status TEXT,
 start_count TEXT, remains INTEGER, failure_code TEXT, reconciliation_note TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 last_checked_at TIMESTAMPTZ, UNIQUE(user_id, idempotency_key)
);
CREATE INDEX orders_user_idx ON orders(user_id, created_at DESC);
CREATE INDEX orders_work_idx ON orders(state, updated_at);
CREATE TABLE deposits (
 id UUID PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), amount_paise BIGINT NOT NULL CHECK(amount_paise BETWEEN 100 AND 100000000),
 utr VARCHAR(64) NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Approved','Rejected')),
 reason TEXT, reviewed_by TEXT, reviewed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX deposits_user_idx ON deposits(user_id, created_at DESC);
CREATE INDEX deposits_pending_idx ON deposits(status, created_at);
CREATE TABLE transactions (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
 amount_paise BIGINT NOT NULL CHECK(amount_paise <> 0), balance_after_paise BIGINT NOT NULL CHECK(balance_after_paise >= 0),
 kind TEXT NOT NULL CHECK(kind IN ('deposit','order','refund','manual')),
 reference TEXT NOT NULL UNIQUE, reason TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX transactions_user_idx ON transactions(user_id, created_at DESC);
CREATE TABLE admin_logs (
 id BIGSERIAL PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL,
 details JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE sessions (sid VARCHAR NOT NULL PRIMARY KEY, sess JSON NOT NULL, expire TIMESTAMP(6) NOT NULL);
CREATE INDEX sessions_expire_idx ON sessions(expire);
'''
FILES['src/config.js'] = r'''
require('dotenv').config({quiet:true});
const { z } = require('zod');
const strongPassword = value => typeof value === 'string' && value.length >= 12 && Buffer.byteLength(value) <= 72 && /[a-z]/.test(value) && /[A-Z]/.test(value) && /[0-9]/.test(value) && /[^A-Za-z0-9]/.test(value);
function loadConfig(env = process.env) {
 const production = env.NODE_ENV === 'production';
 const secret = env.SESSION_SECRET || '';
 if (secret.length < 32) throw new Error('SESSION_SECRET must contain at least 32 characters.');
 if (!env.DATABASE_URL) throw new Error('DATABASE_URL is required.');
 if (!strongPassword(env.OWNER_PASSWORD)) throw new Error('OWNER_PASSWORD must be 12+ characters with upper/lowercase, digit and symbol (max 72 bytes).');
 const origin = env.APP_ORIGIN || (env.RENDER_EXTERNAL_HOSTNAME ? 'https://' + env.RENDER_EXTERNAL_HOSTNAME : 'http://localhost:' + (env.PORT || 3000));
 if (production && !origin.startsWith('https://')) throw new Error('Production APP_ORIGIN must use HTTPS.');
 const currency = env.PROVIDER_CURRENCY || 'INR';
 const fx = env.PROVIDER_TO_INR || (currency === 'INR' ? '1' : '');
 if (!/^[A-Z]{3}$/.test(currency) || !/^\d+(\.\d{1,8})?$/.test(fx) || Number(fx) <= 0 || Number(fx) > 1000000) throw new Error('Set verified PROVIDER_CURRENCY and positive PROVIDER_TO_INR.');
 const markup = Number(env.MARKUP_PERCENT || 20);
 if (!Number.isFinite(markup) || markup < 0 || markup > 1000) throw new Error('Invalid MARKUP_PERCENT.');
 if (production && !env.SMM_API_KEY) throw new Error('SMM_API_KEY is required in production.');
 const ssl = env.DATABASE_SSL || 'disable';
 if (!['disable','verify'].includes(ssl)) throw new Error('DATABASE_SSL must be disable or verify.');
 return { production, origin: new URL(origin).origin, secret, databaseUrl: env.DATABASE_URL, ssl,
  ownerUsername: z.string().regex(/^[a-zA-Z0-9_]{3,32}$/).parse(env.OWNER_USERNAME || 'owner'), ownerPassword: env.OWNER_PASSWORD,
  providerKey: env.SMM_API_KEY || '', currency, fx, markup,
  upiId: env.UPI_ID || 'Fearlessaditya@fam', supportUrl: 'https://t.me/manwithoutego',
  port: Number(env.PORT || 3000) };
}
module.exports = { loadConfig, strongPassword };
'''
FILES['src/db.js'] = r'''
const { Pool } = require('pg');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
function createDb(config) {
 const pool = new Pool({ connectionString: config.databaseUrl, max: 15, connectionTimeoutMillis: 8000,
  idleTimeoutMillis: 30000, ssl: config.ssl === 'verify' ? {rejectUnauthorized: true} : false });
 pool.on('error', () => console.error(JSON.stringify({event:'database_pool_error'})));
 async function tx(fn) {
  const client = await pool.connect();
  try { await client.query('BEGIN'); const result = await fn(client); await client.query('COMMIT'); return result; }
  catch (error) { await client.query('ROLLBACK').catch(()=>{}); throw error; }
  finally { client.release(); }
 }
 async function migrate() {
  const client = await pool.connect();
  try {
   await client.query('SELECT pg_advisory_lock(891501)');
   await client.query('CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())');
   const dir = path.join(__dirname, '..', 'migrations');
   for (const name of (await fs.readdir(dir)).filter(n=>n.endsWith('.sql')).sort()) {
    const sql = await fs.readFile(path.join(dir, name), 'utf8');
    const checksum = crypto.createHash('sha256').update(sql).digest('hex');
    const previous = (await client.query('SELECT checksum FROM schema_migrations WHERE name=$1',[name])).rows[0];
    if (previous) { if(previous.checksum !== checksum) throw new Error('Applied migration was modified: '+name); continue; }
    await client.query('BEGIN');
    try { await client.query(sql); await client.query('INSERT INTO schema_migrations(name,checksum) VALUES($1,$2)',[name,checksum]); await client.query('COMMIT'); }
    catch(e) { await client.query('ROLLBACK'); throw e; }
   }
  } finally { await client.query('SELECT pg_advisory_unlock(891501)').catch(()=>{}); client.release(); }
 }
 return {pool, tx, migrate};
}
module.exports = {createDb};
'''
FILES['src/util.js'] = r'''
const crypto = require('node:crypto');
class AppError extends Error { constructor(status, code, message) { super(message); this.status=status; this.code=code; } }
const fail = (status,code,message) => { throw new AppError(status,code,message); };
function amountToPaise(s) {
 if(typeof s !== 'string' || !/^\d{1,7}(\.\d{1,2})?$/.test(s)) fail(400,'INVALID_AMOUNT','Enter an amount with at most two decimal places.');
 const [whole, fractional=''] = s.split('.'); return BigInt(whole)*100n+BigInt(fractional.padEnd(2,'0'));
}
const hash = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const page = req => ({limit:Math.min(100,Math.max(1,parseInt(req.query.limit,10)||25)), offset:Math.min(1000000,Math.max(0,parseInt(req.query.offset,10)||0))});
const validId = s => /^\d{1,15}$/.test(String(s));
const uuid = s => /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(s));
function safeTarget(value) {
 if (typeof value !== 'string' || value.length > 2048) fail(400,'TARGET','Enter a valid public HTTPS target URL.');
 let url; try { url=new URL(value); } catch { fail(400,'TARGET','Enter a valid public HTTPS target URL.'); }
 const host=url.hostname.toLowerCase();
 if(url.protocol!=='https:' || url.username || url.password || (url.port && url.port!=='443') || !host.includes('.') || host.endsWith('.local') || host.endsWith('.localhost') || host.endsWith('.internal') || /^[\d.]+$/.test(host) || host.includes(':')) fail(400,'TARGET','Use a public HTTPS URL without credentials.');
 return url.href;
}
async function audit(c,actor,action,subject,details={}) { await c.query('INSERT INTO admin_logs(actor,action,subject,details) VALUES($1,$2,$3,$4)',[actor,action,String(subject),JSON.stringify(details)]); }
module.exports={AppError, fail, amountToPaise, hash, page, validId, uuid, safeTarget, audit};
'''
FILES['src/provider.js'] = r'''
class ProviderFailure extends Error {
 constructor(kind) { super('Provider request failed.'); this.kind=kind; }
}
function createProvider(config) {
 const endpoint = 'https://mysmm.org/api/v2';
 async function call(action, fields={}) {
  if(!config.providerKey) throw new ProviderFailure('configuration');
  let response, body;
  try {
   response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:new URLSearchParams({key:config.providerKey,action,...fields}),signal:AbortSignal.timeout(20000),redirect:'error'});
   // Response size bound; never log raw responses or provider messages containing secrets.
   const chunks=[]; let size=0;
   for await (const chunk of response.body) { size+=chunk.length; if(size>10000000) throw new Error('size'); chunks.push(chunk); }
   body=JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch { throw new ProviderFailure('ambiguous'); }
  if(!response.ok) throw new ProviderFailure('ambiguous');
  if(body && !Array.isArray(body) && typeof body.error === 'string') throw new ProviderFailure('rejected');
  if(body===null || typeof body!=='object') throw new ProviderFailure('ambiguous');
  return body;
 }
 return {
  services:()=>call('services'), balance:()=>call('balance'),
  add:({service,target,quantity})=>call('add',{service:String(service),link:target,quantity:String(quantity)}),
  status:order=>call('status',{order:String(order)})
 };
}
module.exports={createProvider,ProviderFailure};
'''
FILES['src/domain.js'] = r'''
const {randomUUID} = require('node:crypto');
const Decimal = require('decimal.js');
Decimal.set({precision:60});
const {fail,hash,audit} = require('./util');
function createDomain(db,provider,config) {
 const {pool,tx} = db;
 async function ledger(c,userId,delta,kind,reference,reason) {
  const user=(await c.query('SELECT * FROM users WHERE id=$1 FOR UPDATE',[userId])).rows[0];
  if(!user) fail(404,'NOT_FOUND','Account not found.');
  const balance=BigInt(user.balance_paise)+BigInt(delta);
  if(balance < BigInt(user.held_paise)) fail(409,'INSUFFICIENT_BALANCE','Insufficient available wallet balance.');
  await c.query('UPDATE users SET balance_paise=$2,updated_at=now() WHERE id=$1',[userId,String(balance)]);
  await c.query('INSERT INTO transactions(user_id,amount_paise,balance_after_paise,kind,reference,reason) VALUES($1,$2,$3,$4,$5,$6)',[userId,String(delta),String(balance),kind,reference,reason]);
  return balance;
 }
 async function syncServices() {
  const balance=await provider.balance();
  if(balance.currency!==config.currency) {await pool.query('UPDATE services_cache SET active=false');fail(503,'CURRENCY_MISMATCH','Provider currency does not match configured currency. Ordering is paused.');}
  const services=await provider.services();
  if(!Array.isArray(services) || services.length===0 || services.length>100000) fail(502,'PROVIDER_CATALOGUE','Provider returned an invalid or empty catalogue.');
  const ids=new Set();
  const parsed=services.map(s=>{
   const id=String(s.service), min=Number(s.min), max=Number(s.max);
   if(!/^\d{1,15}$/.test(id) || id==='0' || ids.has(id) || typeof s.name!=='string' || !s.name.trim() || typeof s.category!=='string' || typeof s.type!=='string' || !Number.isSafeInteger(min) || !Number.isSafeInteger(max) || min<1 || max<min || max>2147483647 || !/^\d{1,24}(\.\d{1,18})?$/.test(String(s.rate))) fail(502,'PROVIDER_CATALOGUE','Provider catalogue validation failed. Previous catalogue retained.');
   ids.add(id);
   const rate=new Decimal(s.rate).mul(config.fx).mul(new Decimal(1).plus(new Decimal(config.markup).div(100))).mul(1000000).ceil();
   if(rate.lte(0) || rate.gte('1e40')) fail(502,'PROVIDER_RATE','Invalid service rate.');
   return {id,min,max,rate:rate.toFixed(0),name:s.name.slice(0,1000),category:s.category.slice(0,1000),type:s.type.slice(0,100),description:typeof s.description==='string'?s.description.slice(0,20000):'',raw:s};
  });
  await tx(async c=>{
   await c.query('SELECT pg_advisory_xact_lock(891503)');
   await c.query('UPDATE services_cache SET active=false');
   for(const s of parsed) {
    // Any upstream material change revokes the compliance approval; prices alone may change.
    await c.query(`INSERT INTO services_cache(provider_service_id,name,category,type,description,provider_rate,retail_rate_micro,min_quantity,max_quantity,raw)
     VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(provider_service_id) DO UPDATE SET
     enabled=CASE WHEN (services_cache.name,services_cache.category,services_cache.type,services_cache.description,services_cache.min_quantity,services_cache.max_quantity) IS DISTINCT FROM (EXCLUDED.name,EXCLUDED.category,EXCLUDED.type,EXCLUDED.description,EXCLUDED.min_quantity,EXCLUDED.max_quantity) THEN false ELSE services_cache.enabled END,
     name=EXCLUDED.name,category=EXCLUDED.category,type=EXCLUDED.type,description=EXCLUDED.description,provider_rate=EXCLUDED.provider_rate,
     retail_rate_micro=EXCLUDED.retail_rate_micro,min_quantity=EXCLUDED.min_quantity,max_quantity=EXCLUDED.max_quantity,raw=EXCLUDED.raw,active=true,synced_at=now()`,
     [s.id,s.name,s.category,s.type,s.description,String(s.raw.rate),s.rate,s.min,s.max,JSON.stringify(s.raw)]);
   }
  });
  return parsed.length;
 }
 async function queueOrder(userId,{serviceId,target,quantity,idempotencyKey,quotePaise}) {
  const fingerprint=hash([String(serviceId),target,quantity]);
  return tx(async c=>{
   const user=(await c.query('SELECT * FROM users WHERE id=$1 FOR UPDATE',[userId])).rows[0];
   if(!user || user.suspended) fail(403,'SUSPENDED','This account is suspended.');
   const existing=(await c.query('SELECT * FROM orders WHERE user_id=$1 AND idempotency_key=$2',[userId,idempotencyKey])).rows[0];
   if(existing) { if(existing.request_hash!==fingerprint) fail(409,'IDEMPOTENCY_CONFLICT','This request key was already used for a different order.'); return existing; }
   const service=(await c.query('SELECT * FROM services_cache WHERE provider_service_id=$1 FOR SHARE',[serviceId])).rows[0];
   if(!service || !service.active || !service.enabled || service.type!=='Default') fail(400,'INVALID_SERVICE','This service is not available for ordering.');
   if(Date.now()-new Date(service.synced_at).getTime()>30*60*1000) fail(503,'STALE_CATALOGUE','Catalogue refresh required. Please try again shortly.');
   if(quantity<service.min_quantity || quantity>service.max_quantity) fail(400,'QUANTITY','Quantity is outside this service’s allowed range.');
   const amount=(BigInt(service.retail_rate_micro)*BigInt(quantity)+9999999n)/10000000n;
   if(amount<1n || amount>100000000n) fail(400,'ORDER_AMOUNT','Order must cost between ₹0.01 and ₹10,00,000.');
   if(String(amount)!==String(quotePaise)) fail(409,'PRICE_CHANGED','Service price changed. Refresh the estimate before confirming.');
   if(BigInt(user.balance_paise)-BigInt(user.held_paise)<amount) fail(409,'INSUFFICIENT_BALANCE','Insufficient available wallet balance. Add funds first.');
   const id=randomUUID();
   await c.query('UPDATE users SET held_paise=held_paise+$2,updated_at=now() WHERE id=$1',[userId,String(amount)]);
   return (await c.query(`INSERT INTO orders(id,user_id,service_id,service_name,target_url,quantity,amount_paise,idempotency_key,request_hash)
    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *`,[id,userId,serviceId,service.name,target,quantity,String(amount),idempotencyKey,fingerprint])).rows[0];
  });
 }
 async function acceptOrder(c,order,providerId,actor=null,note=null) {
  if(!/^\d{1,20}$/.test(String(providerId))) fail(400,'PROVIDER_ID','A valid provider order ID is required.');
  // Lock order before user on all settlement paths.
  await c.query('SELECT id FROM users WHERE id=$1 FOR UPDATE',[order.user_id]);
  await c.query('UPDATE users SET held_paise=held_paise-$2 WHERE id=$1',[order.user_id,order.amount_paise]);
  await ledger(c,order.user_id,-BigInt(order.amount_paise),'order','order:'+order.id,'Order '+order.service_name);
  await c.query("UPDATE orders SET state='accepted',status='Pending',provider_order_id=$2,reconciliation_note=$3,updated_at=now() WHERE id=$1",[order.id,String(providerId),note]);
  if(actor) await audit(c,actor,'order.reconcile.accept',order.id,{providerId:String(providerId),note});
 }
 async function rejectOrder(c,order,code,actor=null,note=null) {
  await c.query('UPDATE users SET held_paise=held_paise-$2,updated_at=now() WHERE id=$1',[order.user_id,order.amount_paise]);
  await c.query("UPDATE orders SET state='rejected',status='Rejected',failure_code=$2,reconciliation_note=$3,updated_at=now() WHERE id=$1",[order.id,code,note]);
  if(actor) await audit(c,actor,'order.reconcile.reject',order.id,{note});
 }
 async function submitQueued() {
  const order=await tx(async c=>{
   const o=(await c.query("SELECT * FROM orders WHERE state='queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED")).rows[0];
   if(!o) return null;
   const u=(await c.query('SELECT suspended FROM users WHERE id=$1 FOR UPDATE',[o.user_id])).rows[0];
   if(u.suspended) {await rejectOrder(c,o,'ACCOUNT_SUSPENDED');return null;}
   const service=(await c.query('SELECT enabled,active FROM services_cache WHERE provider_service_id=$1',[o.service_id])).rows[0];
   if(!service.enabled || !service.active) {await rejectOrder(c,o,'SERVICE_DISABLED');return null;}
   await c.query("UPDATE orders SET state='submitting',status='Submitting',updated_at=now() WHERE id=$1",[o.id]);
   return o;
  });
  if(!order) return false;
  let result;
  try {
   result=await provider.add({service:order.service_id,target:order.target_url,quantity:order.quantity});
   if(!result || !/^\d{1,20}$/.test(String(result.order))) throw new Error('invalid');
  } catch(error) {
   await tx(async c=>{
    const current=(await c.query('SELECT * FROM orders WHERE id=$1 FOR UPDATE',[order.id])).rows[0];
    if(current.state!=='submitting') return;
    if(error.kind==='rejected') await rejectOrder(c,current,'PROVIDER_REJECTED');
    else await c.query("UPDATE orders SET state='reconcile',status='Needs review',failure_code='PROVIDER_UNCERTAIN',updated_at=now() WHERE id=$1",[order.id]);
   });
   return true;
  }
  await tx(async c=>{
   const current=(await c.query('SELECT * FROM orders WHERE id=$1 FOR UPDATE',[order.id])).rows[0];
   if(current.state==='submitting') await acceptOrder(c,current,result.order);
  });
  return true;
 }
 async function refreshOrder(id) {
  const order=(await pool.query('SELECT * FROM orders WHERE id=$1',[id])).rows[0];
  if(!order || !order.provider_order_id) fail(409,'NOT_SUBMITTED','This order has not been confirmed by the provider.');
  if(order.last_checked_at && Date.now()-new Date(order.last_checked_at)<15000) return order;
  const data=await provider.status(order.provider_order_id);
  const allowed=['Pending','In progress','Processing','Completed','Partial','Canceled','Cancelled'];
  if(!allowed.includes(data.status)) fail(502,'PROVIDER_STATUS','Provider returned an unrecognized status.');
  const remains=Number(data.remains);
  if(!/^\d{1,10}$/.test(String(data.remains)) || !Number.isSafeInteger(remains) || remains<0 || remains>order.quantity || (data.status==='Partial' && data.remains==='')) fail(502,'PROVIDER_STATUS','Provider returned invalid remaining quantity.');
  const terminal=s=>['Completed','Partial','Canceled','Cancelled'].includes(s);
  return tx(async c=>{
   const current=(await c.query('SELECT * FROM orders WHERE id=$1 FOR UPDATE',[id])).rows[0];
   if(current.state!=='accepted' || terminal(current.status)) return current;
   let refund=0n;
   // Retail refunds are prorated from the original INR charge, not untrusted provider charge strings.
   if(['Partial','Canceled','Cancelled'].includes(data.status)) refund=BigInt(current.amount_paise)*BigInt(remains)/BigInt(current.quantity);
   if(refund>BigInt(current.refunded_paise)) await ledger(c,current.user_id,refund-BigInt(current.refunded_paise),'refund','refund:'+id,'Unfulfilled quantity refund for order '+id);
   return (await c.query('UPDATE orders SET status=$2,provider_status=$2,start_count=$3,remains=$4,refunded_paise=$5,last_checked_at=now(),updated_at=now() WHERE id=$1 RETURNING *',[id,data.status,String(data.start_count||'0').slice(0,64),remains,String(refund)])).rows[0];
  });
 }
 async function reviewDeposit(id,actor,decision,reason) {
  return tx(async c=>{
   const deposit=(await c.query('SELECT * FROM deposits WHERE id=$1 FOR UPDATE',[id])).rows[0];
   if(!deposit) fail(404,'NOT_FOUND','Deposit not found.');
   if(deposit.status!== 'Pending') { if(deposit.status===decision) return deposit; fail(409,'ALREADY_REVIEWED','This deposit has already been reviewed.'); }
   if(decision==='Approved') await ledger(c,deposit.user_id,BigInt(deposit.amount_paise),'deposit','deposit:'+id,'Verified UPI deposit '+deposit.utr);
   await audit(c,actor,'deposit.'+decision.toLowerCase(),id,{amount:deposit.amount_paise,reason});
   return (await c.query('UPDATE deposits SET status=$2,reason=$3,reviewed_by=$4,reviewed_at=now() WHERE id=$1 RETURNING *',[id,decision,reason,actor])).rows[0];
  });
 }
 async function reconcile(id,actor,providerId,note) {
  let details;
  if(providerId) {
   details=await provider.status(providerId);
   if(!details || !['Pending','In progress','Processing','Completed','Partial','Canceled','Cancelled'].includes(details.status)) fail(400,'PROVIDER_ID','Unable to verify this provider order ID.');
  }
  return tx(async c=>{
   const o=(await c.query('SELECT * FROM orders WHERE id=$1 FOR UPDATE',[id])).rows[0];
   if(!o) fail(404,'NOT_FOUND','Order not found.');
   if(o.state!=='reconcile') fail(409,'NOT_RECONCILABLE','Only uncertain orders can be reconciled.');
   if(providerId) await acceptOrder(c,o,providerId,actor,note);
   else await rejectOrder(c,o,'OWNER_VERIFIED_NO_ORDER',actor,note);
  });
 }
 return {ledger,syncServices,queueOrder,submitQueued,refreshOrder,reviewDeposit,reconcile};
}
module.exports={createDomain};
'''
FILES['src/worker.js'] = r'''
function startWorker(db,domain) {
 let busy=false, stopped=false, lastSync=0, lastCleanup=0;
 async function tick() {
  if(busy||stopped) return; busy=true;
  let c,locked=false;
  try {
   c=await db.pool.connect();
   locked=(await c.query('SELECT pg_try_advisory_lock(891502) AS locked')).rows[0].locked;
   if(!locked) return;
   if(Date.now()-lastCleanup>60*60*1000){await c.query("DELETE FROM request_limits WHERE reset_at<now()-interval '1 day'");lastCleanup=Date.now();}
   // A crash or response lost after provider acceptance must NEVER cause an automatic retry.
   await c.query("UPDATE orders SET state='reconcile',status='Needs review',failure_code='INTERRUPTED_SUBMISSION',updated_at=now() WHERE state='submitting' AND updated_at < now()-interval '2 minutes'");
   if(Date.now()-lastSync>15*60*1000) {
    lastSync=Date.now();
    try {await domain.syncServices();} catch {console.warn(JSON.stringify({event:'catalogue_sync_failed'})); lastSync=Date.now()-14*60*1000;}
   }
   for(let n=0;n<8 && !stopped;n++) if(!await domain.submitQueued()) break;
   const orders=(await c.query("SELECT id FROM orders WHERE state='accepted' AND status NOT IN ('Completed','Partial','Canceled','Cancelled') AND (last_checked_at IS NULL OR last_checked_at<now()-interval '30 seconds') ORDER BY last_checked_at NULLS FIRST LIMIT 30")).rows;
   for(const order of orders) {if(stopped) break; try {await domain.refreshOrder(order.id);} catch {console.warn(JSON.stringify({event:'order_status_refresh_failed',orderId:order.id})); await c.query('UPDATE orders SET last_checked_at=now() WHERE id=$1',[order.id]);}}
  } catch {console.error(JSON.stringify({event:'worker_iteration_failed'}));}
  finally {if(c) {if(locked) await c.query('SELECT pg_advisory_unlock(891502)').catch(()=>{});c.release();} busy=false;}
 }
 const interval=setInterval(tick,3000); interval.unref(); void tick();
 return async()=>{stopped=true;clearInterval(interval);while(busy) await new Promise(r=>setTimeout(r,100));};
}
module.exports={startWorker};
'''
FILES['migrations/002_rate_limits.sql'] = r'''
CREATE TABLE request_limits (key TEXT PRIMARY KEY, hits INTEGER NOT NULL DEFAULT 1, reset_at TIMESTAMPTZ NOT NULL);
CREATE INDEX request_limits_reset_idx ON request_limits(reset_at);
'''
FILES['src/app.js'] = r'''
const express=require('express');
const helmet=require('helmet');
const session=require('express-session');
const PgSession=require('connect-pg-simple')(session);
const {rateLimit}=require('express-rate-limit');
const bcrypt=require('bcrypt');
const {z}=require('zod');
const {randomBytes,randomUUID,timingSafeEqual}=require('node:crypto');
const path=require('node:path');
const {strongPassword}=require('./config');
const {fail,AppError,amountToPaise,page,validId,uuid,safeTarget,audit}=require('./util');
const {createDomain}=require('./domain');
const username=z.string().regex(/^[a-zA-Z0-9_]{3,32}$/,'Username must be 3–32 letters, numbers or underscores.');
const password=z.string().refine(strongPassword,'Use 12+ characters including uppercase, lowercase, a digit and a symbol (max 72 bytes).');
class PgRateStore {
 constructor(pool,prefix){this.pool=pool;this.prefix=prefix;this.localKeys=false;}
 init(options){this.windowMs=options.windowMs;}
 async increment(key){
  const row=(await this.pool.query(`INSERT INTO request_limits(key,reset_at) VALUES($1,now()+($2::text||' milliseconds')::interval)
    ON CONFLICT(key) DO UPDATE SET hits=CASE WHEN request_limits.reset_at<now() THEN 1 ELSE request_limits.hits+1 END,
    reset_at=CASE WHEN request_limits.reset_at<now() THEN EXCLUDED.reset_at ELSE request_limits.reset_at END RETURNING hits,reset_at`,[this.prefix+key,this.windowMs])).rows[0];
  return {totalHits:row.hits,resetTime:new Date(row.reset_at)};
 }
 async decrement(key){await this.pool.query('UPDATE request_limits SET hits=GREATEST(0,hits-1) WHERE key=$1',[this.prefix+key]);}
 async resetKey(key){await this.pool.query('DELETE FROM request_limits WHERE key=$1',[this.prefix+key]);}
}
async function createApp(config,db,provider) {
 const app=express(); const {pool,tx}=db; const domain=createDomain(db,provider,config);
 const ownerHash=await bcrypt.hash(config.ownerPassword,12);
 app.disable('x-powered-by'); app.set('trust proxy',config.production?1:false);
 app.use(helmet({contentSecurityPolicy:{directives:{defaultSrc:["'self'"],scriptSrc:["'self'"],styleSrc:["'self'"],imgSrc:["'self'",'data:'],fontSrc:["'self'"],connectSrc:["'self'"],formAction:["'self'"],frameAncestors:["'none'"],upgradeInsecureRequests:config.production?[]:null}},strictTransportSecurity:config.production?undefined:false}));
 app.get('/healthz',async(req,res)=>{try{await pool.query('SELECT 1');res.json({status:'ok'});}catch{res.status(503).json({status:'unavailable'});}});
 app.use('/api', (req,res,next)=>{res.set('Cache-Control','no-store');next();});
 const limit=(prefix,max,windowMs)=>rateLimit({windowMs,limit:max,standardHeaders:'draft-8',legacyHeaders:false,store:new PgRateStore(pool,prefix),message:{error:{code:'RATE_LIMIT',message:'Too many requests. Please wait before trying again.'}}});
 app.use('/api',limit('api:',500,60000));
 app.use(express.json({limit:'32kb',strict:true}));
 const cookieBase={httpOnly:true,secure:config.production,sameSite:'strict',path:'/',maxAge:8*60*60*1000};
 const options={secret:config.secret,resave:false,saveUninitialized:false,rolling:true,cookie:cookieBase};
 const userSession=session({...options,name:'zudo.sid',store:new PgSession({pool,tableName:'sessions',createTableIfMissing:false,pruneSessionInterval:900})});
 const ownerSession=session({...options,name:'zudo.owner',secret:config.secret+':owner',cookie:{...cookieBase,maxAge:2*60*60*1000},store:new PgSession({pool,tableName:'sessions',createTableIfMissing:false,pruneSessionInterval:false})});
 app.use('/api',(req,res,next)=> (req.path.startsWith('/admin/')?ownerSession:userSession)(req,res,next));
 app.use('/api',(req,res,next)=>{
  if(['GET','HEAD','OPTIONS'].includes(req.method))return next();
  const a=req.session.csrf,b=req.get('X-CSRF-Token');
  if(req.get('Origin')!==config.origin || typeof a!=='string' || typeof b!=='string' || Buffer.byteLength(a)!==Buffer.byteLength(b) || !timingSafeEqual(Buffer.from(a),Buffer.from(b))) return next(new AppError(403,'CSRF','Your security token expired. Reload the page.'));
  next();
 });
 const csrf=(req,res)=>{if(!req.session.csrf)req.session.csrf=randomBytes(32).toString('hex');res.json({csrfToken:req.session.csrf});};
 app.get('/api/auth/csrf',csrf); app.get('/api/admin/auth/csrf',csrf);
 const regenerate=req=>new Promise((resolve,reject)=>req.session.regenerate(e=>e?reject(e):resolve()));
 const destroy=req=>new Promise((resolve,reject)=>req.session.destroy(e=>e?reject(e):resolve()));
 const userAuth=async(req,res,next)=>{
  if(!req.session.userId)return next(new AppError(401,'UNAUTHENTICATED','Please log in to continue.'));
  try{const user=(await pool.query('SELECT id,username,balance_paise,held_paise,suspended,auth_version,created_at FROM users WHERE id=$1',[req.session.userId])).rows[0];
   if(!user || user.auth_version!==req.session.authVersion || user.suspended)fail(401,'SESSION_EXPIRED','Your session expired or this account is suspended.');
   req.user=user;next();}catch(e){next(e);}
 };
 const ownerAuth=(req,res,next)=>req.session.owner===config.ownerUsername?next():next(new AppError(401,'OWNER_REQUIRED','Owner login required.'));
 const authLimiter=limit('auth:',20,15*60000);
 app.post('/api/auth/register',authLimiter,async(req,res)=>{
  const data=z.object({username,password,confirmPassword:z.string()}).parse(req.body);
  if(data.password!==data.confirmPassword)fail(400,'PASSWORD_MISMATCH','Passwords do not match.');
  if(data.username.toLowerCase()===config.ownerUsername.toLowerCase())fail(409,'USERNAME_TAKEN','That username is reserved.');
  const encoded=await bcrypt.hash(data.password,12);
  let user;
  try{user=(await pool.query('INSERT INTO users(username,password_hash) VALUES($1,$2) RETURNING id,username,auth_version',[data.username,encoded])).rows[0];}
  catch(e){if(e.code==='23505')fail(409,'USERNAME_TAKEN','That username is already in use.');throw e;}
  await regenerate(req);req.session.userId=user.id;req.session.authVersion=user.auth_version;req.session.csrf=randomBytes(32).toString('hex');
  res.status(201).json({username:user.username,csrfToken:req.session.csrf});
 });
 app.post('/api/auth/login',authLimiter,async(req,res)=>{
  const data=z.object({username:z.string().min(1).max(32),password:z.string().max(128)}).parse(req.body);
  const user=(await pool.query('SELECT * FROM users WHERE lower(username)=lower($1)',[data.username])).rows[0];
  const okay=await bcrypt.compare(data.password,user?.password_hash||ownerHash);
  if(!user || !okay || user.suspended)fail(401,'INVALID_CREDENTIALS','Invalid login credentials or suspended account.');
  await regenerate(req);req.session.userId=user.id;req.session.authVersion=user.auth_version;req.session.csrf=randomBytes(32).toString('hex');
  res.json({username:user.username,csrfToken:req.session.csrf});
 });
 app.post('/api/admin/auth/login',authLimiter,async(req,res)=>{
  const data=z.object({username:z.string().min(1).max(32),password:z.string().max(128)}).parse(req.body);
  const okay=await bcrypt.compare(data.password,ownerHash);
  if(data.username!==config.ownerUsername || !okay)fail(401,'INVALID_CREDENTIALS','Invalid owner credentials.');
  await regenerate(req);req.session.owner=config.ownerUsername;req.session.csrf=randomBytes(32).toString('hex');
  await tx(c=>audit(c,config.ownerUsername,'owner.login','owner'));
  res.json({username:config.ownerUsername,csrfToken:req.session.csrf});
 });
 app.post('/api/auth/logout',async(req,res)=>{await destroy(req);res.clearCookie('zudo.sid',{path:'/',httpOnly:true,secure:config.production,sameSite:'strict'});res.json({ok:true});});
 app.post('/api/admin/auth/logout',async(req,res)=>{await destroy(req);res.clearCookie('zudo.owner',{path:'/',httpOnly:true,secure:config.production,sameSite:'strict'});res.json({ok:true});});
 app.get('/api/public/config',(req,res)=>res.json({brand:'ZUDO SMM PANEL',upiId:config.upiId,supportUrl:config.supportUrl,currency:'INR'}));
 const user=express.Router();user.use(userAuth);app.use('/api/user',user);
 user.get('/me',(req,res)=>res.json({...req.user,available_paise:String(BigInt(req.user.balance_paise)-BigInt(req.user.held_paise))}));
 user.get('/dashboard',async(req,res)=>{
  const stats=(await pool.query(`SELECT count(*)::int AS total,count(*) FILTER(WHERE status='Completed')::int AS completed,
   count(*) FILTER(WHERE status NOT IN ('Completed','Partial','Canceled','Cancelled','Rejected'))::int AS pending FROM orders WHERE user_id=$1`,[req.user.id])).rows[0];
  const recentOrders=(await pool.query('SELECT * FROM orders WHERE user_id=$1 ORDER BY created_at DESC LIMIT 5',[req.user.id])).rows;
  const transactions=(await pool.query('SELECT * FROM transactions WHERE user_id=$1 ORDER BY created_at DESC LIMIT 5',[req.user.id])).rows;
  res.json({user:{...req.user,available_paise:String(BigInt(req.user.balance_paise)-BigInt(req.user.held_paise))},stats,recentOrders,transactions});
 });
 async function catalogue(req,res,isAdmin=false) {
  const {limit,offset}=page(req);const q=String(req.query.q||'').slice(0,200);const category=String(req.query.category||'').slice(0,1000);
  const where=`WHERE ($1='' OR name ILIKE '%'||$1||'%' OR provider_service_id::text=$1) AND ($2='' OR category=$2) ${isAdmin?'':"AND enabled AND active AND type='Default'"}`;
  const items=(await pool.query(`SELECT provider_service_id,name,category,type,description,retail_rate_micro,min_quantity,max_quantity,enabled,active,compliance_note,synced_at FROM services_cache ${where} ORDER BY category,name,provider_service_id LIMIT $3 OFFSET $4`,[q,category,limit,offset])).rows;
  const total=(await pool.query(`SELECT count(*)::int AS n FROM services_cache ${where}`,[q,category])).rows[0].n;
  const categories=(await pool.query(`SELECT DISTINCT category FROM services_cache ${isAdmin?'':"WHERE enabled AND active AND type='Default'"} ORDER BY category`)).rows.map(r=>r.category);
  res.json({items,total,categories,limit,offset});
 }
 user.get('/services',(req,res)=>catalogue(req,res));
 user.post('/orders',limit('orders:',30,60000),async(req,res)=>{
  const data=z.object({serviceId:z.string().regex(/^\d{1,15}$/),target:z.string(),quantity:z.number().int().positive().max(2147483647),idempotencyKey:z.uuid(),quotePaise:z.string().regex(/^\d{1,12}$/)}).parse(req.body);
  data.target=safeTarget(data.target);
  const order=await domain.queueOrder(req.user.id,data);res.status(202).json({order});
 });
 user.get('/orders',async(req,res)=>{const {limit,offset}=page(req);res.json({items:(await pool.query('SELECT * FROM orders WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3',[req.user.id,limit,offset])).rows,limit,offset});});
 const ownOrder=async(req)=>{if(!uuid(req.params.id))fail(404,'NOT_FOUND','Order not found.');const o=(await pool.query('SELECT * FROM orders WHERE id=$1 AND user_id=$2',[req.params.id,req.user.id])).rows[0];if(!o)fail(404,'NOT_FOUND','Order not found.');return o;};
 user.get('/orders/:id',async(req,res)=>res.json({order:await ownOrder(req)}));
 user.post('/orders/:id/refresh',async(req,res)=>{await ownOrder(req);res.json({order:await domain.refreshOrder(req.params.id)});});
 user.post('/deposits',limit('deposits:',10,60000),async(req,res)=>{
  const data=z.object({amount:z.string(),utr:z.string().trim().toUpperCase().regex(/^[A-Z0-9]{8,64}$/,'UTR must contain 8–64 letters or digits.')}).parse(req.body);
  const amount=amountToPaise(data.amount);if(amount<100n||amount>100000000n)fail(400,'AMOUNT_RANGE','Deposit must be between ₹1 and ₹10,00,000.');
  try{const deposit=(await pool.query('INSERT INTO deposits(id,user_id,amount_paise,utr) VALUES($1,$2,$3,$4) RETURNING *',[randomUUID(),req.user.id,String(amount),data.utr])).rows[0];res.status(201).json({deposit});}
  catch(e){if(e.code==='23505')fail(409,'DUPLICATE_UTR','This payment reference has already been submitted.');throw e;}
 });
 user.get('/deposits',async(req,res)=>{const {limit,offset}=page(req);res.json({items:(await pool.query('SELECT * FROM deposits WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3',[req.user.id,limit,offset])).rows,limit,offset});});
 user.get('/transactions',async(req,res)=>{const {limit,offset}=page(req);res.json({items:(await pool.query('SELECT * FROM transactions WHERE user_id=$1 ORDER BY created_at DESC,id DESC LIMIT $2 OFFSET $3',[req.user.id,limit,offset])).rows,limit,offset});});
 user.post('/password',authLimiter,async(req,res)=>{
  const data=z.object({currentPassword:z.string().max(128),newPassword:password,confirmPassword:z.string()}).parse(req.body);
  if(data.newPassword!==data.confirmPassword)fail(400,'PASSWORD_MISMATCH','New passwords do not match.');
  const current=(await pool.query('SELECT password_hash FROM users WHERE id=$1',[req.user.id])).rows[0];
  if(!await bcrypt.compare(data.currentPassword,current.password_hash))fail(400,'WRONG_PASSWORD','Current password is incorrect.');
  const encoded=await bcrypt.hash(data.newPassword,12);
  const changed=(await pool.query('UPDATE users SET password_hash=$2,auth_version=auth_version+1,updated_at=now() WHERE id=$1 AND password_hash=$3 RETURNING auth_version',[req.user.id,encoded,current.password_hash])).rows[0];
  if(!changed)fail(409,'PASSWORD_CHANGED','Password changed in another session. Please log in again.');
  await regenerate(req);req.session.userId=req.user.id;req.session.authVersion=changed.auth_version;req.session.csrf=randomBytes(32).toString('hex');res.json({ok:true,csrfToken:req.session.csrf});
 });
 const admin=express.Router();admin.use(ownerAuth);app.use('/api/admin',admin);
 admin.get('/me',(req,res)=>res.json({username:config.ownerUsername}));
 admin.get('/dashboard',async(req,res)=>{
  const users=(await pool.query('SELECT count(*)::int AS total FROM users')).rows[0];
  const orders=(await pool.query("SELECT count(*)::int AS total,count(*) FILTER(WHERE state='reconcile')::int AS review FROM orders")).rows[0];
  const deposits=(await pool.query(`SELECT count(*)::int AS total,count(*) FILTER(WHERE status='Pending')::int AS pending,
    count(*) FILTER(WHERE status='Approved')::int AS approved,count(*) FILTER(WHERE status='Rejected')::int AS rejected,
    COALESCE(sum(amount_paise) FILTER(WHERE status='Approved'),0)::text AS approved_paise FROM deposits`)).rows[0];
  const catalogue=(await pool.query('SELECT count(*)::int AS total,count(*) FILTER(WHERE enabled AND active)::int AS enabled,max(synced_at) AS synced_at FROM services_cache')).rows[0];
  res.json({users,orders,deposits,catalogue});
 });
 admin.get('/services',(req,res)=>catalogue(req,res,true));
 admin.post('/services/sync',limit('sync:',5,60000),async(req,res)=>{const count=await domain.syncServices();await tx(c=>audit(c,config.ownerUsername,'catalogue.sync','catalogue',{count}));res.json({count});});
 admin.post('/services/:id/policy',async(req,res)=>{
  if(!validId(req.params.id))fail(404,'NOT_FOUND','Service not found.');
  const data=z.object({enabled:z.boolean(),reason:z.string().trim().min(20).max(2000)}).parse(req.body);
  await tx(async c=>{
   const s=(await c.query('SELECT * FROM services_cache WHERE provider_service_id=$1 FOR UPDATE',[req.params.id])).rows[0];
   if(!s)fail(404,'NOT_FOUND','Service not found.');
   if(data.enabled && (s.type!=='Default'||!s.active))fail(400,'UNSUPPORTED_SERVICE','Only active Default-type services with verified compliant use can be enabled.');
   await c.query('UPDATE services_cache SET enabled=$2,compliance_note=$3,compliance_reviewed_at=now() WHERE provider_service_id=$1',[req.params.id,data.enabled,data.reason]);
   await audit(c,config.ownerUsername,'service.policy',req.params.id,data);
  });res.json({ok:true});
 });
 admin.get('/deposits',async(req,res)=>{const {limit,offset}=page(req);const status=['Pending','Approved','Rejected'].includes(req.query.status)?req.query.status:'';res.json({items:(await pool.query(`SELECT d.*,u.username FROM deposits d JOIN users u ON u.id=d.user_id WHERE ($1='' OR d.status=$1) ORDER BY d.created_at DESC LIMIT $2 OFFSET $3`,[status,limit,offset])).rows,limit,offset});});
 admin.post('/deposits/:id/review',async(req,res)=>{
  if(!uuid(req.params.id))fail(404,'NOT_FOUND','Deposit not found.');
  const d=z.object({decision:z.enum(['Approved','Rejected']),reason:z.string().trim().min(10).max(2000),verified:z.boolean()}).parse(req.body);
  if(d.decision==='Approved'&&!d.verified)fail(400,'VERIFY_PAYMENT','Independently verify the payment in your bank or UPI account first.');
  res.json({deposit:await domain.reviewDeposit(req.params.id,config.ownerUsername,d.decision,d.reason)});
 });
 admin.get('/users',async(req,res)=>{const {limit,offset}=page(req);const q=String(req.query.q||'').slice(0,200);res.json({items:(await pool.query("SELECT id,username,balance_paise,held_paise,suspended,created_at FROM users WHERE ($1='' OR username ILIKE '%'||$1||'%') ORDER BY created_at DESC LIMIT $2 OFFSET $3",[q,limit,offset])).rows,limit,offset});});
 admin.get('/users/:id',async(req,res)=>{
  if(!validId(req.params.id))fail(404,'NOT_FOUND','Account not found.');
  const u=(await pool.query('SELECT id,username,balance_paise,held_paise,suspended,created_at FROM users WHERE id=$1',[req.params.id])).rows[0];if(!u)fail(404,'NOT_FOUND','Account not found.');
  const {limit,offset}=page(req);
  res.json({user:u,orders:(await pool.query('SELECT * FROM orders WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3',[u.id,limit,offset])).rows,transactions:(await pool.query('SELECT * FROM transactions WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3',[u.id,limit,offset])).rows,limit,offset});
 });
 admin.post('/users/:id/suspend',async(req,res)=>{
  if(!validId(req.params.id))fail(404,'NOT_FOUND','Account not found.');
  const d=z.object({suspended:z.boolean(),reason:z.string().trim().min(10).max(2000)}).parse(req.body);
  await tx(async c=>{const u=(await c.query('UPDATE users SET suspended=$2,auth_version=auth_version+1,updated_at=now() WHERE id=$1 RETURNING id',[req.params.id,d.suspended])).rows[0];if(!u)fail(404,'NOT_FOUND','Account not found.');await audit(c,config.ownerUsername,'user.suspension',u.id,d);});res.json({ok:true});
 });
 admin.post('/users/:id/wallet',async(req,res)=>{
  if(!validId(req.params.id))fail(404,'NOT_FOUND','Account not found.');
  const d=z.object({direction:z.enum(['credit','debit']),amount:z.string(),reason:z.string().trim().min(10).max(2000),idempotencyKey:z.uuid()}).parse(req.body);
  const amount=amountToPaise(d.amount);if(amount<1n||amount>100000000n)fail(400,'AMOUNT_RANGE','Adjustment must be ₹0.01–₹10,00,000.');
  const delta=d.direction==='credit'?amount:-amount;
  await tx(async c=>{
   const u=(await c.query('SELECT id FROM users WHERE id=$1 FOR UPDATE',[req.params.id])).rows[0];if(!u)fail(404,'NOT_FOUND','Account not found.');
   const reference='manual:'+d.idempotencyKey;const old=(await c.query('SELECT * FROM transactions WHERE reference=$1',[reference])).rows[0];
   if(old){if(old.user_id!==req.params.id||old.amount_paise!==String(delta)||old.reason!==d.reason)fail(409,'IDEMPOTENCY_CONFLICT','This adjustment key was already used.');return;}
   await domain.ledger(c,u.id,delta,'manual',reference,d.reason);
   await audit(c,config.ownerUsername,'wallet.'+d.direction,u.id,{amount:String(amount),reason:d.reason,reference});
  });res.json({ok:true});
 });
 admin.get('/orders',async(req,res)=>{const {limit,offset}=page(req);res.json({items:(await pool.query('SELECT o.*,u.username FROM orders o JOIN users u ON u.id=o.user_id WHERE ($1=false OR o.state=\'reconcile\') ORDER BY o.created_at DESC LIMIT $2 OFFSET $3',[req.query.review==='true',limit,offset])).rows,limit,offset});});
 admin.post('/orders/:id/refresh',async(req,res)=>{if(!uuid(req.params.id))fail(404,'NOT_FOUND','Order not found.');res.json({order:await domain.refreshOrder(req.params.id)});});
 admin.post('/orders/:id/reconcile',async(req,res)=>{
  if(!uuid(req.params.id))fail(404,'NOT_FOUND','Order not found.');
  const d=z.object({providerId:z.string().regex(/^\d{1,20}$/).nullable(),reason:z.string().trim().min(20).max(2000),verified:z.literal(true)}).parse(req.body);
  await domain.reconcile(req.params.id,config.ownerUsername,d.providerId,d.reason);res.json({ok:true});
 });
 admin.get('/transactions',async(req,res)=>{const {limit,offset}=page(req);res.json({items:(await pool.query('SELECT t.*,u.username FROM transactions t JOIN users u ON u.id=t.user_id ORDER BY t.created_at DESC,t.id DESC LIMIT $1 OFFSET $2',[limit,offset])).rows,limit,offset});});
 admin.get('/audit',async(req,res)=>{const {limit,offset}=page(req);res.json({items:(await pool.query('SELECT * FROM admin_logs ORDER BY created_at DESC,id DESC LIMIT $1 OFFSET $2',[limit,offset])).rows,limit,offset});});
 app.use('/api',(req,res)=>res.status(404).json({error:{code:'NOT_FOUND',message:'Endpoint not found.'}}));
 app.use(express.static(path.join(__dirname,'..','public'),{index:false,maxAge:config.production?'1h':0}));
 for(const route of ['/','/login','/register','/admin','/admin/login'])app.get(route,(req,res)=>{res.set('Cache-Control','no-store');res.sendFile(path.join(__dirname,'..','public','index.html'));});
 app.use((req,res)=>res.status(404).type('text').send('Page not found.'));
 app.use((error,req,res,next)=>{
  if(res.headersSent)return next(error);
  const requestId=randomUUID();
  if(error instanceof z.ZodError)return res.status(400).json({error:{code:'VALIDATION',message:error.issues[0]?.message||'Check the submitted fields.'}});
  if(error instanceof AppError)return res.status(error.status).json({error:{code:error.code,message:error.message}});
  if(error.type==='entity.parse.failed')return res.status(400).json({error:{code:'INVALID_JSON',message:'Invalid request body.'}});
  if(error.type==='entity.too.large')return res.status(413).json({error:{code:'TOO_LARGE',message:'Request is too large.'}});
  if(error.name==='ProviderFailure')return res.status(503).json({error:{code:'PROVIDER_UNAVAILABLE',message:'Provider is temporarily unavailable. No automatic retry will submit a duplicate order.'}});
  console.error(JSON.stringify({event:'request_failed',requestId,code:/^[A-Z0-9]{3,20}$/.test(error.code||'')?error.code:'INTERNAL'}));
  res.status(500).json({error:{code:'INTERNAL',message:'Unable to complete this request. Please try again later.',requestId}});
 });
 return {app,domain};
}
module.exports={createApp};
'''
FILES['server.js'] = r'''
const {loadConfig}=require('./src/config');
const {createDb}=require('./src/db');
const {createProvider}=require('./src/provider');
const {createApp}=require('./src/app');
const {startWorker}=require('./src/worker');
async function main(){
 const config=loadConfig();const db=createDb(config);await db.migrate();
 const {app,domain}=await createApp(config,db,createProvider(config));
 const stopWorker=startWorker(db,domain);
 const server=app.listen(config.port,'0.0.0.0',()=>console.log(JSON.stringify({event:'listening',port:config.port})));
 server.requestTimeout=30000;server.headersTimeout=10000;
 let closing=false;
 async function close(){if(closing)return;closing=true;const hard=setTimeout(()=>process.exit(1),55000);hard.unref();const drained=new Promise(resolve=>server.close(resolve));server.closeIdleConnections();await Promise.all([stopWorker(),drained]);await db.pool.end();clearTimeout(hard);process.exit(0);}
 process.on('SIGTERM',close);process.on('SIGINT',close);
}
main().catch(()=>{console.error('Startup failed. Check required environment variables, PostgreSQL connection and migration integrity.');process.exit(1);});
'''
FILES['scripts/migrate.js'] = r'''
const {loadConfig}=require('../src/config');const {createDb}=require('../src/db');
(async()=>{const db=createDb(loadConfig());try{await db.migrate();console.log('Migrations applied.');}finally{await db.pool.end();}})().catch(()=>{console.error('Migration failed; check database access and configuration.');process.exitCode=1;});
'''
FILES['scripts/check.js'] = r'''
const {readdirSync,statSync}=require('node:fs');const {join}=require('node:path');const {execFileSync}=require('node:child_process');
function walk(dir){for(const file of readdirSync(dir)){if(['node_modules','.git'].includes(file))continue;const p=join(dir,file);if(statSync(p).isDirectory())walk(p);else if(p.endsWith('.js'))execFileSync(process.execPath,['--check',p],{stdio:'inherit'});}}
walk('.');console.log('All JavaScript syntax checks passed.');
'''
FILES['public/index.html'] = r'''<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="dark"><meta name="theme-color" content="#090c15"><meta name="description" content="ZUDO SMM PANEL — your secure service and wallet workspace."><title>ZUDO SMM PANEL</title><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/styles.css"><script src="/app.js" defer></script></head><body><div id="app"><div class="boot"><span class="brand-mark">Z</span><span class="spinner"></span><p>Opening your workspace…</p></div></div><div id="toasts" aria-live="polite"></div><dialog id="modal"><div id="modal-content"></div></dialog></body></html>
'''
FILES['public/favicon.svg'] = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#7955ed"/><path d="M18 19h28L23 45h23M18 45l28-26" stroke="white" stroke-width="5" fill="none" stroke-linejoin="round"/></svg>'''
FILES['public/styles.css'] = r'''
:root{--bg:#090c15;--panel:#111522;--panel2:#171c2d;--line:#252b40;--text:#f2f3fc;--muted:#929db8;--purple:#9976ff;--cyan:#53d2d6;--red:#ff8f9c;--green:#63dec0;--radius:18px;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--text);background:var(--bg);font-synthesis:none;color-scheme:dark}*{box-sizing:border-box}body{margin:0}button,input,select,textarea{font:inherit}button,a,input,select,textarea{-webkit-tap-highlight-color:transparent}a{color:var(--purple);text-decoration:none}a:hover{color:#c7b2ff}button{cursor:pointer}button:disabled{opacity:.5;cursor:wait}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid var(--cyan);outline-offset:3px}h1,h2,h3,p{margin-top:0}h1{font-size:clamp(26px,3vw,36px);line-height:1.2;letter-spacing:-1.2px;margin-bottom:10px}h2{font-size:18px;letter-spacing:-.4px}h3{font-size:15px}p{line-height:1.65}small{font-size:12px}.muted{color:var(--muted)}.eyebrow{font-size:11px;letter-spacing:2px;font-weight:750;color:var(--cyan);text-transform:uppercase}.brand{display:flex;gap:12px;align-items:center;font-weight:800;color:var(--text);font-size:15px;letter-spacing:.5px}.brand small{display:block;color:var(--muted);font-size:9px;letter-spacing:2.4px;margin-top:4px}.brand-mark{display:grid;place-items:center;border:1px solid #b19aff66;background:linear-gradient(135deg,#ab83ff,#5b39c4);width:40px;height:42px;border-radius:12px;color:white;font-size:27px;font-weight:900;box-shadow:0 6px 24px #6d42d229}.sidebar{width:250px;position:fixed;left:0;top:0;bottom:0;padding:30px 20px;background:#0d111d;border-right:1px solid var(--line);display:flex;flex-direction:column;z-index:30}.sidebar .brand{padding:0 8px;margin-bottom:46px}.nav-label{color:#64708d;font-size:10px;font-weight:700;letter-spacing:2px;margin:0 14px 14px}.nav{display:flex;flex-direction:column;gap:6px}.nav a,.nav button{display:flex;gap:12px;align-items:center;color:var(--muted);padding:13px 14px;border:1px solid transparent;border-radius:11px;font-size:13px;font-weight:600;background:none;text-align:left}.nav a:hover,.nav button:hover{background:#ffffff06;color:var(--text)}.nav a.active{background:linear-gradient(90deg,#8b5cf625,#8b5cf60d);border-color:#916bf538;color:#bda4ff}.icon{width:19px;height:19px;flex-shrink:0;display:inline-block;vertical-align:middle}.side-foot{margin-top:auto;border-top:1px solid var(--line);padding:20px 8px 0}.secure{display:flex;gap:9px;font-size:11px;color:var(--muted);align-items:center}.dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 10px #63dec044;display:inline-block}.main{margin-left:250px}.topbar{position:sticky;top:0;z-index:20;height:82px;padding:0 36px;display:flex;align-items:center;justify-content:space-between;background:#090c15e8;backdrop-filter:blur(18px);border-bottom:1px solid var(--line);gap:12px}.breadcrumb{font-size:12px;color:var(--muted)}.breadcrumb b{color:#d9def0;font-weight:500}.top-actions{display:flex;gap:16px;align-items:center}.pill{background:#161d2a;border:1px solid var(--line);border-radius:30px;padding:8px 12px;color:var(--muted);font-size:11px;display:flex;align-items:center;gap:7px}.avatar{width:35px;height:35px;display:grid;place-items:center;background:#8b5cf622;color:#bda4ff;border:1px solid #8b5cf644;border-radius:11px;font-weight:700}.content{padding:32px 36px 20px;max-width:1640px;margin:auto}.page-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:26px}.page-heading p{margin:0;font-size:13px;color:var(--muted)}.btn{display:inline-flex;justify-content:center;align-items:center;gap:9px;border:1px solid var(--line);border-radius:10px;background:var(--panel2);color:var(--text);padding:11px 16px;font-weight:650;font-size:12px;transition:transform .16s,background .16s;line-height:1.4}.btn:hover{background:#242a40;transform:translateY(-1px);color:white}.btn.primary{background:linear-gradient(110deg,#986bff,#7350d8);border-color:#a283ff66;box-shadow:0 5px 20px #7042d525}.btn.primary:hover{background:linear-gradient(110deg,#aa88ff,#8963ee)}.btn.danger{color:var(--red);border-color:#ff8f9c33;background:#ff8f9c0b}.btn.success{color:var(--green);border-color:#63dec033}.btn.sm{padding:7px 10px;font-size:11px;white-space:nowrap}.btn.full{width:100%;padding:14px}.btn.ghost{background:transparent}.hero{border:1px solid #8f6ae53b;border-radius:var(--radius);padding:30px;background:radial-gradient(ellipse at 90% 80%,#663ab52b,transparent 65%),linear-gradient(110deg,#1b1730,#111827);position:relative;overflow:hidden;margin-bottom:24px;display:flex;align-items:center;justify-content:space-between;gap:20px}.hero h2{font-size:25px;margin:10px 0;letter-spacing:-.9px}.hero p{font-size:13px;max-width:520px;color:#adb5cb;margin:0}.hero-symbol{font-weight:900;font-size:94px;line-height:1;letter-spacing:-12px;color:#b6a1ff33;transform:skew(-12deg);padding-right:20px;user-select:none}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:24px}.stat{padding:22px;border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(130deg,#171b2a,#111521);position:relative;overflow:hidden}.stat-label{font-size:12px;color:var(--muted);display:flex;align-items:center;justify-content:space-between;gap:10px}.stat-icon{display:grid;place-items:center;width:33px;height:33px;border-radius:10px;background:#9470ff18;color:var(--purple)}.stat-value{font-size:27px;font-weight:750;letter-spacing:-1px;margin:14px 0 8px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.stat-note{font-size:10px;color:var(--muted)}.stat:first-child{border-color:#9672ff50;background:linear-gradient(120deg,#251d3e,#171525)}.grid{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(0,1fr);gap:22px}.grid.equal{grid-template-columns:repeat(2,minmax(0,1fr))}.panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;margin-bottom:22px}.panel.pad{padding:24px}.panel-head{padding:22px 24px;display:flex;justify-content:space-between;align-items:center;gap:12px;border-bottom:1px solid var(--line)}.panel-head h2{margin:0}.panel-head a{font-size:12px}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;text-align:left;font-size:12px}th{font-size:10px;letter-spacing:.7px;text-transform:uppercase;font-weight:650;color:var(--muted);background:#ffffff02;padding:14px 20px;white-space:nowrap}td{padding:17px 20px;border-top:1px solid #252b407a;vertical-align:middle}tr:hover td{background:#ffffff02}td .sub{font-size:10px;color:var(--muted);margin-top:5px;max-width:260px;overflow-wrap:anywhere}.truncate{max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.money{font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:650}.positive{color:var(--green)}.negative{color:var(--red)}.badge{font-size:10px;padding:5px 9px;border-radius:7px;display:inline-flex;white-space:nowrap;background:#a78bfa15;color:#c1a9ff;border:1px solid #a78bfa22}.badge.good{color:var(--green);background:#63dec010;border-color:#63dec025}.badge.bad{color:var(--red);background:#ff8f9c10;border-color:#ff8f9c25}.badge.wait{color:#e3bc6a;background:#e3bc6a10;border-color:#e3bc6a25}.empty{padding:46px 20px;text-align:center;color:var(--muted);font-size:13px}.empty .icon{width:30px;height:30px;color:#76609e;margin-bottom:12px}.empty strong{display:block;color:#c4cbdf;font-size:14px;margin-bottom:7px}.field{margin-bottom:18px}.field label{display:block;font-size:12px;font-weight:600;color:#cbd1e3;margin-bottom:9px}.field input,.field select,.field textarea{width:100%;border:1px solid #30364c;border-radius:10px;padding:12px 13px;color:var(--text);background:#0c101b;transition:border-color .2s;min-width:0;font-size:13px}.field input:focus,.field select:focus,.field textarea:focus{border-color:var(--purple)}.field textarea{resize:vertical;min-height:95px}.field small{display:block;color:var(--muted);line-height:1.6;font-size:11px;margin-top:7px}.fields-row{display:grid;grid-template-columns:1fr 1fr;gap:16px}.note{font-size:12px;color:#b7c1da;background:#8c70ff0b;border:1px solid #8c70ff29;padding:15px 17px;border-radius:11px;line-height:1.75;margin:16px 0;overflow-wrap:anywhere}.note.warning{border-color:#e3bc6a33;background:#e3bc6a08;color:#e3c987}.note.error{border-color:#ff8f9c33;background:#ff8f9c09;color:var(--red)}.note p:last-child{margin:0}.summary-line{display:flex;justify-content:space-between;gap:12px;padding:13px 0;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted)}.summary-line b{color:var(--text);font-weight:600;overflow-wrap:anywhere}.summary-total{display:flex;justify-content:space-between;gap:12px;padding:20px 0;font-size:15px;font-weight:700}.summary-total b{font-size:22px;color:var(--purple)}.service-description{white-space:pre-wrap;line-height:1.7;font-size:12px;color:var(--muted);max-height:200px;overflow:auto;overflow-wrap:anywhere}.filter-bar{display:flex;align-items:end;gap:12px;margin-bottom:20px;flex-wrap:wrap}.filter-bar .field{margin:0;flex:1;min-width:160px}.pagination{display:flex;align-items:center;justify-content:space-between;padding:17px 20px;border-top:1px solid var(--line);font-size:12px;color:var(--muted);gap:10px}.actions{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.activity{padding:0 24px}.activity-item{padding:18px 0;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px}.activity-item:last-child{border:0}.activity-icon{display:grid;place-items:center;background:#63dec012;border-radius:11px;padding:10px;color:var(--green)}.activity-text{flex:1;font-size:12px;min-width:0}.activity-text small{display:block;color:var(--muted);margin-top:5px;font-size:10px}.footer{padding:20px 0;font-size:10px;color:#6e7894;display:flex;align-items:center;justify-content:space-between;border-top:1px solid var(--line);margin-top:18px;gap:12px}.auth-shell{min-height:100vh;display:grid;grid-template-columns:1.05fr 1fr}.auth-art{padding:50px 9%;background:radial-gradient(ellipse at 30% 50%,#7c4bc323,transparent 65%),#0f1221;border-right:1px solid var(--line);display:flex;flex-direction:column;justify-content:space-between;min-height:100vh}.auth-art h1{font-size:clamp(38px,4.8vw,68px);line-height:1.08;letter-spacing:-3px;max-width:560px;margin:30px 0 25px}.gradient-text{color:#af91ff}.auth-art p{max-width:390px;color:var(--muted);font-size:15px}.auth-decoration{border:1px solid #8b5cf633;padding:22px;border-radius:16px;max-width:385px;background:linear-gradient(120deg,#9a70ed11,#0f1925);margin:35px 0}.auth-form-wrap{display:flex;align-items:center;justify-content:center;padding:50px 34px}.auth-form{width:100%;max-width:390px}.auth-form h1{font-size:30px}.auth-form .subtitle{font-size:13px;color:var(--muted);margin-bottom:32px}.auth-footer{font-size:12px;text-align:center;color:var(--muted);margin-top:24px}.auth-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:30px}.auth-top .pill{font-size:10px}.boot{min-height:70vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;color:var(--muted)}.spinner{display:inline-block;width:22px;height:22px;border:2px solid #9170f433;border-top-color:var(--purple);border-radius:50%;animation:spin .8s linear infinite}.loading{padding:65px;display:grid;place-items:center;gap:18px;color:var(--muted);font-size:12px}@keyframes spin{to{transform:rotate(360deg)}}@keyframes enter{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}.page-content{animation:enter .25s ease}.mobile-menu{display:none}.backdrop{display:none}#toasts{position:fixed;right:24px;bottom:24px;z-index:100;display:flex;flex-direction:column;gap:10px;max-width:calc(100vw - 32px)}.toast{background:#20253a;border:1px solid #9976ff55;border-radius:12px;padding:15px 20px;font-size:12px;box-shadow:0 10px 35px #0007;animation:enter .2s ease;max-width:410px;line-height:1.6}.toast.error{border-color:#ff8f9c55}.toast.success{border-color:#63dec055}dialog{color:var(--text);background:var(--panel);border:1px solid #45405e;border-radius:18px;padding:0;max-width:560px;width:calc(100% - 32px);max-height:90vh;box-shadow:0 30px 100px #0008}dialog::backdrop{background:#03050bbb;backdrop-filter:blur(5px)}.modal-body{padding:26px}.modal-body h2{font-size:21px}.modal-body .actions{justify-content:flex-end;margin-top:22px}.break{overflow-wrap:anywhere}.support-orbit{height:95px;width:95px;display:grid;place-items:center;border:1px solid #9976ff55;border-radius:26px;background:#9976ff15;margin:8px auto 28px;color:var(--purple)}.support-orbit .icon{height:42px;width:42px}.center{text-align:center}.code{font-family:ui-monospace,SFMono-Regular,monospace;font-size:11px;overflow-wrap:anywhere}.checkbox{display:flex;align-items:flex-start;gap:10px;font-size:12px;color:var(--muted);line-height:1.7;margin:16px 0}.checkbox input{margin-top:4px;accent-color:var(--purple)}
@media(min-width:1500px){.content{padding-top:40px}.stat{padding:26px}.hero{padding:36px}}
@media(max-width:1150px){.sidebar{width:220px;padding:28px 14px}.main{margin-left:220px}.content{padding:26px 24px}.topbar{padding:0 24px}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.grid{grid-template-columns:minmax(0,1fr)}.hero-symbol{font-size:75px}.stat-value{font-size:27px}}
@media(max-width:760px){.sidebar{transform:translateX(-100%);transition:transform .2s;width:250px}.sidebar.open{transform:translateX(0)}.sidebar.open~.backdrop{display:block;position:fixed;inset:0;background:#0009;z-index:25}.main{margin-left:0}.topbar{height:68px;padding:0 18px}.mobile-menu{display:inline-flex;padding:8px;background:none;border:1px solid var(--line);border-radius:8px;color:white}.breadcrumb{display:none}.top-actions{margin-left:auto;gap:10px}.content{padding:24px 16px}.page-heading{align-items:flex-start}.page-heading h1{font-size:27px}.page-heading p{font-size:12px}.hero{padding:23px}.hero h2{font-size:22px}.hero-symbol{display:none}.cards{gap:10px}.stat{padding:17px 14px;border-radius:13px}.stat-value{font-size:24px}.stat-label{font-size:11px}.stat-icon{width:27px;height:27px}.stat-icon .icon{height:15px;width:15px}.stat-note{font-size:9px}.grid.equal{grid-template-columns:1fr}.panel.pad{padding:20px}.panel-head{padding:18px}.auth-shell{grid-template-columns:1fr}.auth-art{display:none}.auth-form-wrap{padding:30px 22px;min-height:100vh}.auth-form-wrap .brand{display:flex}.fields-row{grid-template-columns:1fr;gap:0}.footer{font-size:9px}.top-actions .pill{font-size:10px;padding:7px 9px}.page-heading>.btn{padding:10px;font-size:11px}.activity{padding:0 18px}.filter-bar .field{min-width:100%}td,th{padding:14px}.pagination{padding:14px;font-size:11px}#toasts{right:16px;bottom:16px}.note{font-size:11px}.summary-total b{font-size:20px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
'''
FILES['public/app.js'] = r'''
'use strict';
const $=(selector,root=document)=>root.querySelector(selector);
const app=$('#app'),dialog=$('#modal');
const isAdmin=location.pathname.startsWith('/admin');
const base=isAdmin?'/api/admin':'/api/user';
const authBase=isAdmin?'/api/admin/auth':'/api/auth';
let csrf='',me=null,publicConfig={},currentPage='',pagination={offset:0},poll=null,navigationId=0;
const paths={dashboard:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',plus:'M12 5v14 M5 12h14',services:'m12 3 9 5-9 5-9-5 9-5z m-9 9 9 5 9-5 m-18 5 9 5 9-5',orders:'M8 3h8l2 3h3v15H3V6h3l2-3z M8 3v5h8V3 M7 12h10 M7 16h7',wallet:'M3 7V5a2 2 0 0 1 2-2h13v4 M3 7h18v14H3V7z M16 12h5v5h-5z',transactions:'M4 7h16 M16 3l4 4-4 4 M20 17H4 M8 13l-4 4 4 4',support:'m3 11 18-8-6 18-4-7-8-3z M11 14l10-11',profile:'M20 21v-2a7 7 0 0 0-14 0v2 M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0',logout:'M9 3H3v18h6 M14 7l5 5-5 5 M7 12h12',arrow:'M5 12h14 M13 6l6 6-6 6',check:'m5 12 4 4L19 6',clock:'M12 8v5l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',shield:'m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3z m-4 9 3 3 5-6',menu:'M4 6h16 M4 12h16 M4 18h16',refresh:'M20 7v5h-5 M4 17v-5h5 M6 7a7 7 0 0 1 12-1l2 3 M4 15l2 3a7 7 0 0 0 12-1',users:'M16 21v-2a5 5 0 0 0-10 0v2 M15 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M18 4a4 4 0 0 1 0 8 M20 21v-3a4 4 0 0 0-2-3',audit:'M5 3h14v18H5z M9 7h6 M9 11h6 M9 15h4'};
const icon=name=>`<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name]||paths.orders}"/></svg>`;
const e=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=paise=>{const n=BigInt(paise||0),negative=n<0n,a=negative?-n:n;return `${negative?'-':''}₹${(a/100n).toLocaleString('en-IN')}.${String(a%100n).padStart(2,'0')}`;};
const date=value=>value?new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}):'—';
const badge=status=>`<span class="badge ${['Approved','Completed','Active'].includes(status)?'good':['Rejected','Canceled','Cancelled','Suspended','Needs review'].includes(status)?'bad':'wait'}">${e(status)}</span>`;
function toast(text,type=''){const el=document.createElement('div');el.className='toast '+type;el.textContent=text;$('#toasts').append(el);setTimeout(()=>el.remove(),6500);}
async function api(path,options={}){
 const headers={...(options.body?{'Content-Type':'application/json'}:{}),...(options.method&&options.method!=='GET'?{'X-CSRF-Token':csrf}:{}),...options.headers};
 let response,data;
 try{response=await fetch(path,{credentials:'same-origin',...options,headers,body:options.body?JSON.stringify(options.body):undefined});data=await response.json();}
 catch{throw new Error('Connection failed. Check your internet connection. Requests with an existing order key are safe to retry.');}
 if(!response.ok){const error=new Error(data.error?.message||'Unable to complete request.');error.status=response.status;error.code=data.error?.code;if(response.status===401&&me){me=null;clearInterval(poll);authView(false);}throw error;}
 if(data.csrfToken)csrf=data.csrfToken;return data;
}
const mutate=(path,body)=>api(path,{method:'POST',body});
const loading=()=>'<div class="loading"><span class="spinner"></span>Loading live account data…</div>';
const empty=(title='Nothing here yet',text='Your activity will appear here as you get started.')=>`<div class="empty">${icon('services')}<strong>${e(title)}</strong>${e(text)}</div>`;
const stat=(label,value,note,ic)=>`<div class="stat"><div class="stat-label">${e(label)}<span class="stat-icon">${icon(ic)}</span></div><div class="stat-value">${e(value)}</div><div class="stat-note">${e(note)}</div></div>`;
const table=(headers,rows)=>rows.length?`<div class="table-wrap"><table><thead><tr>${headers.map(x=>`<th>${e(x)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`:empty();
function pageControls(items,total){return `<div class="pagination"><span>${items.length?`${pagination.offset+1}–${pagination.offset+items.length}`:'0'} ${total===undefined?'records':`of ${e(total)} records`}</span><div class="actions"><button class="btn sm" data-page="prev" ${pagination.offset===0?'disabled':''}>Previous</button><button class="btn sm" data-page="next" ${total!==undefined?pagination.offset+items.length>=total?'disabled':'':items.length<25?'disabled':''}>Next</button></div></div>`;}
function modal(title,html,handler){$('#modal-content').innerHTML=`<div class="modal-body"><h2>${e(title)}</h2><form id="modal-form">${html}<div class="actions"><button type="button" class="btn" id="cancel-modal">Cancel</button><button class="btn primary" type="submit">Confirm</button></div></form></div>`;$('#cancel-modal').onclick=()=>dialog.close();$('#modal-form').onsubmit=async event=>{event.preventDefault();const b=$('button[type=submit]',event.target);b.disabled=true;try{await handler(Object.fromEntries(new FormData(event.target)));dialog.close();toast('Changes saved successfully.','success');await navigate(currentPage,false);}catch(error){toast(error.message,'error');}finally{b.disabled=false;}};dialog.showModal();}
const reasonField=(min=10)=>`<div class="field"><label for="reason">Reason / verification evidence</label><textarea id="reason" name="reason" required minlength="${min}" maxlength="2000" placeholder="Record the verification details and reason for this action."></textarea></div>`;
function authView(register=false){
 clearInterval(poll);
 const owner=isAdmin;
 app.innerHTML=`<div class="auth-shell"><section class="auth-art"><a class="brand" href="/">${logo()}</a><div><span class="eyebrow">A clearer way to manage</span><h1>Your services.<br>Your wallet.<br><span class="gradient-text">One workspace.</span></h1><p>A thoughtfully designed control center for your service orders, payments and account activity.</p><div class="auth-decoration"><div class="secure"><span class="dot"></span> BUILT AROUND YOUR ACCOUNT</div><h3 >Private by design. Clear by default.</h3><p>Individual wallets. Transparent order tracking. Verified deposits.</p></div></div><small class="muted">ZUDO SMM PANEL · Your next chapter starts here.</small></section><section class="auth-form-wrap"><div class="auth-form"><div class="auth-top"><a class="brand" href="/">${logo()}</a><span class="pill">${icon('shield')}${owner?'Owner access':'Secure access'}</span></div><h1>${owner?'Owner sign in':register?'Create your account':'Welcome back.'}</h1><p class="subtitle">${owner?'Restricted workspace for panel management.':register?'Get your own secure service workspace.':'Sign in and pick up where you left off.'}</p><form id="auth-form"><div class="field"><label for="username">Username</label><input id="username" name="username" autocomplete="username" required minlength="3" maxlength="32" pattern="[a-zA-Z0-9_]+" placeholder="${owner?'owner':'Your username'}"></div><div class="field"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="${register?'new-password':'current-password'}" required maxlength="72" placeholder="Enter your password">${register?'<small>12+ characters with uppercase, lowercase, a number and a symbol.</small>':''}</div>${register?'<div class="field"><label for="confirmPassword">Confirm password</label><input id="confirmPassword" name="confirmPassword" type="password" autocomplete="new-password" required maxlength="72"></div>':''}<div id="auth-error" role="alert"></div><button class="btn primary full" type="submit">${register?'Create account':owner?'Open owner workspace':'Sign in to workspace'}${icon('arrow')}</button></form><div class="auth-footer">${owner?'<a href="/">Return to user sign in</a>':register?'Already have an account? <a href="#login" id="auth-toggle">Sign in</a>':'New to ZUDO? <a href="#register" id="auth-toggle">Create an account</a>'}</div><p class="auth-footer">${owner?'':'<a href="/admin">Owner access</a> · '}Need help? <a href="https://t.me/manwithoutego" target="_blank" rel="noopener noreferrer">Telegram support</a></p></div></section></div>`;
 const toggle=$('#auth-toggle');if(toggle)toggle.onclick=event=>{event.preventDefault();authView(!register);};
 $('#auth-form').onsubmit=async event=>{event.preventDefault();const button=$('button[type=submit]',event.target);button.disabled=true;$('#auth-error').innerHTML='';try{await api(authBase+'/csrf');const values=Object.fromEntries(new FormData(event.target));await mutate(authBase+(register?'/register':'/login'),values);me=await api(base+'/me');location.hash='dashboard';shell();await navigate('dashboard');}catch(error){$('#auth-error').innerHTML=`<div class="note error">${e(error.message)}</div>`;}finally{button.disabled=false;}};
}
function logo(){return '<span class="brand-mark">Z</span><span>ZUDO<small>SMM PANEL</small></span>';}
const userNav=[['dashboard','Dashboard','dashboard'],['new-order','New order','plus'],['services','Services','services'],['orders','My orders','orders'],['funds','Add funds','wallet'],['transactions','Transaction history','transactions'],['support','Support','support'],['profile','Profile','profile']];
const adminNav=[['dashboard','Overview','dashboard'],['deposits','Deposit requests','wallet'],['users','User management','users'],['orders','All orders','orders'],['services','Service policies','services'],['transactions','Wallet ledger','transactions'],['audit','Audit log','audit'],['support','Support','support']];
function shell(){app.innerHTML=`<aside class="sidebar"><a class="brand" href="${isAdmin?'/admin':'/'}">${logo()}</a><div class="nav-label">${isAdmin?'OWNER WORKSPACE':'YOUR WORKSPACE'}</div><nav class="nav">${(isAdmin?adminNav:userNav).map(([key,title,ic])=>`<a href="#${key}" data-nav="${key}">${icon(ic)}${e(title)}</a>`).join('')}<button id="logout">${icon('logout')}Sign out</button></nav><div class="side-foot"><div class="secure">${icon('shield')}Private account workspace</div><div class="nav-label" >ZUDO · ${isAdmin?'OWNER':'MEMBER'}</div></div></aside><div class="backdrop" id="backdrop"></div><main class="main"><header class="topbar"><button class="mobile-menu" id="menu" aria-label="Open navigation">${icon('menu')}</button><span class="breadcrumb">Workspace <span class="muted"> / </span><b id="crumb">Dashboard</b></span><div class="top-actions"><span class="pill">${isAdmin?icon('shield')+'Owner workspace':icon('wallet')+`<span id="top-balance">${money(me.available_paise)}</span>`}</span><div class="avatar" title="${e(me.username)}">${e(me.username.charAt(0).toUpperCase())}</div></div></header><div class="content"><div id="page" class="page-content"></div><footer class="footer"><span>© ${new Date().getFullYear()} ZUDO SMM PANEL</span><span>Made for a better workflow · <a href="https://t.me/manwithoutego" target="_blank" rel="noopener noreferrer">Support ↗</a></span></footer></div></main>`;
 $('#menu').onclick=()=>$('.sidebar').classList.toggle('open');$('#backdrop').onclick=()=>$('.sidebar').classList.remove('open');
 $('#logout').onclick=async()=>{try{await mutate(authBase+'/logout',{});me=null;location.hash='';authView(false);}catch(error){toast(error.message,'error');}};
 clearInterval(poll);poll=setInterval(async()=>{if(!me||document.hidden||dialog.open)return;try{const fresh=await api(base+'/me');me=fresh;if(!isAdmin&&$('#top-balance'))$('#top-balance').textContent=money(me.available_paise);if(['dashboard','orders','deposits','transactions'].includes(currentPage)&&!document.activeElement?.closest('form, .filter-bar'))await navigate(currentPage,false,true);}catch(error){if(error.status!==401)console.debug('Background refresh unavailable');}},20000);
}
function heading(title,subtitle,action=''){return `<div class="page-heading"><div><h1>${e(title)}</h1><p>${e(subtitle)}</p></div>${action}</div>`;}
function ordersTable(items,admin=false){return table(admin?['Order / account','Service / target','Quantity / charge','Status','Actions']:['Order','Service','Quantity / charge','Status',''],items.map(o=>`<tr><td><div class="code">${e(o.id.slice(0,8))}</div><div class="sub">${admin?e(o.username)+' · ':''}${e(date(o.created_at))}</div>${admin?`<div class="sub">Provider #${e(o.provider_order_id||'Unconfirmed')}</div>`:''}</td><td><div class="truncate" title="${e(o.service_name)}">${e(o.service_name)}</div><div class="sub truncate" title="${e(o.target_url)}">${e(o.target_url)}</div></td><td><b>${e(o.quantity.toLocaleString())}</b><div class="sub money">${money(o.amount_paise)}</div>${BigInt(o.refunded_paise)>0n?`<div class="sub positive">Refund ${money(o.refunded_paise)}</div>`:''}</td><td>${badge(o.status)}<div class="sub">Remaining: ${e(o.remains??'—')}</div>${o.state==='reconcile'?'<div class="sub">Funds reserved; owner review needed.</div>':''}${o.state==='rejected'?'<div class="sub">No wallet charge.</div>':''}</td><td>${o.provider_order_id?`<button class="btn sm" data-refresh="${e(o.id)}" aria-label="Refresh order ${e(o.id.slice(0,8))}">${icon('refresh')}</button>`:admin&&o.state==='reconcile'?`<button class="btn sm danger" data-reconcile="${e(o.id)}">Resolve</button>`:'—'}</td></tr>`));}
function transactionsTable(items,admin=false){return table(admin?['Account / date','Type','Description','Amount','Balance after']:['Date','Type','Description','Amount','Balance after'],items.map(t=>`<tr><td>${admin?`<b>${e(t.username)}</b><div class="sub">${e(date(t.created_at))}</div>`:e(date(t.created_at))}</td><td>${badge(t.kind)}</td><td><div class="break">${e(t.reason)}</div><div class="sub code">${e(t.reference)}</div></td><td class="money ${BigInt(t.amount_paise)>0n?'positive':'negative'}">${BigInt(t.amount_paise)>0n?'+':''}${money(t.amount_paise)}</td><td class="money">${money(t.balance_after_paise)}</td></tr>`));}
async function dashboard(){
 const data=await api(base+'/dashboard');
 if(isAdmin)return heading('Owner overview','Your panel, at a glance. Live records from PostgreSQL.',`<a class="btn primary" href="#deposits">Review deposits ${icon('arrow')}</a>`)+`<div class="hero"><div><span class="eyebrow">Operations control center</span><h2>Keep every detail in view.</h2><p>Verify payments independently, review service compliance and track every wallet movement from one secure workspace.</p></div><div class="hero-symbol">Z.</div></div><div class="cards">${stat('Registered users',data.users.total,'Individual, persistent accounts','users')}${stat('Total orders',data.orders.total,`${data.orders.review} uncertain orders need reconciliation`,'orders')}${stat('Verified deposits',money(data.deposits.approved_paise),`${data.deposits.approved} approved deposit requests`,'wallet')}${stat('Pending deposits',data.deposits.pending,'Awaiting independent verification','clock')}</div><div class="grid equal"><section class="panel pad"><h2>Deposit health</h2><div class="summary-line">Total requests <b>${data.deposits.total}</b></div><div class="summary-line">Approved <b>${data.deposits.approved}</b></div><div class="summary-line">Rejected <b>${data.deposits.rejected}</b></div><div class="note warning">A UTR is a payment reference, not proof of payment. Only approve after checking your own bank or UPI records.</div><a href="#deposits" class="btn">Manage requests ${icon('arrow')}</a></section><section class="panel pad"><h2>Catalogue & order safety</h2><div class="summary-line">Provider services cached <b>${data.catalogue.total}</b></div><div class="summary-line">Enabled services <b>${data.catalogue.enabled}</b></div><div class="summary-line">Last catalogue refresh <b>${e(date(data.catalogue.synced_at))}</b></div><div class="note">Services stay disabled until you review their platform compliance. Uncertain provider submissions are never retried automatically.</div><div class="actions"><a class="btn" href="#services">Review services</a><a class="btn" href="#orders">Manage orders</a></div></section></div>`;
 me=data.user;if($('#top-balance'))$('#top-balance').textContent=money(me.available_paise);
 return heading(`Welcome back, ${me.username}.`,'Here’s what’s happening in your workspace.',`<a class="btn primary" href="#new-order">${icon('plus')}New order</a>`)+`<div class="hero"><div><span class="eyebrow">Your workspace. Simplified.</span><h2>Everything in the right place.</h2><p>Explore approved services, follow your orders and manage funds—with full visibility into every transaction.</p></div><div class="hero-symbol">Z.</div></div><div class="cards">${stat('Available balance',money(me.available_paise),`${money(me.held_paise)} reserved for unconfirmed orders`,'wallet')}${stat('Total orders',data.stats.total,'All your service requests','orders')}${stat('Pending orders',data.stats.pending,'Queued, processing or under review','clock')}${stat('Completed orders',data.stats.completed,'Fulfilled by your provider','check')}</div><div class="grid"><section class="panel"><div class="panel-head"><h2>Recent orders</h2><a href="#orders">View all ↗</a></div>${ordersTable(data.recentOrders)}</section><section class="panel"><div class="panel-head"><h2>Wallet activity</h2><a href="#transactions">View all ↗</a></div>${data.transactions.length?`<div class="activity">${data.transactions.map(t=>`<div class="activity-item"><span class="activity-icon">${icon(BigInt(t.amount_paise)>0n?'plus':'orders')}</span><div class="activity-text">${e(t.kind.charAt(0).toUpperCase()+t.kind.slice(1))}<small>${e(date(t.created_at))}</small></div><span class="money ${BigInt(t.amount_paise)>0n?'positive':'muted'}">${BigInt(t.amount_paise)>0n?'+':''}${money(t.amount_paise)}</span></div>`).join('')}</div>`:empty('Your wallet is ready','Add funds to start your first order.')}</section></div><div class="note">${icon('shield')} Wallet deposits are manually verified. Your balance is credited only after payment approval. <a href="#funds">Add funds →</a></div>`;
}
async function servicesPage(){const d=await api(base+'/services?'+new URLSearchParams({limit:25,offset:pagination.offset,q:pagination.q||'',category:pagination.category||''}));return heading(isAdmin?'Service policies':'Service catalogue',isAdmin?'Review the complete provider catalogue before enabling compliant services.':'Browse every active, owner-approved service.',isAdmin?'<button class="btn primary" id="sync-services">'+icon('refresh')+'Sync provider</button>':'')+`<form id="service-filter" class="filter-bar"><div class="field"><label for="search">Search services</label><input id="search" name="q" placeholder="Service name or ID" value="${e(pagination.q||'')}"></div><div class="field"><label for="category">Category</label><select id="category" name="category"><option value="">All categories</option>${d.categories.map(c=>`<option ${c===pagination.category?'selected':''}>${e(c)}</option>`).join('')}</select></div><button class="btn" type="submit">Search</button></form>${isAdmin?'<div class="note warning">All services are disabled by default. Enable only legitimate, platform-permitted marketing services after independent review. Default-type orders are supported; incompatible types cannot be enabled.</div>':''}<section class="panel">${table(['ID / category','Service','Rate / 1,000','Min / max',isAdmin?'Policy':''],d.items.map(s=>`<tr><td><b>#${e(s.provider_service_id)}</b><div class="sub">${e(s.category)}</div></td><td><div class="break">${e(s.name)}</div><div class="sub">${e(s.type)}${s.description?' · Description available':''}</div></td><td class="money">${money((BigInt(s.retail_rate_micro)+9999n)/10000n)}<div class="sub">INR / 1,000 units</div></td><td>${s.min_quantity.toLocaleString()}<div class="sub">to ${s.max_quantity.toLocaleString()}</div></td><td>${isAdmin?`${badge(s.enabled&&s.active?'Active':'Disabled')}<div class="actions"><button class="btn sm" data-policy="${e(s.provider_service_id)}" data-enabled="${s.enabled}">${s.enabled?'Disable':'Review & enable'}</button></div>`:`<button class="btn sm" data-order-service="${e(s.provider_service_id)}">Select ${icon('arrow')}</button>`}</td></tr>`))}${pageControls(d.items,d.total)}</section>`;}
async function newOrderPage(){return heading('Create a new order','Choose a service. Check the details. Confirm with confidence.')+`<div class="grid"><section class="panel pad"><h2>Order details</h2><form id="order-form"><div class="fields-row"><div class="field"><label for="order-category">Category</label><select id="order-category"><option value="">All categories</option></select></div><div class="field"><label for="order-search">Find service</label><input id="order-search" placeholder="Name or service ID"></div></div><div class="actions"><button type="button" class="btn sm" id="order-find">Find services</button><button type="button" class="btn sm" id="order-prev">Previous</button><button type="button" class="btn sm" id="order-next">Next</button><small id="order-service-count" class="muted"></small></div><div class="field"><label for="order-service">Service</label><select id="order-service" name="serviceId" required><option value="">Loading services…</option></select></div><div class="note"><strong>Service details</strong><div class="service-description" id="service-description">Select a service to see its details.</div></div><div class="field"><label for="target">Target URL</label><input id="target" name="target" type="url" pattern="https://.*" maxlength="2048" placeholder="https://your-public-page.example/post" required><small>Use a public HTTPS URL. Only submit targets you own or are authorized to manage.</small></div><div class="field"><label for="quantity">Quantity</label><input id="quantity" name="quantity" type="number" min="1" step="1" required placeholder="Enter quantity"><small id="quantity-range">Choose a service to view the quantity range.</small></div><label class="checkbox"><input type="checkbox" required><span>I have permission to manage this target, and this order complies with the destination platform’s rules.</span></label><div id="order-error" role="alert"></div><button type="submit" class="btn primary full">Submit order ${icon('arrow')}</button></form></section><aside><section class="panel pad"><span class="eyebrow">Before you confirm</span><h2>Order summary</h2><div class="summary-line">Available balance <b id="available">${money(me.available_paise)}</b></div><div class="summary-line">Rate per 1,000 <b id="order-rate">—</b></div><div class="summary-line">Quantity <b id="summary-quantity">—</b></div><div class="summary-total">Estimated total <b id="order-total">₹0.00</b></div><a href="#funds" class="btn full">${icon('wallet')}Add funds</a></section><div class="note">The final price is verified on the server. Funds are reserved while the provider processes your request and charged only after provider acceptance.</div><div class="note warning">Do not create a second order while the first is awaiting review. A provider timeout may require owner reconciliation.</div></aside></div>`;}
async function fundsPage(){const d=await api(base+'/deposits?limit=25&offset='+pagination.offset);return heading('Add funds','Simple UPI payments. Independently verified. Credited once.')+`<div class="grid"><section class="panel pad"><h2>Submit a deposit request</h2><div class="note"><span class="eyebrow">Pay using your UPI app</span><p class="break"><strong id="upi-text">${e(publicConfig.upiId)}</strong></p><div class="actions"><button class="btn sm" type="button" id="copy-upi">Copy UPI ID</button><a class="btn sm" id="upi-pay" href="upi://pay?pa=${encodeURIComponent(publicConfig.upiId)}&pn=ZUDO%20SMM%20PANEL&cu=INR">Open UPI app ↗</a></div></div><form id="deposit-form"><div class="field"><label for="amount">Amount paid (INR)</label><input id="amount" name="amount" type="number" min="1" max="1000000" step=".01" required placeholder="500.00"></div><div class="field"><label for="utr">UTR / transaction reference</label><input id="utr" name="utr" required minlength="8" maxlength="64" pattern="[A-Za-z0-9]+" placeholder="Reference from your payment receipt"><small>Submit the exact reference. The same UTR cannot be used twice.</small></div><label class="checkbox"><input type="checkbox" required><span>I have already made this payment and entered its actual reference.</span></label><button class="btn primary full" type="submit">Submit for verification ${icon('arrow')}</button></form></section><section class="panel pad"><span class="eyebrow">How it works</span><h2>Your payment, clearly tracked.</h2><div class="summary-line">01 <b>Pay the UPI ID shown here</b></div><div class="summary-line">02 <b>Enter amount and UTR</b></div><div class="summary-line">03 <b>Wait for independent verification</b></div><div class="summary-line">04 <b>Approved amount enters your wallet</b></div><div class="note warning">Submitting a UTR does not prove payment. Pending requests do not change your balance. Do not pay again just because verification is pending.</div><a class="btn" href="https://t.me/manwithoutego" target="_blank" rel="noopener noreferrer">${icon('support')}Payment support</a></section></div><section class="panel"><div class="panel-head"><h2>Your deposit requests</h2></div>${depositTable(d.items)}${pageControls(d.items)}</section>`;}
function depositTable(items,admin=false){return table(admin?['Account','Amount','Payment reference','Submitted','Status / action']:['Amount','Payment reference','Submitted','Status / reason'],items.map(d=>`<tr>${admin?`<td><b>${e(d.username)}</b></td>`:''}<td class="money">${money(d.amount_paise)}</td><td class="code">${e(d.utr)}</td><td>${e(date(d.created_at))}</td><td>${badge(d.status)}${d.reason?`<div class="sub">${e(d.reason)}</div>`:''}${admin&&d.status==='Pending'?`<div class="actions"><button class="btn sm success" data-review="${e(d.id)}" data-decision="Approved">Approve</button><button class="btn sm danger" data-review="${e(d.id)}" data-decision="Rejected">Reject</button></div>`:''}</td></tr>`));}
async function adminDeposits(){const d=await api(base+'/deposits?'+new URLSearchParams({limit:25,offset:pagination.offset,status:pagination.status||''}));return heading('Deposit requests','Confirm incoming payments against your own bank or UPI statement.')+`<form class="filter-bar" id="deposit-filter"><div class="field"><label for="status">Status</label><select id="status" name="status"><option value="">All requests</option>${['Pending','Approved','Rejected'].map(s=>`<option ${pagination.status===s?'selected':''}>${s}</option>`).join('')}</select></div><button class="btn">Filter</button></form><div class="note warning">Check the actual received amount, reference and recipient account before approving. Approvals credit the wallet atomically and cannot be reversed by changing deposit status.</div><section class="panel">${depositTable(d.items,true)}${pageControls(d.items)}</section>`;}
async function usersPage(){const d=await api(base+'/users?'+new URLSearchParams({limit:25,offset:pagination.offset,q:pagination.q||''}));return heading('User management','Account access, reserved funds and a complete wallet trail.')+`<form id="user-filter" class="filter-bar"><div class="field"><label for="user-search">Search usernames</label><input id="user-search" name="q" value="${e(pagination.q||'')}" placeholder="Username"></div><button class="btn">Search</button></form><section class="panel">${table(['Account','Wallet balance','Reserved','Access','Actions'],d.items.map(u=>`<tr><td><b>${e(u.username)}</b><div class="sub">Joined ${e(date(u.created_at))}</div></td><td class="money">${money(u.balance_paise)}</td><td class="money">${money(u.held_paise)}</td><td>${badge(u.suspended?'Suspended':'Active')}</td><td><div class="actions"><button class="btn sm" data-user-details="${e(u.id)}">History</button><button class="btn sm" data-wallet="${e(u.id)}">Adjust wallet</button><button class="btn sm ${u.suspended?'':'danger'}" data-suspend="${e(u.id)}" data-suspended="${u.suspended}">${u.suspended?'Restore':'Suspend'}</button></div></td></tr>`))}${pageControls(d.items)}</section>`;}
async function profilePage(){return heading('Your profile','Your account details and sign-in security.')+`<div class="grid equal"><section class="panel pad"><h2>Account details</h2><div class="summary-line">Username <b>${e(me.username)}</b></div><div class="summary-line">Account ID <b>#${e(me.id)}</b></div><div class="summary-line">Joined <b>${e(date(me.created_at))}</b></div><div class="summary-line">Available balance <b>${money(me.available_paise)}</b></div><div class="summary-line">Reserved funds <b>${money(me.held_paise)}</b></div><div class="note">Passwords are securely hashed. Support will never ask you for your password or payment app PIN. Password recovery is handled manually through verified support; do not share account credentials.</div></section><section class="panel pad"><h2>Change password</h2><form id="password-form"><div class="field"><label for="currentPassword">Current password</label><input id="currentPassword" type="password" name="currentPassword" autocomplete="current-password" required></div><div class="field"><label for="newPassword">New password</label><input id="newPassword" type="password" name="newPassword" autocomplete="new-password" minlength="12" maxlength="72" required><small>12+ characters: uppercase, lowercase, digit and symbol.</small></div><div class="field"><label for="confirmPassword">Confirm new password</label><input id="confirmPassword" type="password" name="confirmPassword" autocomplete="new-password" required maxlength="72"></div><button class="btn primary full">Update password</button></form></section></div>`;}
function supportPage(){return heading('A little help, when you need it.','Reach the panel team directly through Telegram.')+`<div class="grid equal"><section class="panel pad center"><div class="support-orbit">${icon('support')}</div><span class="eyebrow">Talk to a real person</span><h2>Telegram support</h2><p class="muted">Share your order ID or deposit reference and describe the issue. Never send passwords, OTPs or UPI PINs.</p><a class="btn primary" href="https://t.me/manwithoutego" target="_blank" rel="noopener noreferrer">Message @manwithoutego ${icon('arrow')}</a></section><section class="panel pad"><h2>Before you reach out</h2><div class="note"><strong>Payment still pending?</strong><p>Verification is manual. Keep your receipt and UTR available. A UTR alone is not payment confirmation.</p></div><div class="note"><strong>Order awaiting review?</strong><p>The provider response may be uncertain. Do not place the same order again; ask support to reconcile it.</p></div><div class="note"><strong>Need an order update?</strong><p>Use the refresh button in your orders. The panel also polls supported provider statuses in the background.</p></div></section></div>`;}
async function navigate(page,reset=true,silent=false){
 if(!me)return;
 if(!(isAdmin?adminNav:userNav).some(n=>n[0]===page))page='dashboard';
 if(reset||currentPage!==page)pagination={offset:0};currentPage=page;
 const navId=++navigationId;$('.sidebar')?.classList.remove('open');document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('active',a.dataset.nav===page));$('#crumb').textContent=(isAdmin?adminNav:userNav).find(n=>n[0]===page)[1];
 if(!silent)$('#page').innerHTML=loading();
 try{let html;
  if(page==='dashboard')html=await dashboard();
  else if(page==='services')html=await servicesPage();
  else if(page==='new-order')html=await newOrderPage();
  else if(page==='funds')html=await fundsPage();
  else if(page==='support')html=supportPage();
  else if(page==='profile')html=await profilePage();
  else if(page==='users')html=await usersPage();
  else if(page==='deposits')html=await adminDeposits();
  else if(page==='orders'){const d=await api(base+'/orders?limit=25&offset='+pagination.offset);html=heading(isAdmin?'All orders':'My orders','Track provider updates and see the details behind every request.')+`<section class="panel">${ordersTable(d.items,isAdmin)}${pageControls(d.items)}</section>`;}
  else if(page==='transactions'){const d=await api(base+'/transactions?limit=25&offset='+pagination.offset);html=heading(isAdmin?'Wallet ledger':'Transaction history','A permanent record of every credit, charge and refund.')+`<section class="panel">${transactionsTable(d.items,isAdmin)}${pageControls(d.items)}</section>`;}
  else if(page==='audit'){const d=await api(base+'/audit?limit=25&offset='+pagination.offset);html=heading('Owner audit trail','Every administrative change, with its reason and timestamp.')+`<section class="panel">${table(['Time / actor','Action','Subject','Details'],d.items.map(a=>`<tr><td>${e(date(a.created_at))}<div class="sub">${e(a.actor)}</div></td><td>${e(a.action)}</td><td class="code">${e(a.subject)}</td><td class="break">${e(JSON.stringify(a.details))}</td></tr>`))}${pageControls(d.items)}</section>`;}
  if(navId!==navigationId||!me)return;$('#page').innerHTML=html;bindPage();if(page==='new-order')await bindOrder();
 }catch(error){if(navId!==navigationId||!me)return;if(!silent){$('#page').innerHTML=heading('Unable to load this page','Your account data has not been changed.')+`<div class="note error">${e(error.message)}</div><button class="btn" id="retry-page">Try again</button>`;$('#retry-page').onclick=()=>navigate(page,false);} }
}
function bindPage(){
 document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{pagination.offset=Math.max(0,pagination.offset+(b.dataset.page==='next'?25:-25));navigate(currentPage,false);});
 for(const [id,keys] of [['service-filter',['q','category']],['user-filter',['q']],['deposit-filter',['status']]]){const f=$('#'+id);if(f)f.onsubmit=event=>{event.preventDefault();const d=Object.fromEntries(new FormData(f));for(const k of keys)pagination[k]=d[k];pagination.offset=0;navigate(currentPage,false);};}
 document.querySelectorAll('[data-order-service]').forEach(b=>b.onclick=()=>{sessionStorage.setItem('zudo-selected-service',b.dataset.orderService);if(location.hash==='#new-order')navigate('new-order');else location.hash='new-order';});
 document.querySelectorAll('[data-refresh]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await mutate(base+'/orders/'+b.dataset.refresh+'/refresh',{});toast('Provider status checked.','success');await navigate(currentPage,false);}catch(error){toast(error.message,'error');b.disabled=false;}});
 if($('#sync-services'))$('#sync-services').onclick=async event=>{event.target.disabled=true;try{const d=await mutate(base+'/services/sync',{});toast(`${d.count} provider services synchronized. Review policies before enabling.`,'success');await navigate('services',false);}catch(error){toast(error.message,'error');event.target.disabled=false;}};
 document.querySelectorAll('[data-policy]').forEach(b=>b.onclick=()=>{const enabled=b.dataset.enabled!=='true';modal(enabled?'Review & enable service':'Disable service',`<div class="note warning">${enabled?'Confirm this service and its intended use comply with the destination platform’s rules and the provider’s requirements. No fake engagement, impersonation, spam or deceptive activity.':'Disabling stops new orders. Existing confirmed provider orders are not canceled.'}</div>${reasonField(20)}`,d=>mutate(base+'/services/'+b.dataset.policy+'/policy',{enabled,reason:d.reason}));});
 document.querySelectorAll('[data-review]').forEach(b=>b.onclick=()=>modal(b.dataset.decision==='Approved'?'Verify and approve deposit':'Reject deposit',`${b.dataset.decision==='Approved'?'<div class="note warning">Approval credits the wallet. Match the actual received amount and UTR in your own bank or UPI account before continuing.</div><label class="checkbox"><input type="checkbox" name="verified" required><span>I independently verified this exact payment in my bank / UPI statement.</span></label>':''}${reasonField()}`,d=>mutate(base+'/deposits/'+b.dataset.review+'/review',{decision:b.dataset.decision,reason:d.reason,verified:d.verified==='on'})));
 document.querySelectorAll('[data-suspend]').forEach(b=>b.onclick=()=>modal(b.dataset.suspended==='true'?'Restore account access':'Suspend account',`${reasonField()}<div class="note">Existing user sessions will be invalidated. Queued orders from suspended accounts will not be sent to the provider.</div>`,d=>mutate(base+'/users/'+b.dataset.suspend+'/suspend',{suspended:b.dataset.suspended!=='true',reason:d.reason})));
 document.querySelectorAll('[data-wallet]').forEach(b=>b.onclick=()=>{const key=crypto.randomUUID();modal('Manual wallet adjustment',`<div class="fields-row"><div class="field"><label for="direction">Action</label><select name="direction" id="direction"><option value="credit">Credit</option><option value="debit">Debit</option></select></div><div class="field"><label for="adjustment">Amount (INR)</label><input id="adjustment" name="amount" type="number" min=".01" max="1000000" step=".01" required></div></div>${reasonField()}`,d=>mutate(base+'/users/'+b.dataset.wallet+'/wallet',{...d,idempotencyKey:key}));});
 document.querySelectorAll('[data-reconcile]').forEach(b=>b.onclick=()=>modal('Resolve uncertain provider submission',`<div class="note warning">Check the provider panel or contact provider support. Their API does not expose client idempotency keys. Verify target, service and quantity manually. Never guess the provider order ID.</div><div class="field"><label for="providerId">Verified provider order ID</label><input id="providerId" name="providerId" pattern="[0-9]+" placeholder="Leave empty ONLY if no order exists"><small>A blank ID releases the reservation without a charge. An ID confirms the order and charges the reserved amount.</small></div>${reasonField(20)}<label class="checkbox"><input type="checkbox" name="verified" required><span>I independently verified the outcome with the provider and documented my evidence.</span></label>`,d=>mutate(base+'/orders/'+b.dataset.reconcile+'/reconcile',{providerId:d.providerId.trim()||null,reason:d.reason,verified:true})));
 document.querySelectorAll('[data-user-details]').forEach(b=>b.onclick=async()=>{try{await showUserHistory(b.dataset.userDetails,0);}catch(error){toast(error.message,'error');}});
 if($('#copy-upi'))$('#copy-upi').onclick=async()=>{try{await navigator.clipboard.writeText(publicConfig.upiId);toast('UPI ID copied.','success');}catch{toast('Copy the UPI ID shown above.');}};
 if($('#deposit-form'))$('#deposit-form').onsubmit=async event=>{event.preventDefault();const form=event.target,button=$('button[type=submit]',form);button.disabled=true;try{await mutate(base+'/deposits',Object.fromEntries(new FormData(form)));toast('Request submitted. Wallet credit follows independent approval.','success');await navigate('funds');}catch(error){toast(error.message,'error');button.disabled=false;}};
 if($('#password-form'))$('#password-form').onsubmit=async event=>{event.preventDefault();const b=$('button',event.target);b.disabled=true;try{await mutate(base+'/password',Object.fromEntries(new FormData(event.target)));toast('Password updated. Other sessions have been invalidated.','success');event.target.reset();}catch(error){toast(error.message,'error');}finally{b.disabled=false;}};
}
async function showUserHistory(id,offset){const d=await api(base+'/users/'+id+'?limit=25&offset='+offset);$('#modal-content').innerHTML=`<div class="modal-body"><h2>${e(d.user.username)} · Account history</h2><div class="note">Balance ${money(d.user.balance_paise)} · Reserved ${money(d.user.held_paise)}</div><h3>Orders</h3>${ordersTable(d.orders)}<h3>Transactions</h3>${transactionsTable(d.transactions)}<div class="actions"><button class="btn sm" id="history-prev" ${offset?'':'disabled'}>Previous</button><button class="btn sm" id="history-next" ${d.orders.length===25||d.transactions.length===25?'':'disabled'}>Next</button><button class="btn" id="history-close">Close</button></div></div>`;if(!dialog.open)dialog.showModal();document.querySelectorAll('#modal-content [data-refresh]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{await mutate(base+'/orders/'+button.dataset.refresh+'/refresh',{});await showUserHistory(id,offset);}catch(error){toast(error.message,'error');button.disabled=false;}});$('#history-close').onclick=()=>dialog.close();$('#history-prev').onclick=()=>showUserHistory(id,Math.max(0,offset-25)).catch(x=>toast(x.message,'error'));$('#history-next').onclick=()=>showUserHistory(id,offset+25).catch(x=>toast(x.message,'error'));}
async function bindOrder(){
 let items=[],selected=null,serviceOffset=0,serviceTotal=0;
 let selectedId=sessionStorage.getItem('zudo-selected-service')||'';sessionStorage.removeItem('zudo-selected-service');
 async function find(){
  const d=await api(base+'/services?'+new URLSearchParams({limit:100,offset:serviceOffset,q:selectedId||$('#order-search').value,category:$('#order-category').value}));items=d.items;serviceTotal=d.total;
  if($('#order-category').options.length===1){$('#order-category').innerHTML='<option value="">All categories</option>'+d.categories.map(c=>`<option>${e(c)}</option>`).join('');}
  $('#order-service').innerHTML='<option value="">Choose a service</option>'+items.map(s=>`<option value="${e(s.provider_service_id)}">#${e(s.provider_service_id)} · ${e(s.name)}</option>`).join('');
  if(selectedId){$('#order-service').value=selectedId;$('#order-search').value=selectedId;selectedId='';}else if(items.length===1)$('#order-service').value=items[0].provider_service_id;
  $('#order-service-count').textContent=`${d.total} matching services`;
  $('#order-prev').disabled=serviceOffset===0;$('#order-next').disabled=serviceOffset+100>=serviceTotal;select();
 }
 function estimate(){const q=$('#quantity').value;const amount=selected&&/^\d+$/.test(q)?(BigInt(selected.retail_rate_micro)*BigInt(q)+9999999n)/10000000n:0n;$('#order-total').textContent=money(amount);$('#summary-quantity').textContent=q||'—';return amount;}
 function select(){selected=items.find(s=>s.provider_service_id===$('#order-service').value)||null;$('#service-description').textContent=selected?(selected.description||'The provider does not supply a description for this service. Review the service name, category and limits; contact support if the scope is unclear.'):'Select an approved service. If none appear, contact support.';$('#order-rate').textContent=selected?money((BigInt(selected.retail_rate_micro)+9999n)/10000n):'—';$('#quantity-range').textContent=selected?`Minimum ${selected.min_quantity.toLocaleString()} · Maximum ${selected.max_quantity.toLocaleString()}`:'Choose a service to view quantity limits.';if(selected){$('#quantity').min=selected.min_quantity;$('#quantity').max=selected.max_quantity;}estimate();}
 $('#order-service').onchange=select;$('#quantity').oninput=estimate;
 const load=async()=>{try{await find();}catch(error){toast(error.message,'error');}};
 $('#order-find').onclick=()=>{serviceOffset=0;load();};$('#order-search').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();serviceOffset=0;load();}};$('#order-category').onchange=()=>{serviceOffset=0;load();};$('#order-prev').onclick=()=>{serviceOffset=Math.max(0,serviceOffset-100);load();};$('#order-next').onclick=()=>{serviceOffset+=100;load();};
 $('#order-form').onsubmit=async event=>{
  event.preventDefault();if(!selected){toast('Choose an available service.','error');return;}
  const form=event.target,button=$('button[type=submit]',form);button.disabled=true;$('#order-error').innerHTML='';
  const data={serviceId:selected.provider_service_id,target:$('#target').value.trim(),quantity:Number($('#quantity').value),quotePaise:String(estimate())};
  const fingerprint=JSON.stringify([data.serviceId,data.target,data.quantity]);let saved;try{saved=JSON.parse(sessionStorage.getItem('zudo-order-attempt'));}catch{}
  const idempotencyKey=saved?.fingerprint===fingerprint?saved.key:crypto.randomUUID();sessionStorage.setItem('zudo-order-attempt',JSON.stringify({fingerprint,key:idempotencyKey}));
  try{await mutate(base+'/orders',{...data,idempotencyKey});toast('Order queued. Funds reserved pending provider confirmation.','success');location.hash='orders';sessionStorage.removeItem('zudo-order-attempt');}
  catch(error){$('#order-error').innerHTML=`<div class="note error">${e(error.message)}</div>`;button.disabled=false;}
 };
 await find();
}
window.addEventListener('hashchange',()=>{if(me)navigate(location.hash.slice(1)||'dashboard');});
(async()=>{try{publicConfig=await api('/api/public/config');await api(authBase+'/csrf');try{me=await api(base+'/me');}catch(error){if(error.status!==401)throw error;}if(me){shell();await navigate(location.hash.slice(1)||'dashboard');}else authView(!isAdmin&&(location.pathname==='/register'||location.hash==='#register'));}catch(error){app.innerHTML=`<div class="boot"><span class="brand-mark">Z</span><p>${e(error.message)}</p><button class="btn" id="retry-start">Reload workspace</button></div>`;$('#retry-start').onclick=()=>location.reload();}})();
'''
FILES['test/integration.test.js'] = r'''
// Test doubles are injected ONLY here. Production always uses the real provider adapter.
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const request=require('supertest');
const {randomUUID}=require('node:crypto');
const {createDb}=require('../src/db');
const {loadConfig}=require('../src/config');
const {createApp}=require('../src/app');
const {createProvider}=require('../src/provider');
const {startWorker}=require('../src/worker');
let db,app,domain,alice,bob,owner,at,bt,ot,aliceId,acceptedId,depositId;
let behavior='success',addCalls=0;
const statuses=new Map();
const stub={
 balance:async()=>({balance:'1000',currency:'USD'}),
 services:async()=>[{service:9201,name:'Authorized campaign setup',type:'Default',category:'Permitted marketing',description:'Owner-authorized campaign setup.',rate:'1.00',min:'10',max:'1000'},{service:9202,name:'Custom workflow',type:'Custom Comments',category:'Other',rate:'2',min:'1',max:'100'},{service:9203,name:'High precision import regression',type:'Default',category:'Other',rate:'0.17675482700577',min:'1',max:'2147483647'},{service:9204,name:'Unusually high provider rate regression',type:'Default',category:'Other',rate:'19160635441893',min:'1',max:'100000'}],
 add:async()=>{addCalls++;if(behavior==='reject'){const e=new Error('rejected');e.kind='rejected';throw e;}if(behavior==='timeout')throw new Error('timeout');return {order:5000+addCalls};},
 status:async id=>statuses.get(String(id))||{status:'In progress',remains:'10',start_count:'0',charge:'0.1',currency:'USD'}
};
const origin='http://localhost:3000';
function post(agent,url,token,body){return agent.post(url).set('Origin',origin).set('X-CSRF-Token',token).send(body);}
const userPost=(path,body)=>post(alice,'/api/user'+path,at,body);
const adminPost=(path,body)=>post(owner,'/api/admin'+path,ot,body);
async function freshOrder(extra={}){return userPost('/orders',{serviceId:'9201',target:'https://example.com/authorized',quantity:10,quotePaise:'100',idempotencyKey:randomUUID(),...extra});}
before(async()=>{
 if(!process.env.TEST_DATABASE_URL)throw new Error('Set TEST_DATABASE_URL to a dedicated, disposable PostgreSQL database. Tests delete its panel data.');
 const c=loadConfig({...process.env,NODE_ENV:'test',DATABASE_URL:process.env.TEST_DATABASE_URL,DATABASE_SSL:'disable',SESSION_SECRET:'test-only-secret-which-is-more-than-32-characters',OWNER_USERNAME:'owner',OWNER_PASSWORD:'LocalTest!OwnerPass32',PROVIDER_CURRENCY:'USD',PROVIDER_TO_INR:'100',MARKUP_PERCENT:'0',APP_ORIGIN:origin});
 db=createDb(c);await db.migrate();await db.migrate();
 await db.pool.query('TRUNCATE admin_logs,transactions,deposits,orders,services_cache,users,sessions,request_limits RESTART IDENTITY CASCADE');
 ({app,domain}=await createApp(c,db,stub));alice=request.agent(app);bob=request.agent(app);owner=request.agent(app);
 at=(await alice.get('/api/auth/csrf')).body.csrfToken;bt=(await bob.get('/api/auth/csrf')).body.csrfToken;ot=(await owner.get('/api/admin/auth/csrf')).body.csrfToken;
});
after(async()=>{if(db)await db.pool.end();});
test('configuration rejects weak owner password and missing FX',()=>{
 assert.throws(()=>loadConfig({DATABASE_URL:'postgres://test',SESSION_SECRET:'a'.repeat(32),OWNER_PASSWORD:'8318',PROVIDER_TO_INR:'100'}),/OWNER_PASSWORD/);
 assert.throws(()=>loadConfig({DATABASE_URL:'postgres://test',SESSION_SECRET:'a'.repeat(32),OWNER_PASSWORD:'StrongOwner!123',PROVIDER_CURRENCY:'USD'}),/PROVIDER_TO_INR/);
});
test('health check, CSRF and owner authorization',async()=>{
 assert.equal((await request(app).get('/healthz')).status,200);
 assert.equal((await request(app).get('/api/user/me')).status,401);
 assert.equal((await request(app).get('/api/admin/dashboard')).status,401);
 assert.equal((await alice.post('/api/auth/register').send({})).status,403);
 assert.equal((await alice.post('/api/auth/register').set('Origin','https://evil.example').set('X-CSRF-Token',at).send({})).status,403);
});
test('register users, hash passwords, enforce username uniqueness and password rules',async()=>{
 const a=await post(alice,'/api/auth/register',at,{username:'alice',password:'SecureAlice!123',confirmPassword:'SecureAlice!123'});assert.equal(a.status,201);at=a.body.csrfToken;
 const b=await post(bob,'/api/auth/register',bt,{username:'bob',password:'SecureBob!1234',confirmPassword:'SecureBob!1234'});assert.equal(b.status,201);bt=b.body.csrfToken;
 aliceId=(await alice.get('/api/user/me')).body.id;
 const encoded=(await db.pool.query('SELECT password_hash FROM users WHERE id=$1',[aliceId])).rows[0].password_hash;assert.match(encoded,/^\$2[aby]\$/);assert.notEqual(encoded,'SecureAlice!123');
 const duplicate=await post(bob,'/api/auth/register',bt,{username:'ALICE',password:'SecureAlice!123',confirmPassword:'SecureAlice!123'});assert.equal(duplicate.status,409);
 assert.equal((await post(bob,'/api/auth/register',bt,{username:'short',password:'1234',confirmPassword:'1234'})).status,400);
 assert.equal((await post(bob,'/api/auth/register',bt,{username:'mismatch',password:'SecureAlice!123',confirmPassword:'Different!123'})).status,400);
 assert.equal((await alice.get('/api/admin/dashboard')).status,401);
});
test('owner login is isolated from normal user sessions',async()=>{
 const bad=await post(owner,'/api/admin/auth/login',ot,{username:'owner',password:'wrong'});assert.equal(bad.status,401);
 const r=await post(owner,'/api/admin/auth/login',ot,{username:'owner',password:'LocalTest!OwnerPass32'});assert.equal(r.status,200);ot=r.body.csrfToken;
 assert.equal((await owner.get('/api/admin/dashboard')).status,200);
 assert.equal((await owner.get('/api/user/me')).status,401);
});
test('provider catalogue is dynamic, descriptions/categories preserved and opt-in compliant',async()=>{
 assert.equal((await adminPost('/services/sync',{})).status,200);
 let d=(await alice.get('/api/user/services')).body;assert.equal(d.items.length,0);
 const enabled=await adminPost('/services/9201/policy',{enabled:true,reason:'Verified platform-permitted campaign setup with authorization.'});assert.equal(enabled.status,200);
 assert.equal((await adminPost('/services/9202/policy',{enabled:true,reason:'Attempt unsupported type for validation testing.'})).status,400);
 d=(await alice.get('/api/user/services?q=9201')).body;assert.equal(d.items.length,1);assert.equal(d.items[0].description,'Owner-authorized campaign setup.');assert.deepEqual(d.categories,['Permitted marketing']);
 const precise=(await owner.get('/api/admin/services?q=9203')).body.items[0];assert.equal(precise.max_quantity,2147483647);assert.equal(precise.retail_rate_micro,'17675483');assert.equal((await owner.get('/api/admin/services?q=9204')).body.items[0].retail_rate_micro,'1916063544189300000000');
 const errorStub={...stub,services:async()=>[{service:1}]};const alternate=await createApp({...loadConfig({...process.env,DATABASE_URL:process.env.TEST_DATABASE_URL,SESSION_SECRET:'a'.repeat(32),OWNER_PASSWORD:'ValidOwner!123',PROVIDER_CURRENCY:'USD',PROVIDER_TO_INR:'100'}),ownerPassword:'ValidOwner!123'},db,errorStub);await assert.rejects(()=>alternate.domain.syncServices());assert.equal((await alice.get('/api/user/services')).body.items.length,1);
});
test('deposits: minimum amount, unique normalized UTR, exact-once concurrent approval',async()=>{
 assert.equal((await userPost('/deposits',{amount:'0.01',utr:'REFERENCE12345'})).status,400);
 const r=await userPost('/deposits',{amount:'1000',utr:'utrreference123'});assert.equal(r.status,201);depositId=r.body.deposit.id;
 assert.equal((await post(bob,'/api/user/deposits',bt,{amount:'1000',utr:'UTRREFERENCE123'})).status,409);
 assert.equal((await adminPost('/deposits/'+depositId+'/review',{decision:'Approved',reason:'Missing payment verification checkbox.',verified:false})).status,400);
 const approvals=await Promise.all([1,2].map(()=>adminPost('/deposits/'+depositId+'/review',{decision:'Approved',reason:'Matched bank statement amount and exact UTR.',verified:true})));assert.ok(approvals.every(x=>x.status===200));
 const u=(await alice.get('/api/user/me')).body;assert.equal(u.balance_paise,'100000');assert.equal((await db.pool.query("SELECT count(*)::int n FROM transactions WHERE reference=$1",['deposit:'+depositId])).rows[0].n,1);
});
test('reject deposit never credits wallet or mutates approved deposit',async()=>{
 const d=(await userPost('/deposits',{amount:'50',utr:'REJECTEDREF123'})).body.deposit;
 assert.equal((await adminPost('/deposits/'+d.id+'/review',{decision:'Rejected',reason:'No corresponding payment in bank statement.',verified:false})).status,200);
 assert.equal((await adminPost('/deposits/'+depositId+'/review',{decision:'Rejected',reason:'Cannot reverse an approved request.',verified:false})).status,409);
 assert.equal((await alice.get('/api/user/me')).body.balance_paise,'100000');
});
test('validation: service, quantity, target, price and insufficient balance',async()=>{
 assert.equal((await freshOrder({serviceId:'99999'})).status,400);
 assert.equal((await freshOrder({quantity:9})).status,400);
 assert.equal((await freshOrder({target:'javascript:alert(1)'})).status,400);
 assert.equal((await freshOrder({target:'https://127.0.0.1/a'})).status,400);
 assert.equal((await freshOrder({quotePaise:'1'})).status,409);
 assert.equal((await freshOrder({quantity:1001})).status,400);
 assert.equal((await post(bob,'/api/user/orders',bt,{serviceId:'9201',target:'https://example.com/b',quantity:10,quotePaise:'100',idempotencyKey:randomUUID()})).status,409);
});
test('order acceptance: retry-safe creation, atomic hold and exactly one provider submission',async()=>{
 const key=randomUUID();const results=await Promise.all([freshOrder({idempotencyKey:key}),freshOrder({idempotencyKey:key})]);assert.ok(results.every(r=>r.status===202));assert.equal(results[0].body.order.id,results[1].body.order.id);acceptedId=results[0].body.order.id;
 const u=(await alice.get('/api/user/me')).body;assert.equal(u.balance_paise,'100000');assert.equal(u.held_paise,'100');
 const before=addCalls;behavior='success';await domain.submitQueued();assert.equal(addCalls,before+1);await domain.submitQueued();assert.equal(addCalls,before+1);
 const after=(await alice.get('/api/user/me')).body;assert.equal(after.balance_paise,'99900');assert.equal(after.held_paise,'0');
 assert.equal((await freshOrder({idempotencyKey:key,target:'https://example.com/different'})).status,409);
 assert.equal((await bob.get('/api/user/orders/'+acceptedId)).status,404);
 assert.equal((await post(bob,'/api/user/orders/'+acceptedId+'/refresh',bt,{})).status,404);
});
test('provider rejection releases reservation and never debits wallet',async()=>{
 const before=(await alice.get('/api/user/me')).body.balance_paise;const r=await freshOrder();assert.equal(r.status,202);behavior='reject';await domain.submitQueued();behavior='success';
 const o=(await alice.get('/api/user/orders/'+r.body.order.id)).body.order;assert.equal(o.state,'rejected');const u=(await alice.get('/api/user/me')).body;assert.equal(u.balance_paise,before);assert.equal(u.held_paise,'0');
});
test('timeout holds funds, never retries, and owner evidence can safely release hold',async()=>{
 const r=await freshOrder();behavior='timeout';const before=addCalls;await domain.submitQueued();behavior='success';await domain.submitQueued();assert.equal(addCalls,before+1);
 const o=(await alice.get('/api/user/orders/'+r.body.order.id)).body.order;assert.equal(o.state,'reconcile');assert.equal((await alice.get('/api/user/me')).body.held_paise,'100');
 assert.equal((await adminPost('/orders/'+o.id+'/reconcile',{providerId:null,reason:'Provider support confirmed no order exists for this request.',verified:true})).status,200);assert.equal((await alice.get('/api/user/me')).body.held_paise,'0');
});
test('owner can reconcile confirmed uncertain order, invalid IDs never charged',async()=>{
 const r=await freshOrder();behavior='timeout';await domain.submitQueued();behavior='success';
 assert.equal((await adminPost('/orders/'+r.body.order.id+'/reconcile',{providerId:'81234',reason:'Provider support verified target, quantity and service match.',verified:true})).status,200);
 assert.equal((await alice.get('/api/user/orders/'+r.body.order.id)).body.order.provider_order_id,'81234');
 assert.equal((await adminPost('/orders/'+r.body.order.id+'/reconcile',{providerId:'81234',reason:'Duplicate reconciliation must not charge twice.',verified:true})).status,409);
});
test('status polling and proportional terminal refund is exact-once under concurrency',async()=>{
 const order=(await alice.get('/api/user/orders/'+acceptedId)).body.order;statuses.set(order.provider_order_id,{status:'Partial',remains:'4',start_count:'0',currency:'USD',charge:'0.06'});
 const before=BigInt((await alice.get('/api/user/me')).body.balance_paise);
 const results=await Promise.all([domain.refreshOrder(acceptedId),domain.refreshOrder(acceptedId)]);assert.ok(results.every(x=>x.status==='Partial'));
 assert.equal(BigInt((await alice.get('/api/user/me')).body.balance_paise),before+40n);
 assert.equal((await db.pool.query('SELECT count(*)::int n FROM transactions WHERE reference=$1',['refund:'+acceptedId])).rows[0].n,1);
});
test('manual adjustments are idempotent, audited and cannot consume reservations',async()=>{
 const key=randomUUID();const input={direction:'credit',amount:'25',reason:'Approved goodwill adjustment after support review.',idempotencyKey:key};const before=BigInt((await alice.get('/api/user/me')).body.balance_paise);
 const results=await Promise.all([adminPost('/users/'+aliceId+'/wallet',input),adminPost('/users/'+aliceId+'/wallet',input)]);assert.ok(results.every(r=>r.status===200));assert.equal(BigInt((await alice.get('/api/user/me')).body.balance_paise),before+2500n);
 const hold=(await freshOrder()).body.order;
 const available=(await alice.get('/api/user/me')).body.available_paise;
 const amount=String(BigInt(available)/100n)+'.99';
 const denied=await adminPost('/users/'+aliceId+'/wallet',{direction:'debit',amount,reason:'This test must not consume reserved wallet funds.',idempotencyKey:randomUUID()});assert.equal(denied.status,409);
 behavior='reject';await domain.submitQueued();behavior='success';assert.equal((await alice.get('/api/user/orders/'+hold.id)).body.order.state,'rejected');
 assert.ok((await owner.get('/api/admin/audit')).body.items.length>0);
});
test('suspension invalidates sessions and password change rotates auth version',async()=>{
 assert.equal((await adminPost('/users/'+aliceId+'/suspend',{suspended:true,reason:'Security test suspension with documented reason.'})).status,200);assert.equal((await alice.get('/api/user/me')).status,401);
 assert.equal((await adminPost('/users/'+aliceId+'/suspend',{suspended:false,reason:'Security test completed; restore access.'})).status,200);
 at=(await alice.get('/api/auth/csrf')).body.csrfToken;
 let r=await post(alice,'/api/auth/login',at,{username:'alice',password:'WrongPassword!123'});assert.equal(r.status,401);
 r=await post(alice,'/api/auth/login',at,{username:'alice',password:'SecureAlice!123'});assert.equal(r.status,200);at=r.body.csrfToken;
 r=await userPost('/password',{currentPassword:'SecureAlice!123',newPassword:'NewSecureAlice!123',confirmPassword:'NewSecureAlice!123'});assert.equal(r.status,200);at=r.body.csrfToken;
 assert.equal((await alice.get('/api/user/me')).status,200);
});
test('all list routes, individual details and frontend assets respond',async()=>{
 for(const route of ['/api/user/dashboard','/api/user/services','/api/user/orders','/api/user/deposits','/api/user/transactions','/api/user/me'])assert.equal((await alice.get(route)).status,200,route);
 for(const route of ['/api/admin/me','/api/admin/dashboard','/api/admin/users','/api/admin/users/'+aliceId,'/api/admin/orders','/api/admin/transactions','/api/admin/deposits','/api/admin/services','/api/admin/audit'])assert.equal((await owner.get(route)).status,200,route);
 for(const route of ['/','/login','/register','/admin','/admin/login','/styles.css','/app.js','/favicon.svg'])assert.equal((await request(app).get(route)).status,200,route);
 const r=await request(app).get('/');assert.match(r.headers['content-security-policy'],/script-src 'self'/);assert.equal(r.headers['x-content-type-options'],'nosniff');
 assert.equal((await request(app).get('/api/not-real')).status,404);
});
test('real provider HTTP adapter contract against controlled HTTP interception',async()=>{
 const actual=global.fetch,calls=[];global.fetch=async(url,opts)=>{calls.push({url,params:Object.fromEntries(opts.body)});return new Response(JSON.stringify(opts.body.get('action')==='add'?{order:55}:{balance:'5',currency:'USD'}),{status:200});};
 try{const p=createProvider({providerKey:'test-key-never-production'});assert.equal((await p.add({service:1,target:'https://example.com',quantity:10})).order,55);await p.balance();assert.equal(calls[0].url,'https://mysmm.org/api/v2');assert.deepEqual(calls[0].params,{key:'test-key-never-production',action:'add',service:'1',link:'https://example.com',quantity:'10'});
 global.fetch=async()=>new Response(JSON.stringify({error:'Incorrect service ID'}),{status:200});await assert.rejects(()=>p.services(),e=>e.kind==='rejected');
 global.fetch=async()=>new Response('<html>bad</html>',{status:200});await assert.rejects(()=>p.services(),e=>e.kind==='ambiguous');
 global.fetch=async()=>new Response(JSON.stringify({error:'busy'}),{status:503});await assert.rejects(()=>p.add({service:1,target:'https://example.com',quantity:10}),e=>e.kind==='ambiguous');
 }finally{global.fetch=actual;}
});
test('worker crash recovery marks interrupted submissions for review, never resubmits',async()=>{
 const r=await freshOrder();await db.pool.query("UPDATE orders SET state='submitting',status='Submitting',updated_at=now()-interval '5 minutes' WHERE id=$1",[r.body.order.id]);
 const before=addCalls;const stop=startWorker(db,domain);await new Promise(resolve=>setTimeout(resolve,300));await stop();assert.equal((await alice.get('/api/user/orders/'+r.body.order.id)).body.order.state,'reconcile');assert.equal(addCalls,before);
});
test('logout destroys user and owner sessions',async()=>{
 assert.equal((await post(alice,'/api/auth/logout',at,{})).status,200);assert.equal((await alice.get('/api/user/me')).status,401);
 assert.equal((await post(owner,'/api/admin/auth/logout',ot,{})).status,200);assert.equal((await owner.get('/api/admin/dashboard')).status,401);
});
'''
FILES['README.md'] = r'''
# ZUDO SMM PANEL

A full-stack Node.js / Express / PostgreSQL service and wallet management application, with a responsive vanilla HTML/CSS/JavaScript interface. Includes separate member/owner sessions, a dynamic provider catalogue, durable order dispatch, wallet ledger, UPI deposit review and owner audit trail. There are **no fake provider responses in production**. Test fixtures live only in `test/`.

## Important launch boundaries

This is deployable application source, not a claim that an unaudited service is already production-certified. A live Render deployment, your real provider account, the permitted catalogue, pricing, bank verification, policies, backups and monitoring require your configuration and acceptance testing. No GitHub repository or Render account is modified by this script.

- The API key previously pasted into chat must be rotated. Set the replacement in Render secrets as `SMM_API_KEY`; do not paste it into source, the README, screenshots or GitHub.
- `8318` is intentionally **not** accepted as an owner password. Set a unique password of 12+ characters containing uppercase/lowercase letters, a digit and a symbol, maximum 72 UTF-8 bytes. Use a password manager. The same policy applies to member registration.
- All wallet values are INR. Verify provider currency and explicitly configure the conversion before accepting money. No implied 1:1 USD/INR conversion exists.
- All imported services start disabled. Enable only independently reviewed, legitimate services that comply with destination platform rules, provider terms and applicable law. Automated fake engagement, spam, impersonation and deceptive activity should not be enabled. A human review is required; this application cannot determine compliance from a provider service name.
- The requested order form supports the provider's **Default** order type. Other types may require custom comments, subscriptions or other payloads. They remain visible to the owner but cannot be enabled or ordered. No parameters are guessed.

## Prerequisites

Node.js 22 LTS (22 or 24), npm, PostgreSQL 15+. Python 3.9+ is needed only to unpack the single-file project generator.

## Run locally

1. Run the supplied generator: `python3 zudo_setup.py --output zudo-smm-panel --install`.
2. In the generated folder copy `.env.example` to `.env` and populate its values. Create a local PostgreSQL database and set its `DATABASE_URL`. Do not upload `.env` to GitHub.
3. `npm start` automatically applies versioned migrations with a database advisory lock, validates configuration, starts the HTTP server and starts a single-leader background worker.
4. Open `http://localhost:3000` for members, `http://localhost:3000/admin` for the owner.
5. Owner: sync the provider catalogue, review compliance and enable permitted Default-type services. Make a small real UPI payment to the configured recipient, independently verify it and approve the matching request. Test a real permitted order only after checking provider balance and pricing.

Without a provider key, local account/wallet administration works but live catalogue synchronization and ordering do not. Production startup requires a provider key. There is no mock mode.

## GitHub → Render (no source editing required)

1. Generate the project and upload **the generated folder contents**, not just this generator, to a new private GitHub repository. Include `package-lock.json` and `render.yaml`; exclude `.env` and `node_modules`.
2. In Render select **New → Blueprint**, connect GitHub, choose the repository and create resources from `render.yaml`.
3. Enter the secrets prompted by Render: `OWNER_PASSWORD` and the rotated `SMM_API_KEY`. The supplied account was read-only verified as INR, so the Blueprint defaults to `PROVIDER_CURRENCY=INR` and `PROVIDER_TO_INR=1`. Re-check currency after rotation; change these environment variables in Render if the new account differs. The owner username defaults to `owner`.
4. Render provisions a paid Node web service and persistent PostgreSQL database. The included plans are paid; review current Render costs/region availability before creation. Build uses `npm ci --omit=dev`; start uses `npm start`. Startup runs migrations automatically. No manual SQL or file edits are needed.
5. Render provides `RENDER_EXTERNAL_HOSTNAME`; the app derives its HTTPS origin from this variable. For a custom domain, set `APP_ORIGIN=https://your-domain.example` in Render and use that canonical domain. Requests from other origins are intentionally rejected.
6. `/healthz` verifies database connectivity and returns 200/503. Check deployment logs, sign in as owner, sync services and perform the launch acceptance checks below.
7. Configure database backups/PITR supported by your database plan, off-platform backup exports, uptime checks and alerting. Restore-test backups before accepting customer deposits.

Render private Postgres uses `DATABASE_SSL=disable` on its private network. For an external TLS database set `DATABASE_SSL=verify` and use a certificate chain trusted by Node. Do not set `rejectUnauthorized:false` or `NODE_TLS_REJECT_UNAUTHORIZED=0`. If your external database needs a custom CA use Node's `NODE_EXTRA_CA_CERTS` through an appropriate deployment configuration.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `NODE_ENV` | Render: production | Secure cookies, HTTPS origin validation, HSTS |
| `PORT` | No | Defaults 3000; Render supplies its port |
| `DATABASE_URL` | Yes | Persistent PostgreSQL connection string; injected by Blueprint |
| `DATABASE_SSL` | No | `disable` for local/private network; `verify` for trusted external TLS |
| `SESSION_SECRET` | Yes | 32+ random characters; Blueprint generates it |
| `OWNER_USERNAME` | No | Defaults `owner`; 3–32 letters/numbers/underscores |
| `OWNER_PASSWORD` | Yes | Strong owner login secret, never sent to frontend |
| `APP_ORIGIN` | Locally default / custom domain required | Canonical origin; Render hostname is auto-detected |
| `SMM_API_KEY` | Yes in production | Rotated provider API secret; backend only |
| `PROVIDER_CURRENCY` | Defaults INR | Must match exact provider `balance` currency; supplied account was verified as INR |
| `PROVIDER_TO_INR` | Yes if non-INR | INR per one provider currency unit; verify and maintain manually |
| `MARKUP_PERCENT` | No | 0–1000; defaults 20 |
| `UPI_ID` | No | Defaults `Fearlessaditya@fam`; verify recipient ownership independently |
| `SUPPORT_URL` | Fixed brand destination | Support is intentionally fixed to `https://t.me/manwithoutego` |
| `TEST_DATABASE_URL` | Test only | Disposable PostgreSQL database; test suite truncates panel tables |

Rates are provider price **per 1,000 units**. The services-list docs show rate fields but do not state the billing unit explicitly in the retrieved example: confirm this convention and the currency with your account/provider before enabling services. This unit is a required operator acceptance check, not a silently verified fact. Retail INR rate = provider rate × configured FX × (1 + markup/100). Rates are stored as integer micro-INR in PostgreSQL NUMERIC(40,0), preserving unusually large upstream prices as well as 14-decimal provider inputs. Individual orders are still capped at ₹10,00,000. Final order paise = ceiling(quantity × rate_micro / 10,000,000). All balance and ledger arithmetic uses PostgreSQL BIGINT and Node BigInt; no floating-point wallet arithmetic. Catalogue displays a rounded-up two-decimal per-1,000 price; the exact micro-rate determines the total estimate. The server requires the client estimate to match, rejecting changed prices.

## Provider contract and limitations

Official reference: https://mysmm.org/api ; endpoint: https://mysmm.org/api/v2 . Requests use form-encoded server-side POSTs with `key` and `action`.

- `services`: provider catalogue with service ID, name, category, type, rate, min/max. Categories are derived from this list—there is no documented separate category endpoint.
- `add`: Default type uses `service`, `link`, `quantity`; successful response contains `order`.
- `status`: accepts `order`, returns status, start_count, remains, charge and currency. Local details include the original request and latest documented status fields; no separate “order details” endpoint is invented.
- `balance`: verifies currency before every catalogue sync.
- Service descriptions are retained and displayed only if the provider actually supplies a `description` field. The public example does not guarantee it. If missing, the interface says so; it never fabricates descriptions.
- Read-only verification of the supplied account succeeded: INR currency, 242 services, 60 categories, 238 Default-type services; Package and Subscriptions are also present. No descriptions were returned. Rates included 14 fractional digits and one unusually large rate; quantities reached 2,147,483,647. Catalogue parsing and regression tests cover those observed shapes. These counts are observations, not hardcoded production data.\n- No documented provider idempotency key or client-reference lookup is assumed. A successful response can be lost over the network. Exactly-once **external** delivery cannot be guaranteed by this API. Local requests/ledger effects are idempotent, while uncertain submissions stop for manual reconciliation instead of being automatically retried.
- Automated status checks run approximately every 30 seconds for eligible orders, subject to provider latency, server uptime, backlog and rate limits; browser account views poll every 20 seconds. This is polling, not push/websocket streaming. Manual refresh is throttled per order to 15 seconds.
- The worker is inside the web service, protected by a PostgreSQL advisory leader lock. Use an always-on paid Render service. Long backlogs need a dedicated worker and provider-specific rate controls; do not assume unlimited throughput.

## Wallet & order invariants

1. A member submits a UUID idempotency key. The server locks that wallet, validates the cached and reviewed service, quantity, HTTPS target, price and available balance, inserts a durable queued order and reserves its cost in one database transaction.
2. `available = balance_paise - held_paise`. Reservation is **not** a charge. Reserved funds cannot be spent or manually debited.
3. A worker commits `submitting` before making the provider call. A confirmed response settles the reservation, debits the balance and creates one unique ledger transaction atomically.
4. A definitive provider rejection releases the reservation with no charge. HTTP/network errors, invalid responses or interrupted submission retain the reservation and enter `reconcile`. A worker crash during submission is marked uncertain after two minutes.
5. The owner independently matches provider account records to target, service and quantity, records evidence, then supplies a verified provider order ID to settle—or confirms that no order exists to release the hold. The status endpoint cannot prove the target belongs to a given ID, so independent verification is mandatory.
6. Provider terminal `Partial`, `Canceled`, `Cancelled` statuses refund the original retail price proportionally to the validated unfulfilled `remains` value, rounded down to paise. Completed orders have no automatic refund. A terminal status is not subsequently overwritten; contradictory upstream corrections require independently reviewed manual adjustments. Refunds use a unique reference and row lock to prevent double credit.
7. Changing service name/category/type/description/quantity limits automatically revokes its approval. Disabling/deleting a provider service prevents new and queued submissions; already accepted orders keep their original amount and details.
8. Catalogue entries older than 30 minutes cannot be ordered. Removed services are retained as inactive for referential integrity. Pagination exposes the entire permitted catalogue, not a hardcoded subset.

## UPI deposit verification

Members transfer money in their own UPI app, then submit amount and actual UTR. A UPI deep link is a convenience only: it neither creates a payment guarantee nor verifies a transfer. UTR is normalized to uppercase and globally unique. Owner approves/rejects after independent bank verification, records a reason, and approvals create a credit exactly once inside a row-locked transaction. Rejection does not credit. Approved requests cannot be changed to rejected. Refunds/corrections require an explicit audited wallet action; this panel does not send UPI refunds or implement automatic payment gateway verification. Never ask customers for OTPs/PINs.

## Pages and administration

Member: Dashboard, New order, searchable/category-filtered Services, paginated My orders, Add funds/deposit history, Transaction history, Telegram Support, Profile/password change, logout.

Owner: Overview, paginated/filterable Deposit requests, searchable Users/history/suspension, All orders/status refresh/uncertain submission reconciliation, full provider Service policies/sync, Wallet ledger/manual credits and debits with reason/idempotency, paginated Audit log, Telegram Support and separate logout.

## Security model

- bcrypt cost 12; minimum strong-password policy and 72-byte maximum.
- Separate owner/member session cookies and namespaces, PostgreSQL session store; regeneration on login/password change; owner two-hour and member eight-hour sliding sessions; HttpOnly, SameSite Strict and Secure in production.
- Session auth-version checks invalidate all member sessions after password change/suspension. Owner credential changes require a restart; change SESSION_SECRET as well to invalidate all sessions.
- Synchronizer CSRF token plus exact canonical Origin check on every unsafe API request, including login/logout.
- Helmet/CSP with no inline executable scripts or styles, escaped DOM rendering and plain-text service descriptions, parameterized SQL and bounded JSON inputs. External HTTPS target URLs are passed to the provider, never fetched by this server.
- PostgreSQL-backed API, login, deposit and order rate limits survive restarts and work across service instances.
- Audited owner actions with mandatory reasons; no public endpoint can choose another user's wallet/order identity.
- Secrets/raw provider errors/request bodies are not logged. Public errors hide raw database failures. `/healthz` only reveals database availability.
- This repository has no password-reset endpoint/email system and no automatic tax invoicing, KYC/AML, card payment processing or 2FA. Add risk-appropriate controls (especially owner MFA/IP restrictions), legal policies, privacy/retention process, abuse monitoring and an independent penetration test before public financial use.
- Audit/ledger entries are append-only through the application but a PostgreSQL administrator can alter data. Use restricted DB roles, off-site audit exports and tamper-evident storage if your compliance requirements demand them.
- Rate-limit keys contain IP addresses. Establish a lawful retention policy. The worker prunes rate-limit records that expired over a day ago, checking hourly. Session rows are automatically pruned.

## Migrations and operations

Migrations in `migrations/*.sql` are ordered, advisory-locked and SHA-256 checksummed in `schema_migrations`. Do not edit already applied migrations: add a new one. Back up before deployment. There is no destructive auto-reset in production. Database data persists independently of Render web-server filesystem/redeploys. Never use the application repository to store customer exports or credentials. Health check failure does not itself retry provider submissions.

Run `npm run migrate` for a standalone initialization if needed; normal `npm start` does this automatically. For database outages the app returns safe errors and the worker resumes when the database recovers. After any outage, inspect `Needs review` orders before considering provider retries.

## Tests

`npm ci` (without `--omit=dev`), then set `TEST_DATABASE_URL` to a **dedicated disposable PostgreSQL database** and run `npm run check && npm test`.

Tests use real PostgreSQL migrations, sessions, constraints, row locks and transactions. Only the provider transport is controlled/injected for deterministic cases. They cover registration/login/uniqueness/hashing, password validation, CSRF/owner isolation, deposits/duplicate UTR/concurrent approval/rejection, dynamic catalogue/policy/type validation, quantity/URL/price/balance validation, repeat-request deduplication, provider rejection/timeouts/reconciliation, partial refunds, audited manual adjustments, suspension/password change, list routes/frontend files, adapter payloads/error contracts, worker crash recovery and logout.

Browser tests: run `npx playwright install --with-deps chromium`, then set a disposable `TEST_DATABASE_URL` and run `npm run test:browser`. This launches a loopback-only test server with an explicitly isolated provider fixture, exercises member/owner registration, deposits/approval, catalogue policy, orders, wallet adjustments, password change, all pages, mobile navigation and 390/768/1440-pixel viewport overflow checks. It saves dashboard screenshots under ignored `test-results/`. Browser tests also truncate their test database; never run against production.\n\n`TEST_REPORT.txt` records actual verification performed during delivery and explicitly lists unverified live dependencies. It is not a future CI guarantee. Do not run the tests against your production database.

### Required launch acceptance checks

- Rotate the key, verify UPI ownership and select a strong unique owner password.
- Confirm provider currency **and per-1,000 billing convention**; configure FX/markup and verify a sample price manually.
- Verify real credentials with a catalogue/balance request; independently review permitted services and descriptions.
- Test a real UPI deposit and owner bank verification; confirm one wallet credit, rejection and duplicate-reference protection.
- With explicit budget authorization, place one small real permitted order; verify its provider ID, charge/status, outcome and wallet ledger.
- Simulate provider ambiguity in staging and rehearse reconciliation without duplicate charges.
- Verify member data isolation, owner access restrictions, cookie security and logout at your HTTPS Render/custom domain.
- Test mobile/tablet/desktop browsers and assistive technology for your audience.
- Establish backup/restore drills, monitoring, reconciliation processes, refund terms, customer support and an incident response plan.

## Sources

Provider documentation: https://mysmm.org/api
Render Blueprint specification: https://render.com/docs/blueprint-spec
Render infrastructure as code: https://render.com/docs/infrastructure-as-code
Telegram support: https://t.me/manwithoutego
'''
FILES['playwright.config.js'] = r'''
const {defineConfig}=require('@playwright/test');
module.exports=defineConfig({testDir:'./test/browser',fullyParallel:false,workers:1,timeout:60000,reporter:'list',use:{baseURL:'http://127.0.0.1:3200',headless:true},webServer:{command:'node test/browser-server.js',url:'http://127.0.0.1:3200/healthz',reuseExistingServer:false,timeout:30000}});
'''
FILES['test/browser-server.js'] = r'''
// Explicit, test-only in-process provider fixture. Never imported by server.js.
const {loadConfig}=require('../src/config');
const {createDb}=require('../src/db');
const {createApp}=require('../src/app');
const {startWorker}=require('../src/worker');
(async()=>{
 if(!process.env.TEST_DATABASE_URL || process.env.NODE_ENV==='production')throw new Error('A disposable TEST_DATABASE_URL is required; never run in production.');
 const config=loadConfig({...process.env,NODE_ENV:'test',DATABASE_URL:process.env.TEST_DATABASE_URL,SESSION_SECRET:'isolated-browser-test-session-secret-0000',OWNER_USERNAME:'owner',OWNER_PASSWORD:'BrowserOwner!1234',PROVIDER_CURRENCY:'INR',PROVIDER_TO_INR:'1',MARKUP_PERCENT:'0',APP_ORIGIN:'http://127.0.0.1:3200',PORT:'3200'});
 const db=createDb(config);await db.migrate();await db.pool.query('TRUNCATE admin_logs,transactions,deposits,orders,services_cache,users,sessions,request_limits RESTART IDENTITY CASCADE');
 let sequence=10000;
 const provider={balance:async()=>({currency:'INR',balance:'10000'}),services:async()=>[{service:9201,name:'Authorized campaign setup',category:'Permitted marketing',description:'Authorized marketing setup for approved business accounts.',type:'Default',rate:'100',min:'10',max:'1000'}],add:async()=>({order:++sequence}),status:async()=>({status:'Completed',remains:'0',start_count:'0',currency:'INR',charge:'1'})};
 const {app,domain}=await createApp(config,db,provider);await domain.syncServices();
 const stopWorker=startWorker(db,domain);const server=app.listen(3200,'127.0.0.1');
 async function stop(){server.close();await stopWorker();await db.pool.end();process.exit(0);}process.on('SIGTERM',stop);process.on('SIGINT',stop);
})();
'''
FILES['test/browser/panel.spec.js'] = r'''
const {test,expect}=require('@playwright/test');
test('member and owner end-to-end workflows at desktop, tablet and mobile sizes',async({browser},testInfo)=>{
 const context=await browser.newContext({viewport:{width:1440,height:960}});const page=await context.newPage();const errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.goto('/register');await expect(page.getByRole('heading',{name:'Create your account'})).toBeVisible();
 await page.locator('#username').fill('browsermember');await page.locator('#password').fill('BrowserMember!123');await page.locator('#confirmPassword').fill('BrowserMember!123');await page.getByRole('button',{name:'Create account'}).click();
 await expect(page.getByRole('heading',{name:'Welcome back, browsermember.'})).toBeVisible();
 await page.screenshot({path:testInfo.outputPath('desktop-dashboard.png'),fullPage:true});
 await page.locator('nav a[href="#funds"]').click();await expect(page.getByRole('heading',{name:'Add funds',exact:true})).toBeVisible();await page.locator('#amount').fill('500');await page.locator('#utr').fill('BROWSERUTR1234');await page.getByRole('checkbox').check();await page.getByRole('button',{name:'Submit for verification'}).click();await expect(page.getByText('Pending',{exact:true}).first()).toBeVisible();
 const ownerContext=await browser.newContext({viewport:{width:1440,height:960}});const owner=await ownerContext.newPage();owner.on('pageerror',error=>errors.push(error.message));
 await owner.goto('/admin');await owner.locator('#username').fill('owner');await owner.locator('#password').fill('BrowserOwner!1234');await owner.getByRole('button',{name:'Open owner workspace'}).click();await expect(owner.getByRole('heading',{name:'Owner overview'})).toBeVisible();
 await owner.locator('nav a[href="#deposits"]').click();await owner.getByRole('button',{name:'Approve',exact:true}).click();await owner.locator('#modal input[type=checkbox]').check();await owner.locator('#reason').fill('Matched actual receipt and amount in bank test fixture.');await owner.locator('#modal button[type=submit]').click();await expect(owner.locator('.badge').filter({hasText:'Approved'}).first()).toBeVisible();
 await owner.locator('nav a[href="#services"]').click();await owner.getByRole('button',{name:'Review & enable'}).click();await owner.locator('#reason').fill('Reviewed authorized campaign setup and applicable platform rules.');await owner.locator('#modal button[type=submit]').click();await expect(owner.getByText('Active',{exact:true}).first()).toBeVisible();
 await page.reload();await page.locator('nav a[href="#new-order"]').click();await page.locator('#order-service').selectOption('9201');await page.locator('#target').fill('https://example.com/authorized-business');await page.locator('#quantity').fill('10');await expect(page.locator('#order-total')).toHaveText('₹1.00');await page.getByRole('checkbox').check();await page.getByRole('button',{name:'Submit order'}).click();await expect(page.getByRole('heading',{name:'My orders',exact:true})).toBeVisible();await expect(page.getByText('Authorized campaign setup',{exact:true}).first()).toBeVisible();
 // All member pages are live rendered, not empty navigation targets.
 for(const [hash,title] of [['dashboard','Welcome back, browsermember.'],['services','Service catalogue'],['orders','My orders'],['funds','Add funds'],['transactions','Transaction history'],['support','A little help, when you need it.'],['profile','Your profile']]){await page.goto('/#'+hash);await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();}
 await page.locator('#currentPassword').fill('BrowserMember!123');await page.locator('#newPassword').fill('BrowserChanged!123');await page.locator('#confirmPassword').fill('BrowserChanged!123');await page.getByRole('button',{name:'Update password'}).click();await expect(page.getByText('Password updated. Other sessions have been invalidated.')).toBeVisible();
 for(const [hash,title] of [['users','User management'],['orders','All orders'],['transactions','Wallet ledger'],['audit','Owner audit trail'],['support','A little help, when you need it.']]){await owner.goto('/admin#'+hash);await expect(owner.getByRole('heading',{name:title,exact:true})).toBeVisible();}
 await owner.goto('/admin#users');await owner.getByRole('button',{name:'History',exact:true}).click();await expect(owner.locator('#modal')).toBeVisible();await owner.getByRole('button',{name:'Close',exact:true}).click();
 await owner.getByRole('button',{name:'Adjust wallet'}).click();await owner.locator('#adjustment').fill('5');await owner.locator('#reason').fill('Authorized browser-test goodwill adjustment.');await owner.locator('#modal button[type=submit]').click();await expect(owner.getByText('Changes saved successfully.').first()).toBeVisible();
 for(const viewport of [{width:390,height:844},{width:768,height:1024},{width:1440,height:960}]){
  await page.setViewportSize(viewport);for(const hash of ['dashboard','new-order','services','orders','funds','transactions','support','profile']){await page.goto('/#'+hash);await expect(page.locator('#page h1')).toBeVisible();const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);expect(overflow,hash+' horizontal overflow '+viewport.width).toBeFalsy();if(viewport.width===390&&hash==='dashboard'){await page.waitForTimeout(300);await page.screenshot({path:testInfo.outputPath('mobile-dashboard.png'),fullPage:true});}}
  await owner.setViewportSize(viewport);for(const hash of ['dashboard','deposits','users','orders','services','transactions','audit','support']){await owner.goto('/admin#'+hash);await expect(owner.locator('#page h1')).toBeVisible();expect(await owner.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),hash+' owner overflow '+viewport.width).toBeFalsy();}
 }
 await page.setViewportSize({width:390,height:844});await page.locator('#menu').click();await expect(page.locator('.sidebar')).toHaveClass(/open/);await page.locator('nav a[href="#dashboard"]').click();await expect(page.locator('.sidebar')).not.toHaveClass(/open/);
 await page.setViewportSize({width:1440,height:960});await page.locator('#logout').click();await expect(page.getByRole('heading',{name:'Welcome back.'})).toBeVisible();await page.locator('#username').fill('browsermember');await page.locator('#password').fill('BrowserChanged!123');await page.getByRole('button',{name:'Sign in to workspace'}).click();await expect(page.getByRole('heading',{name:'Welcome back, browsermember.'})).toBeVisible();
 expect(errors).toEqual([]);await context.close();await ownerContext.close();
});
'''
FILES['test/fixtures-live-shape.json'] = r'''{"description":"Sanitized structural observations from read-only provider verification; no credentials or customer data.","currency":"INR","serviceCountAtVerification":242,"categoryCountAtVerification":60,"types":["Default","Package","Subscriptions"],"maxQuantityObserved":2147483647,"maxDecimalPlacesObserved":14,"descriptionsPresent":false}'''
FILES['migrations/003_precise_provider_rates.sql'] = r'''
-- The live provider includes high-precision decimals and occasional enormous rates.
-- Preserve all positive rates exactly; the server separately caps individual order costs.
ALTER TABLE services_cache ALTER COLUMN retail_rate_micro TYPE NUMERIC(40,0);
'''
FILES['.github/workflows/ci.yml'] = r'''
name: Verify ZUDO
on: [push, pull_request]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: ci-only-disposable-password
          POSTGRES_DB: zudo_test
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      TEST_DATABASE_URL: postgresql://postgres:ci-only-disposable-password@localhost:5432/zudo_test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
      - run: npm ci
      - run: npm run check
      - run: npm test
      - run: npx playwright install --with-deps chromium
      - run: npm run test:browser
'''
FILES['TEST_REPORT.txt'] = r'''
ZUDO SMM PANEL — delivery verification
Verification date: 2026-10-30

Environment: Linux, Node.js 22.23.4, npm 10.9.9, PostgreSQL 16,
Playwright Chromium headless. This is the observed delivery result, not a
claim that an unconfigured deployment is already live or production-certified.

PASS: all JavaScript files pass node --check via npm run check.
PASS: dependency installation; runtime dependency audit reported 0 vulnerabilities.
PASS: 19/19 backend integration tests using an actual PostgreSQL database.
PASS: migration application and repeat-run safety.
PASS: registration, bcrypt hashing, duplicate usernames and strong-password validation.
PASS: member/owner login, separate authorization, CSRF, account isolation and logout.
PASS: duplicate UTR rejection, concurrent approval with one credit, rejection with no credit.
PASS: database-backed wallets, atomic reservations/charges/refunds/manual adjustments.
PASS: retry idempotency, insufficient funds, invalid quantities/service/target/price handling.
PASS: controlled provider rejection, uncertain timeout, reconciliation and crash recovery.
PASS: dynamic catalogue/category import, description retention and unsupported-type blocking.
PASS: provider precision and 2,147,483,647 quantity-bound regression cases.
PASS: account suspension and password change/session version invalidation.
PASS: documented add/balance transport fields and provider error handling under interception.
PASS: owner/user lists, details, frontend assets and security headers.

PASS: one complete browser end-to-end scenario with multiple workflows:
- Real browser registration, login and database-backed member account.
- Deposit submission and owner approval through the UI.
- Catalogue review/enable through the UI.
- Order submission through the UI using an explicit test-only provider fixture.
- Owner wallet adjustment and user history, member password change and re-login.
- Every member/owner navigation page renders.
- Desktop 1440x960, tablet 768x1024, mobile-width 390x844 overflow checks.
- Mobile sidebar opening/closing and no uncaught browser JavaScript errors.
- Desktop/mobile screenshots generated and visually inspected during delivery.
Provider fixtures exist ONLY in test files, never in production server code.

PASS: supplied provider credentials tested with READ-ONLY balance/services actions.
- Currency: INR.
- Catalogue: 242 service entries, 60 categories.
- Types: 238 Default entries; Package and Subscriptions also present.
- Descriptions returned: 0. The UI explicitly discloses missing descriptions.
- Observed decimal precision up to 14 places; large quantities and unusual prices preserved.

PASS: actual server.js in NODE_ENV=production started against PostgreSQL.
- Automatic schema initialization and database-aware health endpoint.
- Secure, HttpOnly, SameSite=Strict cookie headers behind HTTPS proxy signal.
- HSTS header and unauthenticated owner rejection.
- Actual production worker fetched/persisted all 242 live catalogue entries.
- Enabled services after import: 0, awaiting owner compliance review.
- Graceful SIGTERM shutdown completed successfully.

NOT PERFORMED / REQUIRES OPERATOR ACCEPTANCE:
- No paid live provider order was submitted; live order count in smoke database was 0.
- No real UPI transfer, bank reconciliation, refund payout or payment-provider verification.
- No GitHub repository creation/upload or actual Render account deployment.
- No independent penetration test, load/soak test, backup restoration drill,
  cross-region failover, Safari/WebKit/iOS-device testing or legal compliance review.
- Provider per-1,000 billing convention must be confirmed with the account/provider;
  a read-only catalogue response alone does not prove its billing convention.
- Service compliance must be reviewed individually. No automatic approval by service name.
- Package/Subscriptions payloads are intentionally not implemented/enabled because
  the requested single target+quantity form supports Default-type orders only.
- Provider API does not document an idempotency key/client reference lookup.
  Exactly-once external order submission cannot be guaranteed under network ambiguity.
  Uncertain orders retain reservations and require independently evidenced reconciliation.

SECURITY:
The API key supplied in chat is not included in source or generated files.
Rotate it and configure SMM_API_KEY as a Render secret.
The requested weak password 8318 is not accepted; configure a strong OWNER_PASSWORD.
Never run the destructive test suites against a production database.
'''
FILES['package-lock.json'] = '{\n  "name": "zudo-smm-panel",\n  "version": "1.0.0",\n  "lockfileVersion": 3,\n  "requires": true,\n  "packages": {\n    "": {\n      "name": "zudo-smm-panel",\n      "version": "1.0.0",\n      "dependencies": {\n        "bcrypt": "^6.0.0",\n        "connect-pg-simple": "^10.0.0",\n        "decimal.js": "^10.6.0",\n        "dotenv": "^17.2.3",\n        "express": "^5.1.0",\n        "express-rate-limit": "^8.2.1",\n        "express-session": "^1.18.2",\n        "helmet": "^8.1.0",\n        "pg": "^8.16.3",\n        "zod": "^4.1.12"\n      },\n      "devDependencies": {\n        "@playwright/test": "^1.56.1",\n        "supertest": "^7.1.4"\n      },\n      "engines": {\n        "node": ">=22 <25"\n      }\n    },\n    "node_modules/@noble/hashes": {\n      "version": "1.8.0",\n      "resolved": "https://registry.npmjs.org/@noble/hashes/-/hashes-1.8.0.tgz",\n      "integrity": "sha512-jCs9ldd7NwzpgXDIf6P3+NrHh9/sD6CQdxHyjQI+h/6rDNo88ypBxxz45UDuZHz9r3tNz7N/VInSVoVdtXEI4A==",\n      "dev": true,\n      "license": "MIT",\n      "engines": {\n        "node": "^14.21.3 || >=16"\n      },\n      "funding": {\n        "url": "https://paulmillr.com/funding/"\n      }\n    },\n    "node_modules/@paralleldrive/cuid2": {\n      "version": "2.3.1",\n      "resolved": "https://registry.npmjs.org/@paralleldrive/cuid2/-/cuid2-2.3.1.tgz",\n      "integrity": "sha512-XO7cAxhnTZl0Yggq6jOgjiOHhbgcO4NqFqwSmQpjK3b6TEE6Uj/jfSk6wzYyemh3+I0sHirKSetjQwn5cZktFw==",\n      "dev": true,\n      "license": "MIT",\n      "dependencies": {\n        "@noble/hashes": "^1.1.5"\n      }\n    },\n    "node_modules/@playwright/test": {\n      "version": "1.64.1",\n      "resolved": "https://registry.npmjs.org/@playwright/test/-/test-1.64.1.tgz",\n      "integrity": "sha512-IaYGml/nSOiZWROfPtuIL7neuu9qDOZ3TNvNljUIrhDMxiGTgPjzj/g9p9RxpS2tSepPDRY+UwAaEeiKtUvIAg==",\n      "dev": true,\n      "license": "Apache-2.0",\n      "dependencies": {\n        "playwright": "1.64.1"\n      },\n      "bin": {\n        "playwright": "cli.js"\n      },\n      "engines": {\n        "node": ">=20"\n      }\n    },\n    "node_modules/accepts": {\n      "version": "2.0.0",\n      "resolved": "https://registry.npmjs.org/accepts/-/accepts-2.0.0.tgz",\n      "integrity": "sha512-5cvg6CtKwfgdmVqY1WIiXKc3Q1bkRqGLi+2W/6ao+6Y7gu/RCwRuAhGEzh5B4KlszSuTLgZYuqFqo5bImjNKng==",\n      "license": "MIT",\n      "dependencies": {\n        "mime-types": "^3.0.0",\n        "negotiator": "^1.0.0"\n      },\n      "engines": {\n        "node": ">= 0.6"\n      }\n    },\n    "node_modules/asap": {\n      "version": "2.0.6",\n      "resolved": "https://registry.npmjs.org/asap/-/asap-2.0.6.tgz",\n      "integrity": "sha512-BSHWgDSAiKs50o2Re8ppvp3seVHXSRM44cdSsT9FfNEUUZLOGWVCsiWaRPWM1Znn+mqZ1OfVZ3z3DWEzSp7hRA==",\n      "dev": true,\n      "license": "MIT"\n    },\n    "node_modules/asynckit": {\n      "version": "0.4.0",\n      "resolved": "https://registry.npmjs.org/asynckit/-/asynckit-0.4.0.tgz",\n      "integrity": "sha512-Oei9OH4tRh0YqU3GxhX79dM/mwVgvbZJaSNaRk+bshkj0S5cfHcgYakreBjrHwatXKbz+IoIdYLxrKim2MjW0Q==",\n      "dev": true,\n      "license": "MIT"\n    },\n    "node_modules/bcrypt": {\n      "version": "6.0.0",\n      "resolved": "https://registry.npmjs.org/bcrypt/-/bcrypt-6.0.0.tgz",\n      "integrity": "sha512-cU8v/EGSrnH+HnxV2z0J7/blxH8gq7Xh2JFT6Aroax7UohdmiJJlxApMxtKfuI7z68NvvVcmR78k2LbT6efhRg==",\n      "hasInstallScript": true,\n      "license": "MIT",\n      "dependencies": {\n        "node-addon-api": "^8.3.0",\n        "node-gyp-build": "^4.8.4"\n      },\n      "engines": {\n        "node": ">= 18"\n      }\n    },\n    "node_modules/body-parser": {\n      "version": "2.4.0",\n      "resolved": "https://registry.npmjs.org/body-parser/-/body-parser-2.4.0.tgz",\n      "integrity": "sha512-Ifk1KcLrxaGt1occQagQNFNNOqRt1LFuehEnHHzB8Z6cRgIxRU1TBaiIsUiCdA+gy5PL7Y1IX31DNKkRmxtXjQ==",\n      "license": "MIT",\n      "dependencies": {\n        "bytes": "^3.1.2",\n        "content-type": "^2.1.0",\n        "debug": "^4.4.3",\n        "http-errors": "^2.0.1",\n        "iconv-lite": "^0.7.3",\n        "on-finished": "^2.4.1",\n        "qs": "^6.16.1",\n        "raw-body": "^3.0.2",\n        "type-is": "^2.1.0"\n      },\n      "engines": {\n        "node": ">=18"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/bytes": {\n      "version": "3.1.2",\n      "resolved": "https://registry.npmjs.org/bytes/-/bytes-3.1.2.tgz",\n      "integrity": "sha512-/Nf7TyzTx6S3yRJObOAV7956r8cr2+Oj8AC5dt8wSP3BQAoeX58NoHyCU8P8zGkNXStjTSi6fzO6F0pBdcYbEg==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.8"\n      }\n    },\n    "node_modules/call-bind-apply-helpers": {\n      "version": "1.0.2",\n      "resolved": "https://registry.npmjs.org/call-bind-apply-helpers/-/call-bind-apply-helpers-1.0.2.tgz",\n      "integrity": "sha512-Sp1ablJ0ivDkSzjcaJdxEunN5/XvksFJ2sMBFfq6x0ryhQV/2b/KwFe21cMpmHtPOSij8K99/wSfoEuTObmuMQ==",\n      "license": "MIT",\n      "dependencies": {\n        "es-errors": "^1.3.0",\n        "function-bind": "^1.1.2"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      }\n    },\n    "node_modules/call-bound": {\n      "version": "1.0.4",\n      "resolved": "https://registry.npmjs.org/call-bound/-/call-bound-1.0.4.tgz",\n      "integrity": "sha512-+ys997U96po4Kx/ABpBCqhA9EuxJaQWDQg7295H4hBphv3IZg0boBKuwYpt4YXp6MZ5AmZQnU/tyMTlRpaSejg==",\n      "license": "MIT",\n      "dependencies": {\n        "call-bind-apply-helpers": "^1.0.2",\n        "get-intrinsic": "^1.3.0"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/combined-stream": {\n      "version": "1.0.8",\n      "resolved": "https://registry.npmjs.org/combined-stream/-/combined-stream-1.0.8.tgz",\n      "integrity": "sha512-FQN4MRfuJeHf7cBbBMJFXhKSDq+2kAArBlmRBvcvFE5BB1HZKXtSFASDhdlz9zOYwxh8lDdnvmMOe/+5cdoEdg==",\n      "dev": true,\n      "license": "MIT",\n      "dependencies": {\n        "delayed-stream": "~1.0.0"\n      },\n      "engines": {\n        "node": ">= 0.8"\n      }\n    },\n    "node_modules/component-emitter": {\n      "version": "1.3.1",\n      "resolved": "https://registry.npmjs.org/component-emitter/-/component-emitter-1.3.1.tgz",\n      "integrity": "sha512-T0+barUSQRTUQASh8bx02dl+DhF54GtIDY13Y3m9oWTklKbb3Wv974meRpeZ3lp1JpLVECWWNHC4vaG2XHXouQ==",\n      "dev": true,\n      "license": "MIT",\n      "funding": {\n        "url": "https://github.com/sponsors/sindresorhus"\n      }\n    },\n    "node_modules/connect-pg-simple": {\n      "version": "10.0.0",\n      "resolved": "https://registry.npmjs.org/connect-pg-simple/-/connect-pg-simple-10.0.0.tgz",\n      "integrity": "sha512-pBGVazlqiMrackzCr0eKhn4LO5trJXsOX0nQoey9wCOayh80MYtThCbq8eoLsjpiWgiok/h+1/uti9/2/Una8A==",\n      "license": "MIT",\n      "dependencies": {\n        "pg": "^8.12.0"\n      },\n      "engines": {\n        "node": "^18.18.0 || ^20.9.0 || >=22.0.0"\n      }\n    },\n    "node_modules/content-disposition": {\n      "version": "2.0.1",\n      "resolved": "https://registry.npmjs.org/content-disposition/-/content-disposition-2.0.1.tgz",\n      "integrity": "sha512-e+H0ZXHSWYrENhQzw1LPuP4oF5MzVKmDU6d3hxlvaPEYLLg62MxtQNPRx4SYSuYJSBUgnQIG4HIN2tEtNv7Dog==",\n      "license": "MIT",\n      "engines": {\n        "node": ">=18"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/content-type": {\n      "version": "2.1.0",\n      "resolved": "https://registry.npmjs.org/content-type/-/content-type-2.1.0.tgz",\n      "integrity": "sha512-mj7UPXE0jaqaOsukNZRUEfEi2AcL7C/vwmwcHV0O97eO1E1pxBZuyjlZrx5seTaNBg1U6+o35wpa35Qfcc+7ag==",\n      "license": "MIT",\n      "engines": {\n        "node": ">=18"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/cookie": {\n      "version": "0.7.2",\n      "resolved": "https://registry.npmjs.org/cookie/-/cookie-0.7.2.tgz",\n      "integrity": "sha512-yki5XnKuf750l50uGTllt6kKILY4nQ1eNIQatoXEByZ5dWgnKqbnqmTrBE5B4N7lrMJKQ2ytWMiTO2o0v6Ew/w==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.6"\n      }\n    },\n    "node_modules/cookie-signature": {\n      "version": "1.2.2",\n      "resolved": "https://registry.npmjs.org/cookie-signature/-/cookie-signature-1.2.2.tgz",\n      "integrity": "sha512-D76uU73ulSXrD1UXF4KE2TMxVVwhsnCgfAyTg9k8P6KGZjlXKrOLe4dJQKI3Bxi5wjesZoFXJWElNWBjPZMbhg==",\n      "license": "MIT",\n      "engines": {\n        "node": ">=6.6.0"\n      }\n    },\n    "node_modules/cookiejar": {\n      "version": "2.1.4",\n      "resolved": "https://registry.npmjs.org/cookiejar/-/cookiejar-2.1.4.tgz",\n      "integrity": "sha512-LDx6oHrK+PhzLKJU9j5S7/Y3jM/mUHvD/DeI1WQmJn652iPC5Y4TBzC9l+5OMOXlyTTA+SmVUPm0HQUwpD5Jqw==",\n      "dev": true,\n      "license": "MIT"\n    },\n    "node_modules/debug": {\n      "version": "4.4.3",\n      "resolved": "https://registry.npmjs.org/debug/-/debug-4.4.3.tgz",\n      "integrity": "sha512-RGwwWnwQvkVfavKVt22FGLw+xYSdzARwm0ru6DhTVA3umU5hZc28V3kO4stgYryrTlLpuvgI9GiijltAjNbcqA==",\n      "license": "MIT",\n      "dependencies": {\n        "ms": "^2.1.3"\n      },\n      "engines": {\n        "node": ">=6.0"\n      },\n      "peerDependenciesMeta": {\n        "supports-color": {\n          "optional": true\n        }\n      }\n    },\n    "node_modules/decimal.js": {\n      "version": "10.6.0",\n      "resolved": "https://registry.npmjs.org/decimal.js/-/decimal.js-10.6.0.tgz",\n      "integrity": "sha512-YpgQiITW3JXGntzdUmyUR1V812Hn8T1YVXhCu+wO3OpS4eU9l4YdD3qjyiKdV6mvV29zapkMeD390UVEf2lkUg==",\n      "license": "MIT"\n    },\n    "node_modules/delayed-stream": {\n      "version": "1.0.0",\n      "resolved": "https://registry.npmjs.org/delayed-stream/-/delayed-stream-1.0.0.tgz",\n      "integrity": "sha512-ZySD7Nf91aLB0RxL4KGrKHBXl7Eds1DAmEdcoVawXnLD7SDhpNgtuII2aAkg7a7QS41jxPSZ17p4VdGnMHk3MQ==",\n      "dev": true,\n      "license": "MIT",\n      "engines": {\n        "node": ">=0.4.0"\n      }\n    },\n    "node_modules/depd": {\n      "version": "2.0.0",\n      "resolved": "https://registry.npmjs.org/depd/-/depd-2.0.0.tgz",\n      "integrity": "sha512-g7nH6P6dyDioJogAAGprGpCtVImJhpPk/roCzdb3fIh61/s/nPsfR6onyMwkCAR/OlC3yBC0lESvUoQEAssIrw==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.8"\n      }\n    },\n    "node_modules/dezalgo": {\n      "version": "1.0.4",\n      "resolved": "https://registry.npmjs.org/dezalgo/-/dezalgo-1.0.4.tgz",\n      "integrity": "sha512-rXSP0bf+5n0Qonsb+SVVfNfIsimO4HEtmnIpPHY8Q1UCzKlQrDMfdobr8nJOOsRgWCyMRqeSBQzmWUMq7zvVig==",\n      "dev": true,\n      "license": "ISC",\n      "dependencies": {\n        "asap": "^2.0.0",\n        "wrappy": "1"\n      }\n    },\n    "node_modules/dotenv": {\n      "version": "17.4.2",\n      "resolved": "https://registry.npmjs.org/dotenv/-/dotenv-17.4.2.tgz",\n      "integrity": "sha512-nI4U3TottKAcAD9LLud4Cb7b2QztQMUEfHbvhTH09bqXTxnSie8WnjPALV/WMCrJZ6UV/qHJ6L03OqO3LcdYZw==",\n      "license": "BSD-2-Clause",\n      "engines": {\n        "node": ">=12"\n      },\n      "funding": {\n        "url": "https://dotenvx.com"\n      }\n    },\n    "node_modules/dunder-proto": {\n      "version": "1.0.1",\n      "resolved": "https://registry.npmjs.org/dunder-proto/-/dunder-proto-1.0.1.tgz",\n      "integrity": "sha512-KIN/nDJBQRcXw0MLVhZE9iQHmG68qAVIBg9CqmUYjmQIhgij9U5MFvrqkUL5FbtyyzZuOeOt0zdeRe4UY7ct+A==",\n      "license": "MIT",\n      "dependencies": {\n        "call-bind-apply-helpers": "^1.0.1",\n        "es-errors": "^1.3.0",\n        "gopd": "^1.2.0"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      }\n    },\n    "node_modules/ee-first": {\n      "version": "1.1.1",\n      "resolved": "https://registry.npmjs.org/ee-first/-/ee-first-1.1.1.tgz",\n      "integrity": "sha512-WMwm9LhRUo+WUaRN+vRuETqG89IgZphVSNkdFgeb6sS/E4OrDIN7t48CAewSHXc6C8lefD8KKfr5vY61brQlow==",\n      "license": "MIT"\n    },\n    "node_modules/encodeurl": {\n      "version": "2.0.1",\n      "resolved": "https://registry.npmjs.org/encodeurl/-/encodeurl-2.0.1.tgz",\n      "integrity": "sha512-Ev/hIyePLZtpL98x562lvPtenrUfGr0lfaf44HFZ+hDEwso7ccV9QAZrEVLg0hxNAzygaAFxy2dYaAKKM0G06A==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.8"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/es-define-property": {\n      "version": "1.0.1",\n      "resolved": "https://registry.npmjs.org/es-define-property/-/es-define-property-1.0.1.tgz",\n      "integrity": "sha512-e3nRfgfUZ4rNGL232gUgX06QNyyez04KdjFrF+LTRoOXmrOgFKDg4BCdsjW8EnT69eqdYGmRpJwiPVYNrCaW3g==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.4"\n      }\n    },\n    "node_modules/es-errors": {\n      "version": "1.3.0",\n      "resolved": "https://registry.npmjs.org/es-errors/-/es-errors-1.3.0.tgz",\n      "integrity": "sha512-Zf5H2Kxt2xjTvbJvP2ZWLEICxA6j+hAmMzIlypy4xcBg1vKVnx89Wy0GbS+kf5cwCVFFzdCFh2XSCFNULS6csw==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.4"\n      }\n    },\n    "node_modules/es-object-atoms": {\n      "version": "1.1.2",\n      "resolved": "https://registry.npmjs.org/es-object-atoms/-/es-object-atoms-1.1.2.tgz",\n      "integrity": "sha512-HWcBoN6NileqtSydK2FqHbS/LoDd2pqrnQHLyJzBj4kOp/ky2MWMN694xOfkK8/SnUsW2DH7EfyVlydKCsm1Zw==",\n      "license": "MIT",\n      "dependencies": {\n        "es-errors": "^1.3.0"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      }\n    },\n    "node_modules/es-set-tostringtag": {\n      "version": "2.1.0",\n      "resolved": "https://registry.npmjs.org/es-set-tostringtag/-/es-set-tostringtag-2.1.0.tgz",\n      "integrity": "sha512-j6vWzfrGVfyXxge+O0x5sh6cvxAog0a/4Rdd2K36zCMV5eJ+/+tOAngRO8cODMNWbVRdVlmGZQL2YS3yR8bIUA==",\n      "dev": true,\n      "license": "MIT",\n      "dependencies": {\n        "es-errors": "^1.3.0",\n        "get-intrinsic": "^1.2.6",\n        "has-tostringtag": "^1.0.2",\n        "hasown": "^2.0.2"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      }\n    },\n    "node_modules/escape-html": {\n      "version": "1.0.3",\n      "resolved": "https://registry.npmjs.org/escape-html/-/escape-html-1.0.3.tgz",\n      "integrity": "sha512-NiSupZ4OeuGwr68lGIeym/ksIZMJodUGOSCZ/FSnTxcrekbvqrgdUxlJOMpijaKZVjAJrWrGs/6Jy8OMuyj9ow==",\n      "license": "MIT"\n    },\n    "node_modules/etag": {\n      "version": "1.8.1",\n      "resolved": "https://registry.npmjs.org/etag/-/etag-1.8.1.tgz",\n      "integrity": "sha512-aIL5Fx7mawVa300al2BnEE4iNvo1qETxLrPI/o05L7z6go7fCw1J6EQmbK4FmJ2AS7kgVF/KEZWufBfdClMcPg==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.6"\n      }\n    },\n    "node_modules/express": {\n      "version": "5.3.0",\n      "resolved": "https://registry.npmjs.org/express/-/express-5.3.0.tgz",\n      "integrity": "sha512-qCqy1xSoaugxOD4IVHb1ZWdkvCF2W3aE2okKouWj8VwJ+ztskSiXoBnCSJqfKT+cVPJhuJqe9YLbY425+Zh00g==",\n      "license": "MIT",\n      "dependencies": {\n        "accepts": "^2.0.0",\n        "body-parser": "^2.3.0",\n        "content-disposition": "^2.0.1",\n        "content-type": "^2.0.0",\n        "cookie": "^0.7.1",\n        "cookie-signature": "^1.2.1",\n        "debug": "^4.4.0",\n        "depd": "^2.0.0",\n        "encodeurl": "^2.0.0",\n        "escape-html": "^1.0.3",\n        "etag": "^1.8.1",\n        "finalhandler": "^2.1.0",\n        "fresh": "^2.0.0",\n        "http-errors": "^2.0.0",\n        "merge-descriptors": "^2.0.0",\n        "mime-types": "^3.0.0",\n        "on-finished": "^2.4.1",\n        "once": "^1.4.0",\n        "parseurl": "^1.3.3",\n        "proxy-addr": "^2.0.8",\n        "qs": "^6.16.0",\n        "range-parser": "^1.2.1",\n        "router": "^2.2.0",\n        "send": "^1.1.0",\n        "serve-static": "^2.2.0",\n        "statuses": "^2.0.1",\n        "type-is": "^2.1.0",\n        "vary": "^1.1.2"\n      },\n      "engines": {\n        "node": ">= 18"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/express-rate-limit": {\n      "version": "8.7.2",\n      "resolved": "https://registry.npmjs.org/express-rate-limit/-/express-rate-limit-8.7.2.tgz",\n      "integrity": "sha512-U1ScocxDD9WI09LaBVypvNkOtNR5yWAmZLkuKJdAzIchA4YKFYF6GT5IKER7epG58oXtjvGlV0/6ii0F83EyZg==",\n      "license": "MIT",\n      "dependencies": {\n        "debug": "^4.4.3",\n        "ip-address": "^10.2.0"\n      },\n      "engines": {\n        "node": ">= 16"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/express-rate-limit"\n      },\n      "peerDependencies": {\n        "express": ">= 4.11"\n      }\n    },\n    "node_modules/express-session": {\n      "version": "1.19.0",\n      "resolved": "https://registry.npmjs.org/express-session/-/express-session-1.19.0.tgz",\n      "integrity": "sha512-0csaMkGq+vaiZTmSMMGkfdCOabYv192VbytFypcvI0MANrp+4i/7yEkJ0sbAEhycQjntaKGzYfjfXQyVb7BHMA==",\n      "license": "MIT",\n      "dependencies": {\n        "cookie": "~0.7.2",\n        "cookie-signature": "~1.0.7",\n        "debug": "~2.6.9",\n        "depd": "~2.0.0",\n        "on-headers": "~1.1.0",\n        "parseurl": "~1.3.3",\n        "safe-buffer": "~5.2.1",\n        "uid-safe": "~2.1.5"\n      },\n      "engines": {\n        "node": ">= 0.8.0"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/express-session/node_modules/cookie-signature": {\n      "version": "1.0.7",\n      "resolved": "https://registry.npmjs.org/cookie-signature/-/cookie-signature-1.0.7.tgz",\n      "integrity": "sha512-NXdYc3dLr47pBkpUCHtKSwIOQXLVn8dZEuywboCOJY/osA0wFSLlSawr3KN8qXJEyX66FcONTH8EIlVuK0yyFA==",\n      "license": "MIT"\n    },\n    "node_modules/express-session/node_modules/debug": {\n      "version": "2.6.9",\n      "resolved": "https://registry.npmjs.org/debug/-/debug-2.6.9.tgz",\n      "integrity": "sha512-bC7ElrdJaJnPbAP+1EotYvqZsb3ecl5wi6Bfi6BJTUcNowp6cvspg0jXznRTKDjm/E7AdgFBVeAPVMNcKGsHMA==",\n      "license": "MIT",\n      "dependencies": {\n        "ms": "2.0.0"\n      }\n    },\n    "node_modules/express-session/node_modules/ms": {\n      "version": "2.0.0",\n      "resolved": "https://registry.npmjs.org/ms/-/ms-2.0.0.tgz",\n      "integrity": "sha512-Tpp60P6IUJDTuOq/5Z8cdskzJujfwqfOTkrwIwj7IRISpnkJnT6SyJ4PCPnGMoFjC9ddhal5KVIYtAt97ix05A==",\n      "license": "MIT"\n    },\n    "node_modules/fast-safe-stringify": {\n      "version": "2.1.1",\n      "resolved": "https://registry.npmjs.org/fast-safe-stringify/-/fast-safe-stringify-2.1.1.tgz",\n      "integrity": "sha512-W+KJc2dmILlPplD/H4K9l9LcAHAfPtP6BY84uVLXQ6Evcz9Lcg33Y2z1IVblT6xdY54PXYVHEv+0Wpq8Io6zkA==",\n      "dev": true,\n      "license": "MIT"\n    },\n    "node_modules/finalhandler": {\n      "version": "2.1.1",\n      "resolved": "https://registry.npmjs.org/finalhandler/-/finalhandler-2.1.1.tgz",\n      "integrity": "sha512-S8KoZgRZN+a5rNwqTxlZZePjT/4cnm0ROV70LedRHZ0p8u9fRID0hJUZQpkKLzro8LfmC8sx23bY6tVNxv8pQA==",\n      "license": "MIT",\n      "dependencies": {\n        "debug": "^4.4.0",\n        "encodeurl": "^2.0.0",\n        "escape-html": "^1.0.3",\n        "on-finished": "^2.4.1",\n        "parseurl": "^1.3.3",\n        "statuses": "^2.0.1"\n      },\n      "engines": {\n        "node": ">= 18.0.0"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/form-data": {\n      "version": "4.0.6",\n      "resolved": "https://registry.npmjs.org/form-data/-/form-data-4.0.6.tgz",\n      "integrity": "sha512-vKatAh4SlVfgbv+YtmhiRjhEMJsYpsG1Y2rMQtR+SVSbytsSD1YGzDIcrAJmdFec88u/+VoGmxnl+80gL1tRCQ==",\n      "dev": true,\n      "license": "MIT",\n      "dependencies": {\n        "asynckit": "^0.4.0",\n        "combined-stream": "^1.0.8",\n        "es-set-tostringtag": "^2.1.0",\n        "hasown": "^2.0.4",\n        "mime-types": "^2.1.35"\n      },\n      "engines": {\n        "node": ">= 6"\n      }\n    },\n    "node_modules/form-data/node_modules/mime-db": {\n      "version": "1.52.0",\n      "resolved": "https://registry.npmjs.org/mime-db/-/mime-db-1.52.0.tgz",\n      "integrity": "sha512-sPU4uV7dYlvtWJxwwxHD0PuihVNiE7TyAbQ5SWxDCB9mUYvOgroQOwYQQOKPJ8CIbE+1ETVlOoK1UC2nU3gYvg==",\n      "dev": true,\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.6"\n      }\n    },\n    "node_modules/form-data/node_modules/mime-types": {\n      "version": "2.1.35",\n      "resolved": "https://registry.npmjs.org/mime-types/-/mime-types-2.1.35.tgz",\n      "integrity": "sha512-ZDY+bPm5zTTF+YpCrAU9nK0UgICYPT0QtT1NZWFv4s++TNkcgVaT0g6+4R2uI4MjQjzysHB1zxuWL50hzaeXiw==",\n      "dev": true,\n      "license": "MIT",\n      "dependencies": {\n        "mime-db": "1.52.0"\n      },\n      "engines": {\n        "node": ">= 0.6"\n      }\n    },\n    "node_modules/formidable": {\n      "version": "3.5.4",\n      "resolved": "https://registry.npmjs.org/formidable/-/formidable-3.5.4.tgz",\n      "integrity": "sha512-YikH+7CUTOtP44ZTnUhR7Ic2UASBPOqmaRkRKxRbywPTe5VxF7RRCck4af9wutiZ/QKM5nME9Bie2fFaPz5Gug==",\n      "dev": true,\n      "license": "MIT",\n      "dependencies": {\n        "@paralleldrive/cuid2": "^2.2.2",\n        "dezalgo": "^1.0.4",\n        "once": "^1.4.0"\n      },\n      "engines": {\n        "node": ">=14.0.0"\n      },\n      "funding": {\n        "url": "https://ko-fi.com/tunnckoCore/commissions"\n      }\n    },\n    "node_modules/forwarded": {\n      "version": "0.2.0",\n      "resolved": "https://registry.npmjs.org/forwarded/-/forwarded-0.2.0.tgz",\n      "integrity": "sha512-buRG0fpBtRHSTCOASe6hD258tEubFoRLb4ZNA6NxMVHNw2gOcwHo9wyablzMzOA5z9xA9L1KNjk/Nt6MT9aYow==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.6"\n      }\n    },\n    "node_modules/fresh": {\n      "version": "2.0.0",\n      "resolved": "https://registry.npmjs.org/fresh/-/fresh-2.0.0.tgz",\n      "integrity": "sha512-Rx/WycZ60HOaqLKAi6cHRKKI7zxWbJ31MhntmtwMoaTeF7XFH9hhBp8vITaMidfljRQ6eYWCKkaTK+ykVJHP2A==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.8"\n      }\n    },\n    "node_modules/function-bind": {\n      "version": "1.1.2",\n      "resolved": "https://registry.npmjs.org/function-bind/-/function-bind-1.1.2.tgz",\n      "integrity": "sha512-7XHNxH7qX9xG5mIwxkhumTox/MIRNcOgDrxWsMt2pAr23WHp6MrRlN7FBSFpCpr+oVO0F744iUgR82nJMfG2SA==",\n      "license": "MIT",\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/get-intrinsic": {\n      "version": "1.3.0",\n      "resolved": "https://registry.npmjs.org/get-intrinsic/-/get-intrinsic-1.3.0.tgz",\n      "integrity": "sha512-9fSjSaos/fRIVIp+xSJlE6lfwhES7LNtKaCBIamHsjr2na1BiABJPo0mOjjz8GJDURarmCPGqaiVg5mfjb98CQ==",\n      "license": "MIT",\n      "dependencies": {\n        "call-bind-apply-helpers": "^1.0.2",\n        "es-define-property": "^1.0.1",\n        "es-errors": "^1.3.0",\n        "es-object-atoms": "^1.1.1",\n        "function-bind": "^1.1.2",\n        "get-proto": "^1.0.1",\n        "gopd": "^1.2.0",\n        "has-symbols": "^1.1.0",\n        "hasown": "^2.0.2",\n        "math-intrinsics": "^1.1.0"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/get-proto": {\n      "version": "1.0.1",\n      "resolved": "https://registry.npmjs.org/get-proto/-/get-proto-1.0.1.tgz",\n      "integrity": "sha512-sTSfBjoXBp89JvIKIefqw7U2CCebsc74kiY6awiGogKtoSGbgjYE/G/+l9sF3MWFPNc9IcoOC4ODfKHfxFmp0g==",\n      "license": "MIT",\n      "dependencies": {\n        "dunder-proto": "^1.0.1",\n        "es-object-atoms": "^1.0.0"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      }\n    },\n    "node_modules/gopd": {\n      "version": "1.2.0",\n      "resolved": "https://registry.npmjs.org/gopd/-/gopd-1.2.0.tgz",\n      "integrity": "sha512-ZUKRh6/kUFoAiTAtTYPZJ3hw9wNxx+BIBOijnlG9PnrJsCcSjs1wyyD6vJpaYtgnzDrKYRSqf3OO6Rfa93xsRg==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.4"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/has-symbols": {\n      "version": "1.1.0",\n      "resolved": "https://registry.npmjs.org/has-symbols/-/has-symbols-1.1.0.tgz",\n      "integrity": "sha512-1cDNdwJ2Jaohmb3sg4OmKaMBwuC48sYni5HUw2DvsC8LjGTLK9h+eb1X6RyuOHe4hT0ULCW68iomhjUoKUqlPQ==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.4"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/has-tostringtag": {\n      "version": "1.0.2",\n      "resolved": "https://registry.npmjs.org/has-tostringtag/-/has-tostringtag-1.0.2.tgz",\n      "integrity": "sha512-NqADB8VjPFLM2V0VvHUewwwsw0ZWBaIdgo+ieHtK3hasLz4qeCRjYcqfB6AQrBggRKppKF8L52/VqdVsO47Dlw==",\n      "dev": true,\n      "license": "MIT",\n      "dependencies": {\n        "has-symbols": "^1.0.3"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/hasown": {\n      "version": "2.0.4",\n      "resolved": "https://registry.npmjs.org/hasown/-/hasown-2.0.4.tgz",\n      "integrity": "sha512-T2UbfbBEF32wiepXIsMlTW9+dDYC6wMh/t/vYA4tuOMKqWz/n3vr1NFSxQiyP+zk2mXsoMA/i/7qV6LKut1t1A==",\n      "license": "MIT",\n      "dependencies": {\n        "function-bind": "^1.1.2"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      }\n    },\n    "node_modules/helmet": {\n      "version": "8.3.0",\n      "resolved": "https://registry.npmjs.org/helmet/-/helmet-8.3.0.tgz",\n      "integrity": "sha512-Qgpiaws3Sm30Av8Eah6sjMCZZwjlBu+E68rhpCWBshY1lb09HtLwj5GviX0OyQIn+ulUS0iX0AxN5n3tLZzz1w==",\n      "license": "MIT",\n      "engines": {\n        "node": ">=18.0.0"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/EvanHahn"\n      }\n    },\n    "node_modules/http-errors": {\n      "version": "2.0.1",\n      "resolved": "https://registry.npmjs.org/http-errors/-/http-errors-2.0.1.tgz",\n      "integrity": "sha512-4FbRdAX+bSdmo4AUFuS0WNiPz8NgFt+r8ThgNWmlrjQjt1Q7ZR9+zTlce2859x4KSXrwIsaeTqDoKQmtP8pLmQ==",\n      "license": "MIT",\n      "dependencies": {\n        "depd": "~2.0.0",\n        "inherits": "~2.0.4",\n        "setprototypeof": "~1.2.0",\n        "statuses": "~2.0.2",\n        "toidentifier": "~1.0.1"\n      },\n      "engines": {\n        "node": ">= 0.8"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/iconv-lite": {\n      "version": "0.7.3",\n      "resolved": "https://registry.npmjs.org/iconv-lite/-/iconv-lite-0.7.3.tgz",\n      "integrity": "sha512-IKXpvIzjnC9XTAUbVBcMfGS0EPaIXtW6v+zr+RRp+hqULEpo0owZax6wyRwPOJbWbzjYspQwusTsfVr0ifh4uQ==",\n      "license": "MIT",\n      "dependencies": {\n        "safer-buffer": ">= 2.1.2 < 3.0.0"\n      },\n      "engines": {\n        "node": ">=0.10.0"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/inherits": {\n      "version": "2.0.4",\n      "resolved": "https://registry.npmjs.org/inherits/-/inherits-2.0.4.tgz",\n      "integrity": "sha512-k/vGaX4/Yla3WzyMCvTQOXYeIHvqOKtnqBduzTHpzpQZzAskKMhZ2K+EnBiSM9zGSoIFeMpXKxa4dYeZIQqewQ==",\n      "license": "ISC"\n    },\n    "node_modules/ip-address": {\n      "version": "10.7.5",\n      "resolved": "https://registry.npmjs.org/ip-address/-/ip-address-10.7.5.tgz",\n      "integrity": "sha512-t2v0rkILYv9WXmSL7TpAaU3HXgaFYOPUcH3QHgwQ++gpJuH3bqyMy4Fvt/DJCTKwzH3Cf+bAp5W/mFL39KPLzA==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 12"\n      }\n    },\n    "node_modules/ipaddr.js": {\n      "version": "1.9.1",\n      "resolved": "https://registry.npmjs.org/ipaddr.js/-/ipaddr.js-1.9.1.tgz",\n      "integrity": "sha512-0KI/607xoxSToH7GjN1FfSbLoU0+btTicjsQSWQlh/hZykN8KpmMf7uYwPW3R+akZ6R/w18ZlXSHBYXiYUPO3g==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.10"\n      }\n    },\n    "node_modules/is-promise": {\n      "version": "4.0.0",\n      "resolved": "https://registry.npmjs.org/is-promise/-/is-promise-4.0.0.tgz",\n      "integrity": "sha512-hvpoI6korhJMnej285dSg6nu1+e6uxs7zG3BYAm5byqDsgJNWwxzM6z6iZiAgQR4TJ30JmBTOwqZUw3WlyH3AQ==",\n      "license": "MIT"\n    },\n    "node_modules/math-intrinsics": {\n      "version": "1.1.0",\n      "resolved": "https://registry.npmjs.org/math-intrinsics/-/math-intrinsics-1.1.0.tgz",\n      "integrity": "sha512-/IXtbwEk5HTPyEwyKX6hGkYXxM9nbj64B+ilVJnC/R6B0pH5G4V3b0pVbL7DBj4tkhBAppbQUlf6F6Xl9LHu1g==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.4"\n      }\n    },\n    "node_modules/media-typer": {\n      "version": "1.1.1",\n      "resolved": "https://registry.npmjs.org/media-typer/-/media-typer-1.1.1.tgz",\n      "integrity": "sha512-yz3xRaG20c6/BOzvYoDaGtPmGscs7YivItZEEqe6GbwNfHuxu9YNmvnEkMzKldAGY4/80pRcQRZSEnhquk9XuQ==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.8"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/merge-descriptors": {\n      "version": "2.0.0",\n      "resolved": "https://registry.npmjs.org/merge-descriptors/-/merge-descriptors-2.0.0.tgz",\n      "integrity": "sha512-Snk314V5ayFLhp3fkUREub6WtjBfPdCPY1Ln8/8munuLuiYhsABgBVWsozAG+MWMbVEvcdcpbi9R7ww22l9Q3g==",\n      "license": "MIT",\n      "engines": {\n        "node": ">=18"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/sindresorhus"\n      }\n    },\n    "node_modules/methods": {\n      "version": "1.1.2",\n      "resolved": "https://registry.npmjs.org/methods/-/methods-1.1.2.tgz",\n      "integrity": "sha512-iclAHeNqNm68zFtnZ0e+1L2yUIdvzNoauKU4WBA3VvH/vPFieF7qfRlwUZU+DA9P9bPXIS90ulxoUoCH23sV2w==",\n      "dev": true,\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.6"\n      }\n    },\n    "node_modules/mime": {\n      "version": "2.6.0",\n      "resolved": "https://registry.npmjs.org/mime/-/mime-2.6.0.tgz",\n      "integrity": "sha512-USPkMeET31rOMiarsBNIHZKLGgvKc/LrjofAnBlOttf5ajRvqiRA8QsenbcooctK6d6Ts6aqZXBA+XbkKthiQg==",\n      "dev": true,\n      "license": "MIT",\n      "bin": {\n        "mime": "cli.js"\n      },\n      "engines": {\n        "node": ">=4.0.0"\n      }\n    },\n    "node_modules/mime-db": {\n      "version": "1.54.0",\n      "resolved": "https://registry.npmjs.org/mime-db/-/mime-db-1.54.0.tgz",\n      "integrity": "sha512-aU5EJuIN2WDemCcAp2vFBfp/m4EAhWJnUNSSw0ixs7/kXbd6Pg64EmwJkNdFhB8aWt1sH2CTXrLxo/iAGV3oPQ==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.6"\n      }\n    },\n    "node_modules/mime-types": {\n      "version": "3.0.2",\n      "resolved": "https://registry.npmjs.org/mime-types/-/mime-types-3.0.2.tgz",\n      "integrity": "sha512-Lbgzdk0h4juoQ9fCKXW4by0UJqj+nOOrI9MJ1sSj4nI8aI2eo1qmvQEie4VD1glsS250n15LsWsYtCugiStS5A==",\n      "license": "MIT",\n      "dependencies": {\n        "mime-db": "^1.54.0"\n      },\n      "engines": {\n        "node": ">=18"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/ms": {\n      "version": "2.1.3",\n      "resolved": "https://registry.npmjs.org/ms/-/ms-2.1.3.tgz",\n      "integrity": "sha512-6FlzubTLZG3J2a/NVCAleEhjzq5oxgHyaCU9yYXvcLsvoVaHJq/s5xXI6/XXP6tz7R9xAOtHnSO/tXtF3WRTlA==",\n      "license": "MIT"\n    },\n    "node_modules/negotiator": {\n      "version": "1.1.0",\n      "resolved": "https://registry.npmjs.org/negotiator/-/negotiator-1.1.0.tgz",\n      "integrity": "sha512-NMPBRMJgiQHjbd8phG3Vebdx4kZ1H121rbl5IkMqeOsahptB9BKo/d7oJ3zTXqTgagn2bWlNSXkh0QUGM31RYg==",\n      "license": "MIT",\n      "dependencies": {\n        "content-type": "^2.1.0"\n      },\n      "engines": {\n        "node": ">=18"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/node-addon-api": {\n      "version": "8.9.2",\n      "resolved": "https://registry.npmjs.org/node-addon-api/-/node-addon-api-8.9.2.tgz",\n      "integrity": "sha512-VijLXbi3UACN69I0JVXJsX4tjACjNoQDgv2gTF6sx2wWEi8tkSg2eX8p5gSIFi8z2+DL3oHmY6OyKce38SDolg==",\n      "license": "MIT",\n      "engines": {\n        "node": "^18 || ^20 || >= 21"\n      }\n    },\n    "node_modules/node-gyp-build": {\n      "version": "4.8.4",\n      "resolved": "https://registry.npmjs.org/node-gyp-build/-/node-gyp-build-4.8.4.tgz",\n      "integrity": "sha512-LA4ZjwlnUblHVgq0oBF3Jl/6h/Nvs5fzBLwdEF4nuxnFdsfajde4WfxtJr3CaiH+F6ewcIB/q4jQ4UzPyid+CQ==",\n      "license": "MIT",\n      "bin": {\n        "node-gyp-build": "bin.js",\n        "node-gyp-build-optional": "optional.js",\n        "node-gyp-build-test": "build-test.js"\n      }\n    },\n    "node_modules/object-inspect": {\n      "version": "1.13.4",\n      "resolved": "https://registry.npmjs.org/object-inspect/-/object-inspect-1.13.4.tgz",\n      "integrity": "sha512-W67iLl4J2EXEGTbfeHCffrjDfitvLANg0UlX3wFUUSTx92KXRFegMHUVgSqE+wvhAbi4WqjGg9czysTV2Epbew==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.4"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/on-finished": {\n      "version": "2.4.2",\n      "resolved": "https://registry.npmjs.org/on-finished/-/on-finished-2.4.2.tgz",\n      "integrity": "sha512-ATWUv387i+nLD49EiDoOft5scf32Vsdz3ktrQJG9bi7jRFmaXTssvyvj1EmeKVVgvesbqUtvQQvaS2TpTukAZQ==",\n      "license": "MIT",\n      "dependencies": {\n        "ee-first": "1.1.1"\n      },\n      "engines": {\n        "node": ">= 0.8"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/on-headers": {\n      "version": "1.1.0",\n      "resolved": "https://registry.npmjs.org/on-headers/-/on-headers-1.1.0.tgz",\n      "integrity": "sha512-737ZY3yNnXy37FHkQxPzt4UZ2UWPWiCZWLvFZ4fu5cueciegX0zGPnrlY6bwRg4FdQOe9YU8MkmJwGhoMybl8A==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.8"\n      }\n    },\n    "node_modules/once": {\n      "version": "1.4.0",\n      "resolved": "https://registry.npmjs.org/once/-/once-1.4.0.tgz",\n      "integrity": "sha512-lNaJgI+2Q5URQBkccEKHTQOPaXdUxnZZElQTZY0MFUAuaEqe1E+Nyvgdz/aIyNi6Z9MzO5dv1H8n58/GELp3+w==",\n      "license": "ISC",\n      "dependencies": {\n        "wrappy": "1"\n      }\n    },\n    "node_modules/parseurl": {\n      "version": "1.3.3",\n      "resolved": "https://registry.npmjs.org/parseurl/-/parseurl-1.3.3.tgz",\n      "integrity": "sha512-CiyeOxFT/JZyN5m0z9PfXw4SCBJ6Sygz1Dpl0wqjlhDEGGBP1GnsUVEL0p63hoG1fcj3fHynXi9NYO4nWOL+qQ==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.8"\n      }\n    },\n    "node_modules/path-to-regexp": {\n      "version": "8.4.2",\n      "resolved": "https://registry.npmjs.org/path-to-regexp/-/path-to-regexp-8.4.2.tgz",\n      "integrity": "sha512-qRcuIdP69NPm4qbACK+aDogI5CBDMi1jKe0ry5rSQJz8JVLsC7jV8XpiJjGRLLol3N+R5ihGYcrPLTno6pAdBA==",\n      "license": "MIT",\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/pg": {\n      "version": "8.23.1",\n      "resolved": "https://registry.npmjs.org/pg/-/pg-8.23.1.tgz",\n      "integrity": "sha512-aL96AHANtWjPLDOLqnhx+ngp9+UK7ETEU8VJrDCGvsSSi/mGLcWYsS6Herg7lmaBJe4uwrfqsa7gTEFaSizDoQ==",\n      "license": "MIT",\n      "dependencies": {\n        "pg-connection-string": "^2.14.1",\n        "pg-pool": "^3.14.0",\n        "pg-protocol": "^1.16.1",\n        "pg-types": "2.2.0",\n        "pgpass": "1.0.5"\n      },\n      "engines": {\n        "node": ">= 16.0.0"\n      },\n      "optionalDependencies": {\n        "pg-cloudflare": "^1.4.1"\n      },\n      "peerDependencies": {\n        "pg-native": ">=3.0.1"\n      },\n      "peerDependenciesMeta": {\n        "pg-native": {\n          "optional": true\n        }\n      }\n    },\n    "node_modules/pg-cloudflare": {\n      "version": "1.4.1",\n      "resolved": "https://registry.npmjs.org/pg-cloudflare/-/pg-cloudflare-1.4.1.tgz",\n      "integrity": "sha512-6PQbsFWZcp9EmJEwy5cGQ2La+AMWpP46lgbb8X+U/XsHIUweYDNCpeuKck5RxL2MdVFi7krbbEi5nX4Zh7JhrQ==",\n      "license": "MIT",\n      "optional": true\n    },\n    "node_modules/pg-connection-string": {\n      "version": "2.14.1",\n      "resolved": "https://registry.npmjs.org/pg-connection-string/-/pg-connection-string-2.14.1.tgz",\n      "integrity": "sha512-qR3kGNPBLpCNtz0evbKA0Y/MRFXwSSdT+pTJvYp/bXTcReZbvX1kzF0IyTc1QnxqF7AZbOeBhNL8R5mYQZV/MA==",\n      "license": "MIT"\n    },\n    "node_modules/pg-int8": {\n      "version": "1.0.1",\n      "resolved": "https://registry.npmjs.org/pg-int8/-/pg-int8-1.0.1.tgz",\n      "integrity": "sha512-WCtabS6t3c8SkpDBUlb1kjOs7l66xsGdKpIPZsg4wR+B3+u9UAum2odSsF9tnvxg80h4ZxLWMy4pRjOsFIqQpw==",\n      "license": "ISC",\n      "engines": {\n        "node": ">=4.0.0"\n      }\n    },\n    "node_modules/pg-pool": {\n      "version": "3.14.0",\n      "resolved": "https://registry.npmjs.org/pg-pool/-/pg-pool-3.14.0.tgz",\n      "integrity": "sha512-gKtPkFdQPU3DksooVLi9LsjZxrsBUZIpa+7aVx+LV5pNh0KzP4Zleud2po+ConrxbuXGBJ6Hfer6hdgpIBpBaw==",\n      "license": "MIT",\n      "peerDependencies": {\n        "pg": ">=8.0"\n      }\n    },\n    "node_modules/pg-protocol": {\n      "version": "1.16.1",\n      "resolved": "https://registry.npmjs.org/pg-protocol/-/pg-protocol-1.16.1.tgz",\n      "integrity": "sha512-p9VOFMiHB/ZbJATetbg+99PxssTVSQRnyuPSQ67mN1+1KBOjZaZ83ZQzltnxPhJwSsC3nwVjJ10DVJlerbFzLg==",\n      "license": "MIT"\n    },\n    "node_modules/pg-types": {\n      "version": "2.2.0",\n      "resolved": "https://registry.npmjs.org/pg-types/-/pg-types-2.2.0.tgz",\n      "integrity": "sha512-qTAAlrEsl8s4OiEQY69wDvcMIdQN6wdz5ojQiOy6YRMuynxenON0O5oCpJI6lshc6scgAY8qvJ2On/p+CXY0GA==",\n      "license": "MIT",\n      "dependencies": {\n        "pg-int8": "1.0.1",\n        "postgres-array": "~2.0.0",\n        "postgres-bytea": "~1.0.0",\n        "postgres-date": "~1.0.4",\n        "postgres-interval": "^1.1.0"\n      },\n      "engines": {\n        "node": ">=4"\n      }\n    },\n    "node_modules/pgpass": {\n      "version": "1.0.5",\n      "resolved": "https://registry.npmjs.org/pgpass/-/pgpass-1.0.5.tgz",\n      "integrity": "sha512-FdW9r/jQZhSeohs1Z3sI1yxFQNFvMcnmfuj4WBMUTxOrAyLMaTcE1aAMBiTlbMNaXvBCQuVi0R7hd8udDSP7ug==",\n      "license": "MIT",\n      "dependencies": {\n        "split2": "^4.1.0"\n      }\n    },\n    "node_modules/playwright": {\n      "version": "1.64.1",\n      "resolved": "https://registry.npmjs.org/playwright/-/playwright-1.64.1.tgz",\n      "integrity": "sha512-HCrVhHr5QQuwYoswEUGTb7gGp522yflbv/ST8nF4sFWGuLjQCt17Q/EubpGGSNKYn1tsTCPZxqHhHCfVURu7UA==",\n      "dev": true,\n      "license": "Apache-2.0",\n      "dependencies": {\n        "playwright-core": "1.64.1"\n      },\n      "bin": {\n        "playwright": "cli.js"\n      },\n      "engines": {\n        "node": ">=20"\n      }\n    },\n    "node_modules/playwright-core": {\n      "version": "1.64.1",\n      "resolved": "https://registry.npmjs.org/playwright-core/-/playwright-core-1.64.1.tgz",\n      "integrity": "sha512-BC4s8y6SEVA6Q1rSxZTto8hI1KUI3xXlHGZgvGqP4IqPdI/a6FX9H29IDNz7vKo9l21b6LfYosScPL6M3xxyDQ==",\n      "dev": true,\n      "license": "Apache-2.0",\n      "bin": {\n        "playwright-core": "cli.js"\n      },\n      "engines": {\n        "node": ">=20"\n      }\n    },\n    "node_modules/postgres-array": {\n      "version": "2.0.0",\n      "resolved": "https://registry.npmjs.org/postgres-array/-/postgres-array-2.0.0.tgz",\n      "integrity": "sha512-VpZrUqU5A69eQyW2c5CA1jtLecCsN2U/bD6VilrFDWq5+5UIEVO7nazS3TEcHf1zuPYO/sqGvUvW62g86RXZuA==",\n      "license": "MIT",\n      "engines": {\n        "node": ">=4"\n      }\n    },\n    "node_modules/postgres-bytea": {\n      "version": "1.0.1",\n      "resolved": "https://registry.npmjs.org/postgres-bytea/-/postgres-bytea-1.0.1.tgz",\n      "integrity": "sha512-5+5HqXnsZPE65IJZSMkZtURARZelel2oXUEO8rH83VS/hxH5vv1uHquPg5wZs8yMAfdv971IU+kcPUczi7NVBQ==",\n      "license": "MIT",\n      "engines": {\n        "node": ">=0.10.0"\n      }\n    },\n    "node_modules/postgres-date": {\n      "version": "1.0.7",\n      "resolved": "https://registry.npmjs.org/postgres-date/-/postgres-date-1.0.7.tgz",\n      "integrity": "sha512-suDmjLVQg78nMK2UZ454hAG+OAW+HQPZ6n++TNDUX+L0+uUlLywnoxJKDou51Zm+zTCjrCl0Nq6J9C5hP9vK/Q==",\n      "license": "MIT",\n      "engines": {\n        "node": ">=0.10.0"\n      }\n    },\n    "node_modules/postgres-interval": {\n      "version": "1.2.0",\n      "resolved": "https://registry.npmjs.org/postgres-interval/-/postgres-interval-1.2.0.tgz",\n      "integrity": "sha512-9ZhXKM/rw350N1ovuWHbGxnGh/SNJ4cnxHiM0rxE4VN41wsg8P8zWn9hv/buK00RP4WvlOyr/RBDiptyxVbkZQ==",\n      "license": "MIT",\n      "dependencies": {\n        "xtend": "^4.0.0"\n      },\n      "engines": {\n        "node": ">=0.10.0"\n      }\n    },\n    "node_modules/proxy-addr": {\n      "version": "2.0.8",\n      "resolved": "https://registry.npmjs.org/proxy-addr/-/proxy-addr-2.0.8.tgz",\n      "integrity": "sha512-5nnx0yGyVUcY6t9RnWcARWtwT9F1D8O9rt08htPvnd49W1IgZtmLkhu9WfMzQj1cFxjHIO6connUNVW5k7AVyQ==",\n      "license": "MIT",\n      "dependencies": {\n        "forwarded": "0.2.0",\n        "ipaddr.js": "1.9.1"\n      },\n      "engines": {\n        "node": ">= 0.10"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/qs": {\n      "version": "6.17.1",\n      "resolved": "https://registry.npmjs.org/qs/-/qs-6.17.1.tgz",\n      "integrity": "sha512-jd3COkaKVgGUW+ZHyEHCG9bH7RoaaiWuMgzsIBjUMVjLAaWGWpoUAVwljVvBHxRu/2qEHnadLGZrkutYUBPQJA==",\n      "license": "BSD-3-Clause",\n      "dependencies": {\n        "es-define-property": "^1.0.1",\n        "side-channel": "^1.1.1"\n      },\n      "engines": {\n        "node": ">=0.6"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/random-bytes": {\n      "version": "1.0.0",\n      "resolved": "https://registry.npmjs.org/random-bytes/-/random-bytes-1.0.0.tgz",\n      "integrity": "sha512-iv7LhNVO047HzYR3InF6pUcUsPQiHTM1Qal51DcGSuZFBil1aBBWG5eHPNek7bvILMaYJ/8RU1e8w1AMdHmLQQ==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.8"\n      }\n    },\n    "node_modules/range-parser": {\n      "version": "1.3.0",\n      "resolved": "https://registry.npmjs.org/range-parser/-/range-parser-1.3.0.tgz",\n      "integrity": "sha512-hek2mFQpPuI4E1BBKrSto+BU3e3x4xuarsbiwr3+lf7p44juvFMV0XFWQAP3xUyqXA4RrXLIoaSUGbSt056ZMw==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.6"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/raw-body": {\n      "version": "3.0.2",\n      "resolved": "https://registry.npmjs.org/raw-body/-/raw-body-3.0.2.tgz",\n      "integrity": "sha512-K5zQjDllxWkf7Z5xJdV0/B0WTNqx6vxG70zJE4N0kBs4LovmEYWJzQGxC9bS9RAKu3bgM40lrd5zoLJ12MQ5BA==",\n      "license": "MIT",\n      "dependencies": {\n        "bytes": "~3.1.2",\n        "http-errors": "~2.0.1",\n        "iconv-lite": "~0.7.0",\n        "unpipe": "~1.0.0"\n      },\n      "engines": {\n        "node": ">= 0.10"\n      }\n    },\n    "node_modules/router": {\n      "version": "2.2.0",\n      "resolved": "https://registry.npmjs.org/router/-/router-2.2.0.tgz",\n      "integrity": "sha512-nLTrUKm2UyiL7rlhapu/Zl45FwNgkZGaCpZbIHajDYgwlJCOzLSk+cIPAnsEqV955GjILJnKbdQC1nVPz+gAYQ==",\n      "license": "MIT",\n      "dependencies": {\n        "debug": "^4.4.0",\n        "depd": "^2.0.0",\n        "is-promise": "^4.0.0",\n        "parseurl": "^1.3.3",\n        "path-to-regexp": "^8.0.0"\n      },\n      "engines": {\n        "node": ">= 18"\n      }\n    },\n    "node_modules/safe-buffer": {\n      "version": "5.2.1",\n      "resolved": "https://registry.npmjs.org/safe-buffer/-/safe-buffer-5.2.1.tgz",\n      "integrity": "sha512-rp3So07KcdmmKbGvgaNxQSJr7bGVSVk5S9Eq1F+ppbRo70+YeaDxkw5Dd8NPN+GD6bjnYm2VuPuCXmpuYvmCXQ==",\n      "funding": [\n        {\n          "type": "github",\n          "url": "https://github.com/sponsors/feross"\n        },\n        {\n          "type": "patreon",\n          "url": "https://www.patreon.com/feross"\n        },\n        {\n          "type": "consulting",\n          "url": "https://feross.org/support"\n        }\n      ],\n      "license": "MIT"\n    },\n    "node_modules/safer-buffer": {\n      "version": "2.1.2",\n      "resolved": "https://registry.npmjs.org/safer-buffer/-/safer-buffer-2.1.2.tgz",\n      "integrity": "sha512-YZo3K82SD7Riyi0E1EQPojLz7kpepnSQI9IyPbHHg1XXXevb5dJI7tpyN2ADxGcQbHG7vcyRHk0cbwqcQriUtg==",\n      "license": "MIT"\n    },\n    "node_modules/send": {\n      "version": "1.2.1",\n      "resolved": "https://registry.npmjs.org/send/-/send-1.2.1.tgz",\n      "integrity": "sha512-1gnZf7DFcoIcajTjTwjwuDjzuz4PPcY2StKPlsGAQ1+YH20IRVrBaXSWmdjowTJ6u8Rc01PoYOGHXfP1mYcZNQ==",\n      "license": "MIT",\n      "dependencies": {\n        "debug": "^4.4.3",\n        "encodeurl": "^2.0.0",\n        "escape-html": "^1.0.3",\n        "etag": "^1.8.1",\n        "fresh": "^2.0.0",\n        "http-errors": "^2.0.1",\n        "mime-types": "^3.0.2",\n        "ms": "^2.1.3",\n        "on-finished": "^2.4.1",\n        "range-parser": "^1.2.1",\n        "statuses": "^2.0.2"\n      },\n      "engines": {\n        "node": ">= 18"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/serve-static": {\n      "version": "2.2.1",\n      "resolved": "https://registry.npmjs.org/serve-static/-/serve-static-2.2.1.tgz",\n      "integrity": "sha512-xRXBn0pPqQTVQiC8wyQrKs2MOlX24zQ0POGaj0kultvoOCstBQM5yvOhAVSUwOMjQtTvsPWoNCHfPGwaaQJhTw==",\n      "license": "MIT",\n      "dependencies": {\n        "encodeurl": "^2.0.0",\n        "escape-html": "^1.0.3",\n        "parseurl": "^1.3.3",\n        "send": "^1.2.0"\n      },\n      "engines": {\n        "node": ">= 18"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/setprototypeof": {\n      "version": "1.2.0",\n      "resolved": "https://registry.npmjs.org/setprototypeof/-/setprototypeof-1.2.0.tgz",\n      "integrity": "sha512-E5LDX7Wrp85Kil5bhZv46j8jOeboKq5JMmYM3gVGdGH8xFpPWXUMsNrlODCrkoxMEeNi/XZIwuRvY4XNwYMJpw==",\n      "license": "ISC"\n    },\n    "node_modules/side-channel": {\n      "version": "1.1.1",\n      "resolved": "https://registry.npmjs.org/side-channel/-/side-channel-1.1.1.tgz",\n      "integrity": "sha512-6x6dK6zJdpTzF4sQeNYxwtvBzf6Eg4GtlesS94HOvTudUeyK2WXAaIfmDgsyslYrRBeFIlsi54AYsFGUuhmvrQ==",\n      "license": "MIT",\n      "dependencies": {\n        "es-errors": "^1.3.0",\n        "object-inspect": "^1.13.4",\n        "side-channel-list": "^1.0.1",\n        "side-channel-map": "^1.0.1",\n        "side-channel-weakmap": "^1.0.2"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/side-channel-list": {\n      "version": "1.0.1",\n      "resolved": "https://registry.npmjs.org/side-channel-list/-/side-channel-list-1.0.1.tgz",\n      "integrity": "sha512-mjn/0bi/oUURjc5Xl7IaWi/OJJJumuoJFQJfDDyO46+hBWsfaVM65TBHq2eoZBhzl9EchxOijpkbRC8SVBQU0w==",\n      "license": "MIT",\n      "dependencies": {\n        "es-errors": "^1.3.0",\n        "object-inspect": "^1.13.4"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/side-channel-map": {\n      "version": "1.0.1",\n      "resolved": "https://registry.npmjs.org/side-channel-map/-/side-channel-map-1.0.1.tgz",\n      "integrity": "sha512-VCjCNfgMsby3tTdo02nbjtM/ewra6jPHmpThenkTYh8pG9ucZ/1P8So4u4FGBek/BjpOVsDCMoLA/iuBKIFXRA==",\n      "license": "MIT",\n      "dependencies": {\n        "call-bound": "^1.0.2",\n        "es-errors": "^1.3.0",\n        "get-intrinsic": "^1.2.5",\n        "object-inspect": "^1.13.3"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/side-channel-weakmap": {\n      "version": "1.0.2",\n      "resolved": "https://registry.npmjs.org/side-channel-weakmap/-/side-channel-weakmap-1.0.2.tgz",\n      "integrity": "sha512-WPS/HvHQTYnHisLo9McqBHOJk2FkHO/tlpvldyrnem4aeQp4hai3gythswg6p01oSoTl58rcpiFAjF2br2Ak2A==",\n      "license": "MIT",\n      "dependencies": {\n        "call-bound": "^1.0.2",\n        "es-errors": "^1.3.0",\n        "get-intrinsic": "^1.2.5",\n        "object-inspect": "^1.13.3",\n        "side-channel-map": "^1.0.1"\n      },\n      "engines": {\n        "node": ">= 0.4"\n      },\n      "funding": {\n        "url": "https://github.com/sponsors/ljharb"\n      }\n    },\n    "node_modules/split2": {\n      "version": "4.2.0",\n      "resolved": "https://registry.npmjs.org/split2/-/split2-4.2.0.tgz",\n      "integrity": "sha512-UcjcJOWknrNkF6PLX83qcHM6KHgVKNkV62Y8a5uYDVv9ydGQVwAHMKqHdJje1VTWpljG0WYpCDhrCdAOYH4TWg==",\n      "license": "ISC",\n      "engines": {\n        "node": ">= 10.x"\n      }\n    },\n    "node_modules/statuses": {\n      "version": "2.0.2",\n      "resolved": "https://registry.npmjs.org/statuses/-/statuses-2.0.2.tgz",\n      "integrity": "sha512-DvEy55V3DB7uknRo+4iOGT5fP1slR8wQohVdknigZPMpMstaKJQWhwiYBACJE3Ul2pTnATihhBYnRhZQHGBiRw==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.8"\n      }\n    },\n    "node_modules/superagent": {\n      "version": "10.4.1",\n      "resolved": "https://registry.npmjs.org/superagent/-/superagent-10.4.1.tgz",\n      "integrity": "sha512-PVMkMrhKrSTtFhUU8jiWuGh/gyRMKiyCTCmm0+qVzRNxlfntmRKJkDhlEXN62x3HIb33sQ4kmL8lcSdccWAchQ==",\n      "dev": true,\n      "license": "MIT",\n      "dependencies": {\n        "component-emitter": "^1.3.1",\n        "cookiejar": "^2.1.4",\n        "debug": "^4.3.7",\n        "fast-safe-stringify": "^2.1.1",\n        "form-data": "^4.0.5",\n        "formidable": "^3.5.4",\n        "methods": "^1.1.2",\n        "mime": "2.6.0",\n        "qs": "^6.14.1"\n      },\n      "engines": {\n        "node": ">=14.18.0"\n      }\n    },\n    "node_modules/supertest": {\n      "version": "7.3.1",\n      "resolved": "https://registry.npmjs.org/supertest/-/supertest-7.3.1.tgz",\n      "integrity": "sha512-vNaNCFoCR/edDbErQZp5KLNT8R4dSPHX7rlDLoE8hWLAm/878j6ShMbe8HK/E6RwwuhlSXVelXAIg9AxR5WWPw==",\n      "dev": true,\n      "license": "MIT",\n      "dependencies": {\n        "cookie-signature": "^1.2.2",\n        "methods": "^1.1.2",\n        "superagent": "^10.3.0"\n      },\n      "engines": {\n        "node": ">=14.18.0"\n      }\n    },\n    "node_modules/toidentifier": {\n      "version": "1.0.1",\n      "resolved": "https://registry.npmjs.org/toidentifier/-/toidentifier-1.0.1.tgz",\n      "integrity": "sha512-o5sSPKEkg/DIQNmH43V0/uerLrpzVedkUh8tGNvaeXpfpuwjKenlSox/2O/BTlZUtEe+JG7s5YhEz608PlAHRA==",\n      "license": "MIT",\n      "engines": {\n        "node": ">=0.6"\n      }\n    },\n    "node_modules/type-is": {\n      "version": "2.1.0",\n      "resolved": "https://registry.npmjs.org/type-is/-/type-is-2.1.0.tgz",\n      "integrity": "sha512-faYHw0anBbc/kWF3zFTEnxSFOAGUX9GFbOBthvDdLsIlEoWOFOtS0zgCiQYwIskL9iGXZL3kAXD8OoZ4GmMATA==",\n      "license": "MIT",\n      "dependencies": {\n        "content-type": "^2.0.0",\n        "media-typer": "^1.1.0",\n        "mime-types": "^3.0.0"\n      },\n      "engines": {\n        "node": ">= 18"\n      },\n      "funding": {\n        "type": "opencollective",\n        "url": "https://opencollective.com/express"\n      }\n    },\n    "node_modules/uid-safe": {\n      "version": "2.1.5",\n      "resolved": "https://registry.npmjs.org/uid-safe/-/uid-safe-2.1.5.tgz",\n      "integrity": "sha512-KPHm4VL5dDXKz01UuEd88Df+KzynaohSL9fBh096KWAxSKZQDI2uBrVqtvRM4rwrIrRRKsdLNML/lnaaVSRioA==",\n      "license": "MIT",\n      "dependencies": {\n        "random-bytes": "~1.0.0"\n      },\n      "engines": {\n        "node": ">= 0.8"\n      }\n    },\n    "node_modules/unpipe": {\n      "version": "1.0.0",\n      "resolved": "https://registry.npmjs.org/unpipe/-/unpipe-1.0.0.tgz",\n      "integrity": "sha512-pjy2bYhSsufwWlKwPc+l3cN7+wuJlK6uz0YdJEOlQDbl6jo/YlPi4mb8agUkVC8BF7V8NuzeyPNqRksA3hztKQ==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.8"\n      }\n    },\n    "node_modules/vary": {\n      "version": "1.1.2",\n      "resolved": "https://registry.npmjs.org/vary/-/vary-1.1.2.tgz",\n      "integrity": "sha512-BNGbWLfd0eUPabhkXUVm0j8uuvREyTh5ovRa/dyow/BqAbZJyC+5fU+IzQOzmAKzYqYRAISoRhdQr3eIZ/PXqg==",\n      "license": "MIT",\n      "engines": {\n        "node": ">= 0.8"\n      }\n    },\n    "node_modules/wrappy": {\n      "version": "1.0.2",\n      "resolved": "https://registry.npmjs.org/wrappy/-/wrappy-1.0.2.tgz",\n      "integrity": "sha512-l4Sp/DRseor9wL6EvV2+TuQn63dMkPjZ/sp9XkghTEbV9KlPS1xUsZ3u7/IQO4wxtcFB4bgpQPRcR3QCvezPcQ==",\n      "license": "ISC"\n    },\n    "node_modules/xtend": {\n      "version": "4.0.2",\n      "resolved": "https://registry.npmjs.org/xtend/-/xtend-4.0.2.tgz",\n      "integrity": "sha512-LKYU1iAXJXUgAXn9URjiu+MWhyUXHsvfp7mcuYm9dSUKK0/CjtrUwFAxD82/mCWbtLsGjFIad0wIsod4zrTAEQ==",\n      "license": "MIT",\n      "engines": {\n        "node": ">=0.4"\n      }\n    },\n    "node_modules/zod": {\n      "version": "4.6.7",\n      "resolved": "https://registry.npmjs.org/zod/-/zod-4.6.7.tgz",\n      "integrity": "sha512-g8W2D2kU6a8untc053fX1uVBKzM7yqAxW/3zwk83+6RyF2+SKOuV+c0wBDhUwzV1PaGapmZH+rmcUzPf+3CGwg==",\n      "license": "MIT",\n      "funding": {\n        "url": "https://github.com/sponsors/colinhacks"\n      }\n    }\n  }\n}\n'

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--output',default='zudo-smm-panel',help='new output directory')
 p.add_argument('--install',action='store_true',help='install Node dependencies')
 args=p.parse_args()
 root=Path(args.output).resolve()
 if root.exists() and any(root.iterdir()):
  p.error('Output directory is not empty; choose a new --output directory. No existing files were changed.')
 root.mkdir(parents=True,exist_ok=True)
 for name,body in FILES.items():
  dest=root/name; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_text(body.lstrip('\n'),encoding='utf-8')
 print(f'Created {len(FILES)} project files in {root}')
 if args.install:
  subprocess.run(['npm','ci' if (root/'package-lock.json').exists() else 'install'],cwd=root,check=True)
 print('Next: read README.md, configure environment variables, then npm start. Never commit .env.')
if __name__=='__main__':
 main()
