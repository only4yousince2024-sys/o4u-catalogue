-- O4U backend, migration 0002: real Supabase Auth. Keeps 0001 untouched; safe to re-run (idempotent).
-- Needs Supabase's `auth` schema (auth.uid(), auth.users). Development only; nothing here is applied to a real project
-- without the owner's approval.
--
-- How identity works on Supabase: the website/Stockroom signs a person in with Supabase Auth and sends the access token
-- (a JWT). PostgREST verifies it and, per request, runs  SET LOCAL ROLE authenticated  +  set_config('request.jwt.claims', <json>).
-- auth.uid() is the JWT's `sub` = auth.users.id. `staff.user_id` is that same id, so being "on the staff list" is a row
-- here keyed by the auth user id - never an email or a claim the user could edit (we do NOT trust user_metadata).

-- ───────────────────────── default privileges: new objects are private ─────────────────────────
-- Supabase grants every NEW table/function in `public` to anon + authenticated by default. 0001 revoked only what existed
-- then, so without this every later table would silently be reachable (RLS would be the only guard). From here on a new
-- object is closed until a migration grants it explicitly.
alter default privileges in schema public revoke all on tables    from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke all on functions from anon, authenticated;
-- (Postgres also gives every new function EXECUTE to PUBLIC, and a schema-level default cannot take that away, so each
--  migration that adds a function revokes it from PUBLIC/anon/authenticated by name and grants only what is intended.
--  The privilege audit in backend/tests fails if any function or table is ever reachable that is not on the allowlist.)

-- 0001 revoked table and function access but not SEQUENCE access, which Supabase's default privileges had already granted
-- to anon/authenticated (anyone could have burned receipt numbers with nextval). Close them.
revoke all on all sequences in schema public from public, anon, authenticated;

-- ───────────────────────── staff keyed by the auth user ─────────────────────────
alter table staff add column if not exists created_at timestamptz not null default now();

do $$ begin
  if to_regclass('auth.users') is null then
    raise exception 'migration 0002 needs the Supabase auth schema (auth.users)';
  end if;
  if not exists (select 1 from pg_constraint where conname = 'staff_user_id_auth_fkey' and conrelid = 'public.staff'::regclass) then
    -- a staff row can only exist for a real sign-in account; deleting the account removes the staff row
    alter table staff add constraint staff_user_id_auth_fkey foreign key (user_id) references auth.users(id) on delete cascade;
  end if;
end $$;

-- A person counts as staff only while: their staff row is active AND their auth account is not deleted or banned.
-- A banned/deleted account therefore loses database access at once, even if a still-valid access token is replayed.
create or replace function current_role_rank() returns int
language sql stable security definer set search_path = public, auth as $$
  select case s.role when 'owner' then 3 when 'manager' then 2 else 1 end
  from staff s
  where s.user_id = auth.uid() and s.active
    and not exists (select 1 from auth.users u where u.id = s.user_id and (u.deleted_at is not null or u.banned_until > now()))
$$;

-- Who is acting, for the audit trail: the staff name; 'system' when there is no signed-in user (scheduler, service role);
-- 'unregistered user' for someone signed in who is not on the staff list.
create or replace function actor_name() returns text
language sql stable security definer set search_path = public, auth as $$
  select coalesce((select s.name from staff s where s.user_id = auth.uid() and s.active),
                  case when auth.uid() is null then 'system' else 'unregistered user' end)
$$;

