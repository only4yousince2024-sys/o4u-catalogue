-- O4U backend, migration 0006: constraints found in the real Stockroom backup (25 Oct 2026). Idempotent. Development only.
--   1. Barcodes are NOT unique per variant: one manufacturer barcode is printed on several colours of one article.
--   2. Opening stock must enter the ledger as an opening balance - never as invented receipts, sales or movements.
--   3. Quantities that disagree between two sources are imported but flagged "count pending" until a person counts them.
-- Nothing here changes a number: it only adds structure, refuses to guess, and keeps disputed stock out of the website.

-- ───────────────────────── 1. shared barcodes ─────────────────────────
create table if not exists variant_barcodes (
  barcode text not null check (length(barcode) between 3 and 64 and barcode !~ '\s'),
  variant_id uuid not null references variants(id) on delete restrict,
  primary key (barcode, variant_id)
);
create index if not exists variant_barcodes_variant on variant_barcodes (variant_id);
insert into variant_barcodes (barcode, variant_id) select barcode, id from variants where barcode is not null on conflict do nothing;
alter table variants drop constraint if exists variants_barcode_key;       -- many variants may now carry the same printed barcode

-- variants.barcode stays as the legacy "main printed barcode" column; variant_barcodes is what scanning uses
create or replace function variants_barcode_sync() returns trigger language plpgsql security definer set search_path = public as $$
begin
  if new.barcode is not null then insert into variant_barcodes (barcode, variant_id) values (new.barcode, new.id) on conflict do nothing; end if;
  return new;
end $$;
drop trigger if exists variants_barcode_sync on variants;
create trigger variants_barcode_sync after insert or update of barcode on variants for each row execute function variants_barcode_sync();

alter table variant_barcodes enable row level security;
drop policy if exists staff_read on variant_barcodes;
create policy staff_read on variant_barcodes for select to authenticated using ((select current_role_rank()) >= 1);
grant select on variant_barcodes to authenticated;

-- ───────────────────────── 2 + 3. opening balance and count-pending ─────────────────────────
alter table stock_events drop constraint if exists stock_events_kind_check;
alter table stock_events add constraint stock_events_kind_check
  check (kind in ('receive','adjust','recount','reserve','release','dispatch','sale','return_in','opening_balance'));

alter table stock_levels add column if not exists count_pending boolean not null default false;
alter table stock_levels add column if not exists count_pending_reason text;

insert into app_settings (key, value) values ('pending_blocks_counter_sales', 0) on conflict (key) do nothing;   -- 1 = the cashier cannot sell uncounted items

-- the website never shows an uncounted size as available: it reads "check"
create or replace function get_availability(p_product_ids text[] default null)
returns table (product_id text, size text, state text, n int, as_of timestamptz)
language plpgsql stable security definer set search_path = public as $$
declare st store_status; online boolean;
begin
  select * into st from store_status where id = 1;
  online := not st.offline_switch and st.last_heartbeat is not null
            and st.last_heartbeat > now() - make_interval(mins => setting('heartbeat_stale_minutes'));
  return query
    select v.product_id, v.size,
      case when not online or sl.count_pending then 'check'
           when sl.on_hand - sl.reserved >= 3 then 'available'
           when sl.on_hand - sl.reserved > 0 then 'low' else 'ask' end,
      case when not online or sl.count_pending then null when sl.on_hand - sl.reserved between 1 and 2 then sl.on_hand - sl.reserved
           when sl.on_hand - sl.reserved <= 0 then 0 else null end,
      now()
    from variants v join products p on p.id = v.product_id join stock_levels sl on sl.variant_id = v.id
    where p.published and (p_product_ids is null or v.product_id = any(p_product_ids))
    order by v.product_id, v.size;
end $$;

-- a website hold cannot be placed on stock nobody has counted
create or replace function reserve_lines(p_order uuid) returns void
language plpgsql security definer set search_path = public as $$
declare l record;
begin
  perform lock_stock_rows(array(select variant_id from order_lines where order_id = p_order));
  for l in select ol.variant_id, ol.qty, sl.on_hand - sl.reserved as free, sl.count_pending, v.size, v.product_id
           from order_lines ol join stock_levels sl using (variant_id) join variants v on v.id = ol.variant_id
           where ol.order_id = p_order order by ol.variant_id loop
    if l.count_pending then
      raise exception 'stock count pending: % size % has to be counted on the shelf before it can be held', l.product_id, l.size using errcode = 'P0001';
    end if;
    if l.free < l.qty then
      raise exception 'not enough stock: % size % has % free, order needs %', l.product_id, l.size, l.free, l.qty using errcode = 'P0001';
    end if;
  end loop;
  for l in select variant_id, qty from order_lines where order_id = p_order order by variant_id loop
    perform apply_stock_event(l.variant_id, 'reserve', 0, l.qty, p_order, null, 'order hold');
  end loop;
