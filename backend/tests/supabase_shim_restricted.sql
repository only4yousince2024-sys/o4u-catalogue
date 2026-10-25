-- TEST ONLY. A closer imitation of a HOSTED Supabase project with the owner's chosen settings, for hosted_like_check.py:
--   * the migration runner is NOT a superuser (like Supabase's `postgres`): role supa_owner, BYPASSRLS, member of anon/authenticated/service_role,
--     cannot read superuser-only settings such as shared_preload_libraries;
--   * "Automatically expose new tables" DISABLED: no default grants to anon/authenticated/service_role on new tables/functions/sequences;
--   * "Automatic RLS" ENABLED: an event trigger switches row-level security on for every table created in public;
--   * the auth schema, roles and auth.uid() as in supabase_shim.sql.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticator') then create role authenticator login noinherit; end if;
  if not exists (select 1 from pg_roles where rolname = 'supa_owner') then create role supa_owner login createrole createdb bypassrls; end if;
end $$;
grant anon, authenticated, service_role to authenticator;
grant anon, authenticated, service_role to supa_owner;

create schema auth;
create table auth.users (
  id uuid primary key, email text, raw_app_meta_data jsonb not null default '{}',
  banned_until timestamptz, deleted_at timestamptz, created_at timestamptz not null default now()
);
create function auth.uid() returns uuid language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
                  (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'))::uuid $$;
create function auth.role() returns text language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim.role', true), ''), (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role'))::text $$;
create function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim', true), ''), nullif(current_setting('request.jwt.claims', true), ''))::jsonb $$;
grant usage on schema auth to anon, authenticated, service_role, supa_owner;
grant execute on function auth.uid(), auth.role(), auth.jwt() to anon, authenticated, service_role, supa_owner;
grant select, references on auth.users to supa_owner;
-- the dashboard / auth service can add users; give the runner the same for the seed's onboarding lookups
grant usage, create on schema public to supa_owner;
grant usage on schema public to anon, authenticated, service_role;

-- Automatic RLS: every table created in public gets row-level security switched on
create schema supa_internal;
create function supa_internal.rls_auto_enable() returns event_trigger language plpgsql security definer as $$
declare r record;
begin
  for r in select * from pg_event_trigger_ddl_commands() where command_tag in ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO') and object_type = 'table' loop
    if r.schema_name = 'public' then execute format('alter table %s enable row level security', r.object_identity); end if;
  end loop;
end $$;
create event trigger rls_auto_enable on ddl_command_end execute function supa_internal.rls_auto_enable();
-- (no `alter default privileges ... grant` lines: new objects are NOT exposed to the API roles automatically)
