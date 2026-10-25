-- O4U backend: READ-ONLY pre-flight for a hosted Supabase project. Changes nothing. Run it BEFORE migration 0001 and send me the result grid(s).
-- (If the editor shows only the last grid, run the numbered queries one at a time.)

-- 1. which role is the SQL editor using, and what is this server?
select current_user as running_as, session_user, split_part(version(), ',', 1) as server;

-- 2. the public schema should be empty on a new project
select count(*) as tables_in_public from pg_tables where schemaname = 'public';

-- 3. role attributes (is the runner a superuser? can it bypass row-level security? can it read server settings?)
select r.rolname, r.rolsuper, r.rolbypassrls, r.rolcreaterole,
       case when r.rolname = 'postgres' then pg_has_role('postgres', 'pg_read_all_settings', 'member') end as postgres_reads_all_settings,
       case when r.rolname = 'postgres' then has_table_privilege('postgres', 'auth.users', 'references') end as postgres_can_reference_auth_users
from pg_roles r where r.rolname in ('postgres', 'anon', 'authenticated', 'service_role', 'authenticator', 'supabase_admin') order by r.rolname;

-- 4. extensions we care about, and where they live
select e.extname, e.extversion, n.nspname as schema from pg_extension e join pg_namespace n on n.oid = e.extnamespace
where e.extname in ('pg_cron', 'pg_net', 'pgcrypto', 'pg_stat_statements') order by 1;

-- 5. the automatic-RLS event trigger and any other event triggers
select evtname, evtevent, evtenabled from pg_event_trigger order by 1;

-- 6. default privileges: with "automatically expose new tables" OFF, nothing should be granted to anon / authenticated / service_role
select defaclrole::regrole as for_role, defaclnamespace::regnamespace as in_schema, defaclobjtype as object_type, defaclacl::text as default_grants
from pg_default_acl order by 1, 3;

-- 7. is the server setting visible to this role? (0 rows = not visible; migration 0004 handles that case)
select name, setting from pg_settings where name = 'shared_preload_libraries';

-- 8. scheduled jobs (should be none yet)
select count(*) as cron_jobs from cron.job;