end $$;

-- a physical count settles the question: it records the counted number (even when equal to what was on file) and clears the flag
create or replace function recount_stock(p_idem_key text, p_variant uuid, p_counted int, p_reason text) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; cur int;
begin
  perform require_role('manager');
  prev := idem_begin(p_idem_key, 'recount_stock'); if prev is not null then return prev; end if;
  select on_hand into cur from stock_levels where variant_id = p_variant for update;
  if cur is null then raise exception 'unknown variant'; end if;
  perform apply_stock_event(p_variant, 'recount', p_counted - cur, 0, null, null, p_reason);
  update stock_levels set count_pending = false, count_pending_reason = null where variant_id = p_variant;
  return idem_end(p_idem_key, jsonb_build_object('on_hand', p_counted));
end $$;

-- a manager can also ask for a count (shelf looks wrong, scan disagrees): the item is kept off the website until counted
create or replace function set_count_pending(p_idem_key text, p_variant uuid, p_reason text) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb;
begin
  perform require_role('manager');
  prev := idem_begin(p_idem_key, 'set_count_pending'); if prev is not null then return prev; end if;
  if length(coalesce(trim(p_reason), '')) < 3 then raise exception 'say why this needs a count'; end if;
  perform 1 from stock_levels where variant_id = p_variant for update;
  if not found then raise exception 'unknown variant'; end if;
  update stock_levels set count_pending = true, count_pending_reason = trim(p_reason) where variant_id = p_variant;
  perform apply_stock_event(p_variant, 'adjust', 0, 0, null, null, 'count requested: ' || trim(p_reason));   -- audit row, no quantity change
  return idem_end(p_idem_key, jsonb_build_object('count_pending', true));
end $$;

create or replace function pending_counts()
returns table (variant_id uuid, product_id text, colour text, size text, on_hand int, reserved int, reason text)
language plpgsql stable security definer set search_path = public, auth as $$
begin
  perform require_role('manager');
  return query select sl.variant_id, v.product_id, p.colour, v.size, sl.on_hand, sl.reserved, sl.count_pending_reason
               from stock_levels sl join variants v on v.id = sl.variant_id join products p on p.id = v.product_id
               where sl.count_pending order by v.product_id, v.size;
end $$;

-- Opening balances: ONE ledger row per variant, kind 'opening_balance', nothing else. No sale, dispatch, receipt, order or
-- invented date. All-or-nothing; the same key replays harmlessly; a variant that already has any history is refused, so a
-- second import cannot stack on top of a first. p_rows: [{product_id, size, qty, pending?, reason?}].
-- Service role / owner SQL editor only (the importer), never reachable from the web.
create or replace function import_opening_balance(p_idem_key text, p_source text, p_rows jsonb) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; r jsonb; v uuid; q int; n int := 0; npend int := 0; total int := 0; res jsonb;
begin
  prev := idem_begin(p_idem_key, 'import_opening_balance'); if prev is not null then return prev; end if;
  if length(coalesce(trim(p_source), '')) < 8 then raise exception 'say which backup this comes from (at least 8 characters, e.g. the start of its SHA-256)'; end if;
  if jsonb_typeof(p_rows) <> 'array' or jsonb_array_length(p_rows) = 0 then raise exception 'no rows to import'; end if;
  for r in select value from jsonb_array_elements(p_rows) loop
    select id into v from variants where product_id = r->>'product_id' and size = r->>'size';
    if v is null then raise exception 'unknown variant: % %', r->>'product_id', r->>'size'; end if;
    q := (r->>'qty')::int;
    if q is null or q < 0 then raise exception 'quantity must be zero or more: % %', r->>'product_id', r->>'size'; end if;
    perform 1 from stock_levels where variant_id = v for update;
    if not found then raise exception 'no stock row for % %', r->>'product_id', r->>'size'; end if;
    if exists (select 1 from stock_events where variant_id = v) then
      raise exception 'already has stock history, opening balance refused: % %', r->>'product_id', r->>'size';
    end if;
    perform apply_stock_event(v, 'opening_balance', q, 0, null, null, 'opening balance from Stockroom backup ' || trim(p_source));
    if coalesce((r->>'pending')::boolean, false) then
      update stock_levels set count_pending = true, count_pending_reason = coalesce(nullif(trim(r->>'reason'), ''), 'quantity not confirmed') where variant_id = v;
      npend := npend + 1;
    end if;
    n := n + 1; total := total + q;
  end loop;
  res := jsonb_build_object('variants', n, 'pieces', total, 'count_pending', npend);
  return idem_end(p_idem_key, res);
