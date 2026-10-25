-- O4U backend, migration 0005: server-side order-reference check, per-phone rate limiting, and the owner-visible
-- "stock cannot be trusted" flag. Idempotent.

-- ───────────────────────── 1. order-reference check digits ─────────────────────────
-- Exact port of the website's o4uCheck() (website/index.html), which is shared with Stockroom. Test vector:
--   o4u_check('W1410-K7M3', '[["14602b-purple-floral","M",1],["770221-jet-black","L",2]]') = 'ZP'
-- base = 'W<DDMM>-<4 chars>'; items = [[productId, size, qty], ...] IN THE ORDER OF THE BAG LINES (the order of the ITEM
-- lines in the WhatsApp block). FNV-1a (32 bit) over the code points of  BASE|id,SIZE,qty;id,SIZE,qty  then two base-31 digits.
create or replace function o4u_check(p_base text, p_items jsonb) returns text
language plpgsql immutable set search_path = pg_catalog as $$
declare
  alpha constant text := '23456789ABCDEFGHJKMNPQRSTUVWXYZ';
  s text; h bigint := 2166136261; i int; parts text[] := '{}'; e jsonb; z text;
begin
  for e in select value from jsonb_array_elements(p_items) with ordinality t(value, n) order by n loop
    z := upper(regexp_replace(btrim(e->>1), '\s+', '', 'g'));
    z := case z when '2XL' then 'XXL' when 'FREESIZE' then 'FREE' else z end;
    parts := parts || (lower(btrim(e->>0)) || ',' || z || ',' || ((e->>2)::numeric)::text);
  end loop;
  s := upper(p_base) || '|' || array_to_string(parts, ';');
  for i in 1 .. char_length(s) loop
    h := (((h # ascii(substr(s, i, 1))::bigint) * 16777619) & 4294967295);
  end loop;
  return substr(alpha, (h % 31)::int + 1, 1) || substr(alpha, ((h / 31) % 31)::int + 1, 1);
end $$;

-- ───────────────────────── 2. rate limiting settings ─────────────────────────
insert into app_settings (key, value) values ('rate_phone_per_hour', 5), ('rate_phone_per_day', 15), ('rate_all_per_hour', 300)
on conflict (key) do nothing;
create index if not exists orders_phone_created on orders (phone, created_at);
create index if not exists orders_created on orders (created_at);

-- place_order_request = 0001's function plus: (a) the check digits must match the lines sent, (b) rate limits.
-- Limits count REQUESTS ALREADY STORED for the phone (orders.created_at): no extra table, replays (same idempotency key)
-- return the stored answer and are never counted, and a refused request leaves nothing behind. A per-phone advisory lock
-- makes the count race-free, so ten simultaneous requests from one phone still admit exactly the allowed number.
create or replace function place_order_request(p_idem_key text, p_ref text, p_name text, p_phone text,
                                               p_address text, p_landmark text, p_lines jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare prev jsonb; o_id uuid; total int := 0; l record; v record; res jsonb; nlines int;
begin
  prev := idem_begin(p_idem_key, 'place_order_request'); if prev is not null then return prev; end if;
  if coalesce(trim(p_name),'') = '' or coalesce(trim(p_address),'') = '' then raise exception 'name and address are required'; end if;
  if p_phone !~ '^[0-9]{10}$' then raise exception 'phone must be 10 digits'; end if;
  if jsonb_typeof(p_lines) <> 'array' then raise exception 'lines must be a list'; end if;
  nlines := jsonb_array_length(p_lines);
  if nlines < 1 or nlines > setting('max_lines') then raise exception 'between 1 and % lines allowed', setting('max_lines'); end if;
  if p_ref !~ '^W[0-9]{4}-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{2}$' then raise exception 'bad order reference'; end if;
  begin
    if right(p_ref, 2) <> o4u_check(left(p_ref, 10),
         (select coalesce(jsonb_agg(jsonb_build_array(e->>'product_id', e->>'size', e->>'qty') order by n), '[]'::jsonb)
          from jsonb_array_elements(p_lines) with ordinality t(e, n))) then
      raise exception 'order reference check digits do not match the items' using errcode = 'P0001';
    end if;
  exception when invalid_text_representation or numeric_value_out_of_range or null_value_not_allowed or invalid_parameter_value then
    raise exception 'order reference check digits do not match the items' using errcode = 'P0001';
  end;

  perform pg_advisory_xact_lock(hashtextextended('o4u-order-phone:' || p_phone, 0));
  if (select count(*) from orders where phone = p_phone and created_at > now() - interval '1 hour') >= setting('rate_phone_per_hour')
     or (select count(*) from orders where phone = p_phone and created_at > now() - interval '1 day') >= setting('rate_phone_per_day') then
    raise exception 'too many order requests from this phone number - please wait a while or message the shop on WhatsApp' using errcode = 'P0429';
  end if;
  if (select count(*) from orders where created_at > now() - interval '1 hour') >= setting('rate_all_per_hour') then
    raise exception 'the shop is receiving a lot of requests right now - please try again shortly' using errcode = 'P0429';
  end if;

  if exists (select 1 from orders where ref = p_ref) then raise exception 'order reference already used'; end if;

  insert into orders (ref, source, customer_name, phone, address, landmark, items_paise)
  values (p_ref, 'website', trim(p_name), p_phone, trim(p_address), coalesce(trim(p_landmark),''), 1) returning id into o_id;   -- items_paise fixed below
  for l in select (e->>'product_id') as product_id, (e->>'size') as size, (e->>'qty')::int as qty from jsonb_array_elements(p_lines) e loop
    if l.qty is null or l.qty < 1 or l.qty > setting('max_qty_per_line') then raise exception 'quantity must be 1 to %', setting('max_qty_per_line'); end if;
    select vr.id, coalesce(vr.price_paise, p.price_paise) as unit into v from variants vr join products p on p.id = vr.product_id
      where vr.product_id = l.product_id and vr.size = l.size and p.published;
    if not found then raise exception 'item not available on the website: % %', l.product_id, l.size; end if;
    insert into order_lines (order_id, variant_id, qty, unit_paise) values (o_id, v.id, l.qty, v.unit);   -- duplicate variant → primary key error
    total := total + l.qty * v.unit;
  end loop;
  update orders set items_paise = total where id = o_id;
  perform log_order(o_id, 'place_order_request', null, 'request', 'website order request');
  res := jsonb_build_object('order_id', o_id, 'ref', p_ref, 'status', 'request', 'items_total_paise', total);
  return idem_end(p_idem_key, res);
end $$;
grant execute on function place_order_request(text,text,text,text,text,text,jsonb) to anon, authenticated;

-- ───────────────────────── 3. "stock cannot be trusted" flag ─────────────────────────
-- Derived from the shop app's heartbeat. While the shop app is silent (or the offline switch is on) every size already reads
-- "check" on the website. After it comes back, the gap is kept as an outage until a manager reconciles (counts the rack /
-- checks orders taken meanwhile) and records it. Stockroom shows stock_trust_status() as a banner.
create table if not exists store_outages (
  id bigserial primary key,
  kind text not null check (kind in ('heartbeat_gap','manual_switch')),
  started_at timestamptz not null,
  ended_at timestamptz,                        -- null while an offline switch is still on
  reconciled_at timestamptz, reconciled_by text, note text
);
alter table store_outages enable row level security;
drop policy if exists staff_read on store_outages;
create policy staff_read on store_outages for select to authenticated using ((select current_role_rank()) >= 1);
grant select on store_outages to authenticated;

create or replace function store_ping() returns void language plpgsql security definer set search_path = public, auth as $$
declare prev timestamptz;
begin
  perform require_role('staff');
  select last_heartbeat into prev from store_status where id = 1 for update;
  if prev is not null and prev < now() - make_interval(mins => setting('heartbeat_stale_minutes')) then
    insert into store_outages (kind, started_at, ended_at) values ('heartbeat_gap', prev, now());   -- the shop app was silent from prev until now
  end if;
  update store_status set last_heartbeat = now() where id = 1;
end $$;

create or replace function set_offline_switch(p_offline boolean, p_note text default '') returns void
language plpgsql security definer set search_path = public, auth as $$
declare was boolean;
begin
  perform require_role('manager');
  select offline_switch into was from store_status where id = 1 for update;
  if p_offline and not was then
    insert into store_outages (kind, started_at, note) values ('manual_switch', now(), p_note);
  elsif not p_offline and was then
    update store_outages set ended_at = now() where kind = 'manual_switch' and ended_at is null;
  end if;
  update store_status set offline_switch = p_offline, note = p_note where id = 1;
end $$;

create or replace function stock_trust_status() returns jsonb
language plpgsql stable security definer set search_path = public, auth as $$
declare st store_status; fresh boolean; unrec int; since timestamptz; reasons text[] := '{}'; warns text[] := '{}'; od int; ef int;
begin
  perform require_role('staff');
  select * into st from store_status where id = 1;
  fresh := st.last_heartbeat is not null and st.last_heartbeat > now() - make_interval(mins => setting('heartbeat_stale_minutes'));
  select count(*), min(started_at) into unrec, since from store_outages where reconciled_at is null and (ended_at is not null or kind = 'manual_switch');
  if st.offline_switch then reasons := array_append(reasons, 'offline switch is on'); end if;
  if not fresh then reasons := array_append(reasons, case when st.last_heartbeat is null then 'the shop app has never reported' else 'the shop app has not reported recently' end); end if;
  if unrec > 0 and fresh and not st.offline_switch then reasons := array_append(reasons, format('%s outage(s) not reconciled yet', unrec)); end if;
  select count(*) into od from orders o where o.status = 'awaiting_payment' and o.hold_until < now() - interval '5 minutes'
     and not exists (select 1 from payments p where p.order_id = o.id and p.kind = 'payment');
  select count(*) into ef from expiry_failures where at > now() - interval '1 hour';
  if od > 0 then warns := array_append(warns, format('%s hold(s) overdue for release', od)); end if;
  if ef > 0 then warns := array_append(warns, format('%s expiry failure(s) in the last hour', ef)); end if;
  return jsonb_build_object('trusted', cardinality(reasons) = 0, 'reasons', to_jsonb(reasons), 'warnings', to_jsonb(warns),
    'last_heartbeat', st.last_heartbeat, 'offline_switch', st.offline_switch,
    'unreconciled_outages', unrec, 'oldest_unreconciled_since', since, 'overdue_holds', od, 'expiry_failures_last_hour', ef);
end $$;

-- A manager says: I checked the rack and the orders taken during the outage. Not possible while the shop app is still silent.
create or replace function reconcile_outages(p_idem_key text, p_note text) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; st store_status; n int; res jsonb;
begin
  perform require_role('manager');
  prev := idem_begin(p_idem_key, 'reconcile_outages'); if prev is not null then return prev; end if;
  if length(coalesce(trim(p_note), '')) < 3 then raise exception 'say what you checked (a short note is required)'; end if;
  select * into st from store_status where id = 1;
  if st.offline_switch or st.last_heartbeat is null or st.last_heartbeat <= now() - make_interval(mins => setting('heartbeat_stale_minutes')) then
    raise exception 'the shop app is not reporting yet: reconcile after it is back online';
  end if;
  update store_outages set reconciled_at = now(), reconciled_by = actor_name(), note = trim(p_note)
   where reconciled_at is null and ended_at is not null;
  get diagnostics n = row_count;
  res := jsonb_build_object('reconciled', n);
  return idem_end(p_idem_key, res);
end $$;

revoke all on function stock_trust_status(), reconcile_outages(text,text), o4u_check(text,jsonb) from public, anon, authenticated;
grant execute on function stock_trust_status(), store_ping(), set_offline_switch(boolean,text) to authenticated;
grant execute on function reconcile_outages(text,text) to authenticated;
