CREATE TABLE users (
 id BIGSERIAL PRIMARY KEY, username VARCHAR(32) NOT NULL UNIQUE CHECK(username=lower(username)),
 password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','owner')),
 balance NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK(balance>=0), suspended BOOLEAN NOT NULL DEFAULT false,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
INSERT INTO settings(key,value) VALUES('profit_percentage','60');
CREATE TABLE services_cache (service_id TEXT PRIMARY KEY,payload JSONB NOT NULL,active BOOLEAN NOT NULL DEFAULT true,updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE orders (
 id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id), idempotency_key UUID NOT NULL,
 service_id TEXT NOT NULL,service_name TEXT NOT NULL,service_type TEXT NOT NULL,link TEXT NOT NULL,quantity BIGINT NOT NULL CHECK(quantity>0),
 provider_order_id TEXT UNIQUE,provider_cost NUMERIC(20,6) NOT NULL CHECK(provider_cost>=0),selling_price NUMERIC(20,2) NOT NULL CHECK(selling_price>=0),
 profit_percentage NUMERIC(10,4) NOT NULL,currency TEXT NOT NULL DEFAULT 'INR',status TEXT NOT NULL DEFAULT 'Submitting',
 refunded NUMERIC(20,2) NOT NULL DEFAULT 0 CHECK(refunded>=0 AND refunded<=selling_price),
 start_count TEXT,remains TEXT,provider_charge NUMERIC(20,6),provider_error TEXT,request_payload JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),UNIQUE(user_id,idempotency_key)
);
CREATE INDEX orders_user_created ON orders(user_id,created_at DESC);
CREATE TABLE deposits (
 id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),amount NUMERIC(20,2) NOT NULL CHECK(amount>0),
 utr VARCHAR(80) NOT NULL UNIQUE CHECK(utr=upper(utr)),status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
 reviewed_by BIGINT REFERENCES users(id),reviewed_at TIMESTAMPTZ,note TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE transactions (
 id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),amount NUMERIC(20,2) NOT NULL CHECK(amount<>0),
 balance_after NUMERIC(20,2) NOT NULL CHECK(balance_after>=0),type TEXT NOT NULL,reason TEXT NOT NULL,
 reference TEXT UNIQUE,created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX transactions_user_created ON transactions(user_id,created_at DESC);
CREATE TABLE admin_logs (id BIGSERIAL PRIMARY KEY,owner_id BIGINT NOT NULL REFERENCES users(id),action TEXT NOT NULL,target TEXT,details JSONB NOT NULL DEFAULT '{}',created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE sessions(sid VARCHAR NOT NULL PRIMARY KEY,sess JSON NOT NULL,expire TIMESTAMP(6) NOT NULL);
CREATE INDEX sessions_expire_idx ON sessions(expire);
CREATE TABLE tickets (id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),subject VARCHAR(180) NOT NULL,status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE ticket_messages (id BIGSERIAL PRIMARY KEY,ticket_id BIGINT NOT NULL REFERENCES tickets(id),user_id BIGINT NOT NULL REFERENCES users(id),body TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now());
