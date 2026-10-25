-- TEST ONLY. Stand-ins for what Supabase provides, so the real migrations can run on a plain local PostgreSQL.
-- Never part of a migration. In Supabase all of this already exists. The definitions below copy Supabase's behaviour
-- as closely as can be done without their image:
--   * auth.uid() reads the verified JWT claims PostgREST puts into the session: the JSON setting `request.jwt.claims`
--     (current) with the legacy `request.jwt.claim.sub` as fallback - the same coalesce Supabase's own function uses.
--   * auth.users with the columns the migrations rely on (id, email, banned_until, deleted_at).
--   * the roles anon / authenticated / service_role (+ `authenticator`, the login role PostgREST connects as and then
--     `SET LOCAL ROLE`s from), and Supabase's DEFAULT PRIVILEGES: every new table/function in public is granted to
--     anon/authenticated/service_role. The migrations must therefore revoke explicitly - exactly the real-world hazard.
-- roles are cluster-wide, so create them only once (several test databases share one cluster)
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticator') then create role authenticator login noinherit; end if;
end $$;
grant anon, authenticated, service_role to authenticator;

create schema auth;
create table auth.users (
  id uuid primary key,
  email text,
  raw_app_meta_data jsonb not null default '{}',
  banned_until timestamptz,
  deleted_at timestamptz,
  created_at timestamptz not null default now()
);
create function auth.uid() returns uuid language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
                  (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'))::uuid $$;
create function auth.role() returns text language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim.role', true), ''),
                  (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role'))::text $$;
create function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim', true), ''), nullif(current_setting('request.jwt.claims', true), ''))::jsonb $$;

grant usage on schema public, auth to anon, authenticated, service_role;
grant execute on function auth.uid(), auth.role(), auth.jwt() to anon, authenticated, service_role;

alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public grant all on functions to anon, authenticated, service_role;
