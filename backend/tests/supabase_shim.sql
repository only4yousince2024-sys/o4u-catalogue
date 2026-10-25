-- TEST ONLY. Stand-ins for what Supabase provides, so the real migrations can run on a plain local PostgreSQL.
-- Never part of a migration. In Supabase: roles and auth.uid() already exist and read the signed-in user's JWT.
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create schema auth;
create function auth.uid() returns uuid language sql stable as
  $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
grant usage on schema public, auth to anon, authenticated, service_role;
grant execute on function auth.uid() to anon, authenticated, service_role;