end $$;

-- ───────────────────────── scanning: never guess between products or colours ─────────────────────────
create or replace function lookup_barcode(p_barcode text)
returns table (variant_id uuid, product_id text, article text, name text, colour text, size text, free int, count_pending boolean)
language plpgsql stable security definer set search_path = public, auth as $$
begin
  perform require_role('staff');
  return query select v.id, p.id, p.article, p.name, p.colour, v.size, sl.on_hand - sl.reserved, sl.count_pending
               from variant_barcodes b join variants v on v.id = b.variant_id join products p on p.id = v.product_id
                    join stock_levels sl on sl.variant_id = v.id
               where b.barcode = trim(p_barcode) order by p.id, v.size;
end $$;

-- complete_sale: a line names its item by variant_id (what the cashier picked), or by a barcode that has exactly ONE
-- owner, or by product_id + size. A barcode with several owners is refused until the cashier chooses the colour.
-- Uncounted items may still be sold at the counter (the piece is in the cashier's hand) but the answer carries a warning
-- and the flag stays; set app_settings 'pending_blocks_counter_sales' to 1 to refuse them instead.
create or replace function complete_sale(p_idem_key text, p_lines jsonb, p_payments jsonb, p_discount_paise int default 0) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; sale uuid; rn bigint; sub int := 0; ldisc int := 0; total int; paid int := 0;
        e jsonb; v record; res jsonb; nc int; pend boolean; warns jsonb := '[]'::jsonb;
        rl_variant uuid[] := '{}'; rl_qty int[] := '{}'; rl_unit int[] := '{}'; rl_disc int[] := '{}'; i int; d int; q int;
begin
  perform require_role('staff');
  prev := idem_begin(p_idem_key, 'complete_sale'); if prev is not null then return prev; end if;
  if jsonb_typeof(p_lines) <> 'array' or jsonb_array_length(p_lines) < 1 then raise exception 'a sale needs at least one line'; end if;
  for e in select * from jsonb_array_elements(p_lines) loop
    if e ? 'variant_id' then
      select vr.id, coalesce(vr.price_paise, pr.price_paise) as unit, pr.id as pid, vr.size as sz into v
        from variants vr join products pr on pr.id = vr.product_id where vr.id = (e->>'variant_id')::uuid;
      if not found then raise exception 'unknown item in sale'; end if;
      if e ? 'barcode' and not exists (select 1 from variant_barcodes b where b.barcode = trim(e->>'barcode') and b.variant_id = v.id) then
        raise exception 'that item does not carry barcode %', e->>'barcode';
      end if;
    elsif e ? 'barcode' then
      select count(*) into nc from variant_barcodes b where b.barcode = trim(e->>'barcode');
      if nc = 0 then raise exception 'unknown barcode'; end if;
      if nc > 1 then raise exception 'ambiguous barcode %: % items carry it - choose the colour (use lookup_barcode, then send variant_id)', trim(e->>'barcode'), nc using errcode = 'P0001'; end if;
      select vr.id, coalesce(vr.price_paise, pr.price_paise) as unit, pr.id as pid, vr.size as sz into v
        from variant_barcodes b join variants vr on vr.id = b.variant_id join products pr on pr.id = vr.product_id where b.barcode = trim(e->>'barcode');
    else
      select vr.id, coalesce(vr.price_paise, pr.price_paise) as unit, pr.id as pid, vr.size as sz into v
        from variants vr join products pr on pr.id = vr.product_id where vr.product_id = e->>'product_id' and upper(vr.size) = upper(e->>'size');
      if not found then raise exception 'unknown item in sale'; end if;
    end if;
    if v.id = any(rl_variant) then raise exception 'list each item once; use quantity'; end if;
    q := (e->>'qty')::int; d := coalesce((e->>'discount_paise')::int, 0);
    if q is null or q < 1 or q > setting('max_qty_per_line') then raise exception 'bad quantity'; end if;
    if d < 0 or d >= q * v.unit then raise exception 'line discount must be below the line total'; end if;
    select count_pending into pend from stock_levels where variant_id = v.id;
    if coalesce(pend, false) then
      if setting('pending_blocks_counter_sales') = 1 then
        raise exception 'stock count pending: % size % has to be counted before it can be sold', v.pid, v.sz using errcode = 'P0001';
      end if;
      warns := warns || to_jsonb(format('%s size %s: stock count is still pending', v.pid, v.sz));
    end if;
    rl_variant := rl_variant || v.id; rl_qty := rl_qty || q; rl_unit := rl_unit || v.unit; rl_disc := rl_disc || d;
    sub := sub + q * v.unit; ldisc := ldisc + d;
  end loop;
  if coalesce(p_discount_paise,0) < 0 then raise exception 'discount cannot be negative'; end if;
  if ldisc + coalesce(p_discount_paise,0) > 0 then perform require_role('manager'); end if;
  total := sub - ldisc - coalesce(p_discount_paise,0);
  if total <= 0 then raise exception 'discount cannot take the bill to zero'; end if;
  for e in select * from jsonb_array_elements(p_payments) loop
    if (e->>'method') not in ('cash','upi') or coalesce((e->>'amount_paise')::int,0) <= 0 then raise exception 'bad payment line'; end if;
    paid := paid + (e->>'amount_paise')::int;
  end loop;
  if paid <> total then raise exception 'payments % do not equal the bill %', paid, total; end if;

  perform lock_stock_rows(rl_variant);
  for i in 1 .. array_length(rl_variant,1) loop
    select on_hand - reserved into q from stock_levels where variant_id = rl_variant[i];
    if q < rl_qty[i] then raise exception 'not enough free stock for a counter sale (variant %)', rl_variant[i] using errcode = 'P0001'; end if;
  end loop;

  insert into sales (subtotal_paise, discount_paise, total_paise, actor) values (sub, ldisc + coalesce(p_discount_paise,0), total, actor_name())
    returning id, receipt_no into sale, rn;
  for i in 1 .. array_length(rl_variant,1) loop
    insert into sale_lines (sale_id, variant_id, qty, unit_paise, line_discount_paise) values (sale, rl_variant[i], rl_qty[i], rl_unit[i], rl_disc[i]);
    perform apply_stock_event(rl_variant[i], 'sale', -rl_qty[i], 0, null, sale, 'counter sale');
  end loop;
  for e in select * from jsonb_array_elements(p_payments) loop
    insert into payments (sale_id, method, amount_paise, upi_ref, verified_by)
    values (sale, e->>'method', (e->>'amount_paise')::int, nullif(trim(e->>'upi_ref'),''), actor_name());
  end loop;
  res := jsonb_build_object('sale_id', sale, 'receipt_no', rn, 'total_paise', total, 'warnings', warns);
  return idem_end(p_idem_key, res);
end $$;

-- ───────────────────────── 4. size labels: FREE and Free are the same size ─────────────────────────
-- Found in the real backup: one product writes its free size as FREE in `sizes` and Free in `stock`, and the website's order line
-- carries the `sizes` spelling. Matching is therefore case-insensitive, and two variants of one product can no longer differ only by case.
create unique index if not exists variants_product_size_ci on variants (product_id, upper(size));

-- place_order_request = the 0005 function with ONE change: the size is matched case-insensitively
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
      where vr.product_id = l.product_id and upper(vr.size) = upper(l.size) and p.published;
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

-- ───────────────────────── grants ─────────────────────────
revoke all on function variants_barcode_sync(), lookup_barcode(text), set_count_pending(text,uuid,text), pending_counts(), import_opening_balance(text,text,jsonb)
  from public, anon, authenticated;
grant execute on function lookup_barcode(text), set_count_pending(text,uuid,text), pending_counts() to authenticated;
grant execute on function import_opening_balance(text,text,jsonb) to service_role;      -- the importer only; never a signed-in web user
