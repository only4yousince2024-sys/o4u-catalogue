-- O4U backend, migration 0003: expire_holds() made safe for two schedulers at once, for one bad order, and for a stuck lock.
-- Replaces the function from 0001 with the same signature and return value. Idempotent.
--
-- What can go wrong with a scheduler, and what now happens:
--   two runs at once          -> each takes different overdue orders (FOR UPDATE SKIP LOCKED); an order is released exactly once.
--   one order that errors     -> only that order is skipped (its own sub-transaction); the rest still expire; the failure is
--                                recorded in expiry_failures; the next run tries it again.
--   a lock held by someone    -> lock_timeout (3 s) gives up on that order instead of hanging every later run; same retry.
--   a run that dies half-way  -> a run is one transaction: nothing half-done is ever committed; the next run starts clean.
-- In every case stock stays exactly as the ledger says; an unreleased hold is retried, never lost, and is shown by overdue_holds().

create table if not exists expiry_failures (
  id bigserial primary key,
  order_id uuid not null references orders(id),
  at timestamptz not null default now(),
  error text not null
);
create index if not exists expiry_failures_order_at on expiry_failures (order_id, at);
alter table expiry_failures enable row level security;
drop policy if exists mgr_read on expiry_failures;
create policy mgr_read on expiry_failures for select to authenticated using ((select current_role_rank()) >= 2);
grant select on expiry_failures to authenticated;

create or replace function expire_holds(p_now timestamptz default now()) returns int
language plpgsql security definer set search_path = public, auth set lock_timeout = '3s' as $$
declare o record; n int := 0;
begin
  for o in select id from orders
           where status = 'awaiting_payment' and hold_until <= p_now
             and not exists (select 1 from payments p where p.order_id = orders.id and p.kind = 'payment')
           order by hold_until, id limit 500
           for update skip locked
  loop
    begin                                   -- own sub-transaction: a failure here undoes only this order
      perform release_lines(o.id, 'hold expired');
      update orders set status = 'hold_expired', reserved = false, updated_at = now() where id = o.id and status = 'awaiting_payment';
      perform log_order(o.id, 'hold_expired', 'awaiting_payment', 'hold_expired', 'unpaid hold ran out; stock released');
      n := n + 1;
    exception when others then
      insert into expiry_failures (order_id, error)
      select o.id, sqlstate || ': ' || sqlerrm
      where not exists (select 1 from expiry_failures f where f.order_id = o.id and f.at > now() - interval '1 hour');
    end;
  end loop;
  return n;
end $$;

-- Holds that should already have been released (the scheduler is late, stuck or failing for that order). Manager and above.
create or replace function overdue_holds(p_grace_minutes int default 5)
returns table (order_id uuid, ref text, hold_until timestamptz, minutes_overdue int, last_error text)
language plpgsql stable security definer set search_path = public, auth as $$
begin
  perform require_role('manager');
  return query
    select o.id, o.ref, o.hold_until, (extract(epoch from (now() - o.hold_until)) / 60)::int,
           (select f.error from expiry_failures f where f.order_id = o.id order by f.at desc limit 1)
    from orders o
    where o.status = 'awaiting_payment' and o.hold_until < now() - make_interval(mins => p_grace_minutes)
      and not exists (select 1 from payments p where p.order_id = o.id and p.kind = 'payment')
    order by o.hold_until;
end $$;

-- the scheduler runs as the service role (or as postgres through pg_cron); never anon or authenticated
revoke all on function overdue_holds(int) from public, anon, authenticated;
grant execute on function expire_holds(timestamptz) to service_role;
grant execute on function overdue_holds(int) to authenticated;
