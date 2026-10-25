-- O4U backend, migration 0004: run expire_holds() every minute with pg_cron - and do NOTHING, harmlessly, where pg_cron
-- cannot run. Idempotent: running it again replaces the same two named jobs, it never adds copies.
--
-- No-op conditions (each prints a NOTICE and the migration still succeeds):
--   * pg_cron is not in pg_available_extensions (not installed on this server), or
--   * pg_cron is installed but not loaded (not in shared_preload_libraries), or
--   * creating the extension / scheduling fails for any other reason (a WARNING says why - read it).
-- Then use the documented fallback: backend/functions/expire-holds (Supabase Edge Function + any scheduler), see backend/README.md.
--
-- Jobs: 'o4u-expire-holds' every minute; 'o4u-cron-cleanup' daily, trims pg_cron's own run history to 7 days.
-- Remove:  select cron.unschedule('o4u-expire-holds');  select cron.unschedule('o4u-cron-cleanup');
do $$
begin
  if not exists (select 1 from pg_available_extensions where name = 'pg_cron') then
    raise notice 'o4u: pg_cron is not available on this server - expire_holds() is NOT scheduled here; use the Edge Function fallback';
    return;
  end if;
  if coalesce(current_setting('shared_preload_libraries', true), '') not like '%pg_cron%' then
    raise notice 'o4u: pg_cron is installed but not loaded (shared_preload_libraries) - expire_holds() is NOT scheduled here';
    return;
  end if;
  begin
    create extension if not exists pg_cron;
    perform cron.schedule('o4u-expire-holds', '* * * * *', 'select public.expire_holds()');
    perform cron.schedule('o4u-cron-cleanup', '17 3 * * *', $c$delete from cron.job_run_details where end_time < now() - interval '7 days'$c$);
    raise notice 'o4u: expire_holds() scheduled every minute (pg_cron job o4u-expire-holds)';
  exception when others then
    raise warning 'o4u: could not schedule expire_holds() with pg_cron (% / %) - use the Edge Function fallback', sqlstate, sqlerrm;
  end;
end $$;
