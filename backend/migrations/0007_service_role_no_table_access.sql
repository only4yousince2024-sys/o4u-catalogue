-- O4U backend, migration 0007: the service role keeps NO direct table privileges. Idempotent. Development only until the owner approves otherwise.
--
-- Found on the real hosted project (preflight, 25 Oct 2026): even with "automatically expose new tables" switched OFF, every table the SQL
-- editor's `postgres` role creates is granted TRUNCATE, REFERENCES, TRIGGER (and MAINTAIN on Postgres 17) to anon, authenticated AND
-- service_role by default. 0001 and 0002 already close that for anon and authenticated. The service role (a server-side key, used by an
-- Edge Function or the importer) was left with it: TRUNCATE skips row-level triggers, so it could have emptied the append-only
-- stock ledger and audit tables without a trace. Everything the service role legitimately does goes through SECURITY DEFINER functions
-- (expire_holds, onboard_staff, import_opening_balance), which need no table privileges.
revoke all on all tables    in schema public from service_role;
revoke all on all sequences in schema public from service_role;
alter default privileges in schema public revoke all on tables    from service_role;
alter default privileges in schema public revoke all on sequences from service_role;