-- Row-level security: wrap the role lookup in a sub-select so Postgres evaluates it once per query, not once per row
-- (Supabase's own performance guidance). Same rules as 0001.
drop policy if exists staff_read on products;          create policy staff_read on products          for select to authenticated using ((select current_role_rank()) >= 1);
drop policy if exists staff_read on variants;          create policy staff_read on variants          for select to authenticated using ((select current_role_rank()) >= 1);
drop policy if exists staff_read on stock_levels;      create policy staff_read on stock_levels      for select to authenticated using ((select current_role_rank()) >= 1);
drop policy if exists staff_read on stock_events;      create policy staff_read on stock_events      for select to authenticated using ((select current_role_rank()) >= 1);
drop policy if exists staff_read on orders;            create policy staff_read on orders            for select to authenticated using ((select current_role_rank()) >= 1);
drop policy if exists staff_read on order_lines;       create policy staff_read on order_lines       for select to authenticated using ((select current_role_rank()) >= 1);
drop policy if exists staff_read on order_events;      create policy staff_read on order_events      for select to authenticated using ((select current_role_rank()) >= 1);
drop policy if exists staff_read on order_transitions; create policy staff_read on order_transitions for select to authenticated using ((select current_role_rank()) >= 1);
drop policy if exists staff_read on payment_reports;   create policy staff_read on payment_reports   for select to authenticated using ((select current_role_rank()) >= 1);
drop policy if exists staff_read on store_status;      create policy staff_read on store_status      for select to authenticated using ((select current_role_rank()) >= 1);
drop policy if exists mgr_read   on refunds;           create policy mgr_read   on refunds           for select to authenticated using ((select current_role_rank()) >= 2);
drop policy if exists mgr_read   on payments;          create policy mgr_read   on payments          for select to authenticated using ((select current_role_rank()) >= 2);
drop policy if exists mgr_read   on sales;             create policy mgr_read   on sales             for select to authenticated using ((select current_role_rank()) >= 2);
drop policy if exists mgr_read   on sale_lines;        create policy mgr_read   on sale_lines        for select to authenticated using ((select current_role_rank()) >= 2);
drop policy if exists self_read  on staff;             create policy self_read  on staff             for select to authenticated using (user_id = (select auth.uid()));

-- ───────────────────────── never lock the shop out ─────────────────────────
-- The last active owner cannot be demoted, deactivated or deleted (including by deleting their auth account).
create or replace function keep_one_owner() returns trigger language plpgsql as $$
begin
  if old.role = 'owner' and old.active and (tg_op = 'DELETE' or new.role <> 'owner' or not new.active)
     and not exists (select 1 from staff s where s.role = 'owner' and s.active and s.user_id <> old.user_id) then
    raise exception 'there must always be one active owner: add another owner first' using errcode = 'P0001';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end $$;
drop trigger if exists staff_keep_one_owner on staff;
create trigger staff_keep_one_owner before update or delete on staff for each row execute function keep_one_owner();

-- ───────────────────────── onboarding (run by the owner in the Supabase SQL editor, or with the service role) ─────────────────────────
-- Staff are created in Supabase Auth first (Dashboard > Authentication > Add user / invite). These functions then put
-- that account on the staff list with a role. Not granted to anon/authenticated: a signed-in user cannot promote anyone.
create or replace function onboard_staff(p_user_id uuid, p_name text, p_role text) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
begin
  if coalesce(trim(p_name), '') = '' then raise exception 'a display name is required'; end if;
  if p_role not in ('owner','manager','staff') then raise exception 'role must be owner, manager or staff'; end if;
  if not exists (select 1 from auth.users where id = p_user_id and deleted_at is null) then
    raise exception 'no sign-in account with that id: create the user in Supabase Auth first';
  end if;
  insert into staff (user_id, name, role, active) values (p_user_id, trim(p_name), p_role, true)
  on conflict (user_id) do update set name = excluded.name, role = excluded.role, active = true;
  return jsonb_build_object('user_id', p_user_id, 'name', trim(p_name), 'role', p_role);
end $$;

-- Same, found by the e-mail the account was created with (typed at run time; no address is ever stored in these files).
create or replace function onboard_staff_by_email(p_email text, p_name text, p_role text) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare ids uuid[];
begin
  select array_agg(id) into ids from auth.users where lower(email) = lower(trim(p_email)) and deleted_at is null;
  if ids is null then raise exception 'no sign-in account with that e-mail: create the user in Supabase Auth first'; end if;
  if array_length(ids, 1) > 1 then raise exception 'more than one account has that e-mail: use onboard_staff(user_id, ...)'; end if;
  return onboard_staff(ids[1], p_name, p_role);
end $$;

-- Switch a person off without deleting their history. Their audit rows keep their name.
create or replace function deactivate_staff(p_user_id uuid) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
begin
  update staff set active = false where user_id = p_user_id;
  if not found then raise exception 'that person is not on the staff list'; end if;
  return jsonb_build_object('user_id', p_user_id, 'active', false);
end $$;

revoke all on function keep_one_owner(), onboard_staff(uuid,text,text), onboard_staff_by_email(text,text,text), deactivate_staff(uuid) from public, anon, authenticated;
grant execute on function onboard_staff(uuid,text,text), onboard_staff_by_email(text,text,text), deactivate_staff(uuid) to service_role;
