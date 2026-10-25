-- O4U backend, migration 0001: catalogue, stock ledger, order lifecycle, POS foundations.
-- Supabase-compatible PostgreSQL. DEVELOPMENT ONLY: never applied to a real project; tested on synthetic data.
-- All money is integer paise. All writes go through the SECURITY DEFINER functions below; no table is writable
-- by anon/authenticated directly. Roles: owner > manager > staff (see staff table, enforced here, not in the page).

-- ───────────────────────── people ─────────────────────────
create table staff (
  user_id uuid primary key,
  name    text not null,
  role    text not null check (role in ('owner','manager','staff')),
  active  boolean not null default true
);

create or replace function current_role_rank() returns int
language sql stable security definer set search_path = public, auth as $$
  select case s.role when 'owner' then 3 when 'manager' then 2 else 1 end
  from staff s where s.user_id = auth.uid() and s.active
$$;

create or replace function require_role(p_min text) returns void
language plpgsql stable security definer set search_path = public, auth as $$
declare need int := case p_min when 'owner' then 3 when 'manager' then 2 else 1 end; have int := current_role_rank();
begin
  if have is null then raise exception 'not allowed: sign in as shop staff' using errcode = '42501'; end if;
  if have < need then raise exception 'not allowed: needs % access', p_min using errcode = '42501'; end if;
end $$;

create or replace function actor_name() returns text
language sql stable security definer set search_path = public, auth as $$
  select coalesce((select name from staff where user_id = auth.uid()), 'system')
$$;

-- ───────────────────────── settings & store status ─────────────────────────
create table app_settings (key text primary key, value int not null);
insert into app_settings values ('hold_minutes', 120), ('payment_grace_minutes', 60), ('heartbeat_stale_minutes', 3),
                                ('max_qty_per_line', 99), ('max_lines', 40);

create table store_status (
  id int primary key check (id = 1),
  last_heartbeat timestamptz,
  offline_switch boolean not null default false,
  note text
);
insert into store_status (id) values (1);

create or replace function setting(p_key text) returns int language sql stable as $$ select value from app_settings where key = p_key $$;

-- ───────────────────────── catalogue ─────────────────────────
create table products (
  id text primary key,                         -- slug(article + colour), same id Stockroom and the website use
  article text not null, name text not null, brand text not null default '', category text not null,
  colour text not null default '',
  price_paise int not null check (price_paise > 0),
  mrp_paise int check (mrp_paise is null or mrp_paise >= price_paise),
  published boolean not null default false
);

create table variants (
  id uuid primary key default gen_random_uuid(),
  product_id text not null references products(id),
  size text not null,                          -- exactly as written in stockroom.json
  barcode text unique,
  price_paise int check (price_paise is null or price_paise > 0),   -- per-size price override
  unique (product_id, size)
);

-- one row per size; changed ONLY by apply_stock_event
create table stock_levels (
  variant_id uuid primary key references variants(id),
  on_hand  int not null default 0 check (on_hand  >= 0),
  reserved int not null default 0 check (reserved >= 0),
  check (reserved <= on_hand)
);

-- append-only ledger: every change to stock_levels is exactly one row here
create table stock_events (
  id bigserial primary key,
  variant_id uuid not null references variants(id),
  kind text not null check (kind in ('receive','adjust','recount','reserve','release','dispatch','sale','return_in')),
  d_on_hand int not null default 0, d_reserved int not null default 0,
  order_id uuid, sale_id uuid, reason text not null default '',
  actor text not null, at timestamptz not null default now()
);
create index on stock_events (variant_id);
create index on stock_events (order_id);

-- ───────────────────────── idempotency ─────────────────────────
create table idempotency (
  key text primary key, action text not null, result jsonb, created_at timestamptz not null default now()
);

-- ───────────────────────── orders (website requests; same table serves WhatsApp-pasted ones later) ─────────────────────────
create table orders (
  id uuid primary key default gen_random_uuid(),
  ref text not null unique check (ref ~ '^W[0-9]{4}-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{2}$'),
  source text not null default 'website' check (source in ('website','whatsapp')),
  status text not null default 'request' check (status in
    ('request','awaiting_payment','hold_expired','paid','packed','dispatched','failed','delivered','refund_due','refunded','cancelled')),
  customer_name text not null, phone text not null check (phone ~ '^[0-9]{10}$'),
  address text not null, landmark text not null default '',
  -- three different amounts, never conflated:
  items_paise int not null check (items_paise > 0),            -- website-calculated from trusted prices (preliminary)
  delivery_paise int check (delivery_paise is null or delivery_paise >= 0),   -- staff-entered
  discount_paise int not null default 0 check (discount_paise >= 0),
  agreed_paise int check (agreed_paise is null or agreed_paise > 0),          -- staff-agreed final bill; null until agreed
  paid_paise int not null default 0 check (paid_paise >= 0),                  -- verified payments only
  reserved boolean not null default false,                     -- true while this order holds stock in stock_levels.reserved
  stock_deducted boolean not null default false,               -- true once dispatch took the pieces off the rack (once only)
  hold_until timestamptz, grace_used boolean not null default false,
  tracking text not null default '',
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  check (status <> 'awaiting_payment' or (reserved and hold_until is not null)),
  check (status <> 'paid' or paid_paise > 0)
);
create index on orders (status);

create table order_lines (
  order_id uuid not null references orders(id) on delete restrict,
  variant_id uuid not null references variants(id),
  qty int not null check (qty between 1 and 99),
  unit_paise int not null check (unit_paise > 0),              -- trusted price copied at request time
  primary key (order_id, variant_id)
);

-- the allowed lifecycle, as data (the dashboard can read it too)
create table order_transitions (
  action text not null, from_status text not null, to_status text not null, primary key (action, from_status)
);
insert into order_transitions values
  ('confirm_and_reserve','request','awaiting_payment'), ('confirm_and_reserve','hold_expired','awaiting_payment'),
  ('verify_payment','awaiting_payment','paid'), ('verify_payment','hold_expired','paid'),
  ('release_hold','awaiting_payment','request'),
  ('pack','paid','packed'),
  ('dispatch','paid','dispatched'), ('dispatch','packed','dispatched'), ('dispatch','failed','dispatched'),
  ('mark_failed','dispatched','failed'),
  ('mark_delivered','dispatched','delivered'), ('mark_delivered','failed','delivered'),
  ('cancel','request','cancelled'), ('cancel','awaiting_payment','cancelled'), ('cancel','hold_expired','cancelled'),
  ('request_refund','paid','refund_due'), ('request_refund','packed','refund_due'), ('request_refund','failed','refund_due'),
  ('refund_sent','refund_due','refunded');

create table order_events (                                    -- immutable audit trail
  id bigserial primary key, order_id uuid not null references orders(id),
  action text not null, from_status text, to_status text, actor text not null, note text not null default '',
  at timestamptz not null default now()
);
create index on order_events (order_id);

-- customer-reported payments: information only, never money
create table payment_reports (
  id bigserial primary key, order_id uuid not null references orders(id),
  claimed_ref text not null default '', claimed_paise int, at timestamptz not null default now()
);

-- ───────────────────────── money ledger (verified only) ─────────────────────────
create table sales (                                           -- counter (physical) sales: the POS record
  id uuid primary key default gen_random_uuid(),
  receipt_no bigint generated always as identity unique,
  channel text not null default 'counter' check (channel = 'counter'),
  subtotal_paise int not null check (subtotal_paise > 0), discount_paise int not null default 0 check (discount_paise >= 0),
  total_paise int not null check (total_paise > 0),
  status text not null default 'completed' check (status in ('completed')),
  actor text not null, at timestamptz not null default now(),
  check (total_paise = subtotal_paise - discount_paise)
);
create table sale_lines (
  sale_id uuid not null references sales(id), variant_id uuid not null references variants(id),
  qty int not null check (qty between 1 and 99), unit_paise int not null check (unit_paise > 0),
  line_discount_paise int not null default 0 check (line_discount_paise >= 0),
  primary key (sale_id, variant_id)
);

create table payments (                                        -- immutable; one row = money that staff verified
  id bigserial primary key,
  order_id uuid references orders(id), sale_id uuid references sales(id),
  kind text not null default 'payment' check (kind in ('payment','refund')),
  method text not null check (method in ('upi','cash')),
  amount_paise int not null check (amount_paise > 0),
  upi_ref text, paid_at timestamptz not null default now(), verified_by text not null,
  check ((order_id is null) <> (sale_id is null)),
  check (method <> 'upi' or upi_ref is not null)
);
create unique index payments_upi_ref_once on payments (lower(upi_ref)) where kind = 'payment' and upi_ref is not null;

create table refunds (                                         -- never auto-completed: 'due' until a person records the send
  id bigserial primary key, order_id uuid not null references orders(id),
  amount_paise int not null check (amount_paise > 0), reason text not null,
  status text not null default 'due' check (status in ('due','sent')),
  created_by text not null, created_at timestamptz not null default now(),
  sent_ref text, sent_by text, sent_at timestamptz,
  check (status = 'due' or (sent_ref is not null and sent_by is not null))
);

-- immutability
create or replace function forbid_change() returns trigger language plpgsql as $$
begin raise exception '% is append-only', tg_table_name using errcode = '42501'; end $$;
create trigger stock_events_immutable before update or delete on stock_events for each row execute function forbid_change();
create trigger order_events_immutable before update or delete on order_events for each row execute function forbid_change();
create trigger payments_immutable     before update or delete on payments     for each row execute function forbid_change();
create trigger sales_immutable        before update or delete on sales        for each row execute function forbid_change();
create trigger sale_lines_immutable   before update or delete on sale_lines   for each row execute function forbid_change();

-- ───────────────────────── internals ─────────────────────────
-- the ONLY writer of stock_levels. Constraints on stock_levels refuse any negative or over-reserved result.
create or replace function apply_stock_event(p_variant uuid, p_kind text, p_d_on_hand int, p_d_reserved int,
                                             p_order uuid, p_sale uuid, p_reason text) returns void
language plpgsql security definer set search_path = public, auth as $$
begin
  update stock_levels set on_hand = on_hand + p_d_on_hand, reserved = reserved + p_d_reserved where variant_id = p_variant;
  if not found then raise exception 'unknown variant %', p_variant; end if;
  insert into stock_events (variant_id, kind, d_on_hand, d_reserved, order_id, sale_id, reason, actor)
  values (p_variant, p_kind, p_d_on_hand, p_d_reserved, p_order, p_sale, coalesce(p_reason,''), actor_name());
end $$;

create or replace function idem_begin(p_key text, p_action text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare n int; a text; r jsonb;
begin
  if p_key is null or length(p_key) < 8 then raise exception 'idempotency key required (min 8 chars)'; end if;
  insert into idempotency (key, action) values (p_key, p_action) on conflict (key) do nothing;
  get diagnostics n = row_count;
  if n = 1 then return null; end if;
  select action, result into a, r from idempotency where key = p_key;
  if a <> p_action then raise exception 'idempotency key already used for a different action'; end if;
  if r is null then raise exception 'previous attempt with this key did not finish'; end if;
  return r;
end $$;

create or replace function idem_end(p_key text, p_result jsonb) returns jsonb
language sql security definer set search_path = public as $$
  update idempotency set result = p_result where key = p_key returning p_result
$$;

create or replace function log_order(p_order uuid, p_action text, p_from text, p_to text, p_note text) returns void
language sql security definer set search_path = public, auth as $$
  insert into order_events (order_id, action, from_status, to_status, actor, note) values (p_order, p_action, p_from, p_to, actor_name(), coalesce(p_note,''))
$$;

-- lock an order and check the lifecycle table allows this action from its current status
create or replace function lock_order_for(p_order uuid, p_action text) returns orders
language plpgsql security definer set search_path = public as $$
declare o orders;
begin
  select * into o from orders where id = p_order for update;
  if not found then raise exception 'order not found'; end if;
  if not exists (select 1 from order_transitions where action = p_action and from_status = o.status) then
    raise exception 'cannot % an order that is %', p_action, o.status using errcode = 'P0001';
  end if;
  return o;
end $$;

create or replace function lock_stock_rows(p_variants uuid[]) returns void
language sql security definer set search_path = public as $$
  select 1 from stock_levels where variant_id = any(p_variants) order by variant_id for update
$$;

-- reserve every line or none (caller holds the order lock). Locks stock rows in id order: no deadlocks.
create or replace function reserve_lines(p_order uuid) returns void
language plpgsql security definer set search_path = public as $$
declare l record;
begin
  perform lock_stock_rows(array(select variant_id from order_lines where order_id = p_order));
  for l in select ol.variant_id, ol.qty, sl.on_hand - sl.reserved as free, v.size, v.product_id
           from order_lines ol join stock_levels sl using (variant_id) join variants v on v.id = ol.variant_id
           where ol.order_id = p_order order by ol.variant_id loop
    if l.free < l.qty then
      raise exception 'not enough stock: % size % has % free, order needs %', l.product_id, l.size, l.free, l.qty using errcode = 'P0001';
    end if;
  end loop;
  for l in select variant_id, qty from order_lines where order_id = p_order order by variant_id loop
    perform apply_stock_event(l.variant_id, 'reserve', 0, l.qty, p_order, null, 'order hold');
  end loop;
end $$;

create or replace function release_lines(p_order uuid, p_reason text) returns void
language plpgsql security definer set search_path = public as $$
declare l record;
begin
  if not (select reserved from orders where id = p_order) then return; end if;
  perform lock_stock_rows(array(select variant_id from order_lines where order_id = p_order));
  for l in select variant_id, qty from order_lines where order_id = p_order order by variant_id loop
    perform apply_stock_event(l.variant_id, 'release', 0, -l.qty, p_order, null, p_reason);
  end loop;
end $$;

-- ───────────────────────── public (anon) surface ─────────────────────────
-- Availability labels, decided here. A count of 3 or more never leaves the database.
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
      case when not online then 'check'
           when sl.on_hand - sl.reserved >= 3 then 'available'
           when sl.on_hand - sl.reserved > 0 then 'low' else 'ask' end,
      case when not online then null when sl.on_hand - sl.reserved between 1 and 2 then sl.on_hand - sl.reserved
           when sl.on_hand - sl.reserved <= 0 then 0 else null end,
      now()
    from variants v join products p on p.id = v.product_id join stock_levels sl on sl.variant_id = v.id
    where p.published and (p_product_ids is null or v.product_id = any(p_product_ids))
    order by v.product_id, v.size;
end $$;

-- A website order request. Creates a REQUEST only: never reserves stock, never confirms anything.
-- Prices are read from the catalogue; any price the page sends is ignored. Delivery is not calculated here.
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

-- "I have paid" from the customer: recorded as information. It is NOT payment. One bounded grace extension.
create or replace function report_payment(p_ref text, p_phone text, p_claimed_ref text, p_claimed_paise int)
returns jsonb language plpgsql security definer set search_path = public as $$
declare o orders; extended boolean := false;
begin
  select * into o from orders where ref = p_ref and phone = p_phone for update;
  if not found then raise exception 'order not found'; end if;
  insert into payment_reports (order_id, claimed_ref, claimed_paise) values (o.id, coalesce(p_claimed_ref,''), p_claimed_paise);
  if o.status = 'awaiting_payment' and not o.grace_used then
    update orders set grace_used = true, hold_until = greatest(hold_until, now() + make_interval(mins => setting('payment_grace_minutes'))), updated_at = now() where id = o.id;
    extended := true;
    perform log_order(o.id, 'payment_reported', o.status, o.status, 'customer says paid; hold extended once, not verified');
  else
    perform log_order(o.id, 'payment_reported', o.status, o.status, 'customer says paid; not verified');
  end if;
  return jsonb_build_object('recorded', true, 'verified', false, 'hold_extended_once', extended);
end $$;

-- ───────────────────────── staff actions (one call = every consequence) ─────────────────────────
-- New request → awaiting payment: records the agreed bill, revalidates stock, reserves all lines or none, starts the 2 h hold.
create or replace function confirm_and_reserve(p_idem_key text, p_order uuid, p_delivery_paise int default null, p_discount_paise int default 0)
returns jsonb language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; o orders; delivery int; agreed int; res jsonb;
begin
  perform require_role('staff');
  prev := idem_begin(p_idem_key, 'confirm_and_reserve'); if prev is not null then return prev; end if;
  o := lock_order_for(p_order, 'confirm_and_reserve');
  delivery := coalesce(p_delivery_paise, o.delivery_paise);
  if delivery is null then raise exception 'add the delivery charge first'; end if;
  if p_discount_paise < 0 or p_discount_paise >= o.items_paise then raise exception 'discount must be below the items total'; end if;
  if p_discount_paise > 0 then perform require_role('manager'); end if;      -- negotiated amounts need a manager
  agreed := o.items_paise - p_discount_paise + delivery;
  perform reserve_lines(o.id);                                                -- raises (and rolls everything back) if any line is short
  update orders set delivery_paise = delivery, discount_paise = p_discount_paise, agreed_paise = agreed, status = 'awaiting_payment',
         reserved = true, hold_until = now() + make_interval(mins => setting('hold_minutes')), grace_used = false, updated_at = now() where id = o.id;
  perform log_order(o.id, 'confirm_and_reserve', o.status, 'awaiting_payment', format('bill agreed %s paise (items %s, discount %s, delivery %s); stock held', agreed, o.items_paise, p_discount_paise, delivery));
  res := jsonb_build_object('order_id', o.id, 'status', 'awaiting_payment', 'agreed_paise', agreed, 'hold_until', (select hold_until from orders where id = o.id));
  return idem_end(p_idem_key, res);
end $$;

-- Staff checked the money in the UPI app / cash box. The only way an order becomes paid.
create or replace function verify_payment(p_idem_key text, p_order uuid, p_method text, p_amount_paise int, p_upi_ref text, p_paid_at timestamptz default now())
returns jsonb language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; o orders; res jsonb; late boolean; ok boolean := true; why text;
begin
  perform require_role('staff');
  prev := idem_begin(p_idem_key, 'verify_payment'); if prev is not null then return prev; end if;
  o := lock_order_for(p_order, 'verify_payment');
  if p_amount_paise <> o.agreed_paise then raise exception 'amount % differs from the agreed bill % - fix the bill first', p_amount_paise, o.agreed_paise; end if;
  if p_paid_at > now() + interval '2 minutes' then raise exception 'payment time cannot be in the future'; end if;
  late := (o.status = 'hold_expired');
  insert into payments (order_id, method, amount_paise, upi_ref, paid_at, verified_by) values (o.id, p_method, p_amount_paise, nullif(trim(p_upi_ref),''), p_paid_at, actor_name());
  if late then
    begin                                                                      -- try to take the stock back; money is real either way
      perform reserve_lines(o.id);
    exception when sqlstate 'P0001' then ok := false; why := sqlerrm; end;
  end if;
  if ok then
    update orders set status = 'paid', paid_paise = p_amount_paise, reserved = (reserved or late), hold_until = null, updated_at = now() where id = o.id;
    perform log_order(o.id, 'verify_payment', o.status, 'paid', format('%s %s paise verified%s', p_method, p_amount_paise, case when late then '; arrived after the hold expired, stock re-held' else '' end));
    res := jsonb_build_object('order_id', o.id, 'status', 'paid', 'paid_paise', p_amount_paise, 'late', late);
  else                                                                         -- paid but the pieces are gone: refund is DUE, a person completes it
    update orders set status = 'refund_due', paid_paise = p_amount_paise, hold_until = null, updated_at = now() where id = o.id;
    insert into refunds (order_id, amount_paise, reason, created_by) values (o.id, p_amount_paise, 'paid after hold expired and stock was gone', actor_name());
    perform log_order(o.id, 'verify_payment', o.status, 'refund_due', 'paid after the hold expired and the stock was gone: full refund due');
    res := jsonb_build_object('order_id', o.id, 'status', 'refund_due', 'paid_paise', p_amount_paise, 'late', true, 'stock_gone', true);
  end if;
  return idem_end(p_idem_key, res);
end $$;

create or replace function release_hold(p_idem_key text, p_order uuid) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; o orders; res jsonb;
begin
  perform require_role('staff');
  prev := idem_begin(p_idem_key, 'release_hold'); if prev is not null then return prev; end if;
  o := lock_order_for(p_order, 'release_hold');
  perform release_lines(o.id, 'no payment found; released by staff');
  update orders set status = 'request', reserved = false, hold_until = null, agreed_paise = null, updated_at = now() where id = o.id;
  perform log_order(o.id, 'release_hold', o.status, 'request', 'stock released by staff');
  res := jsonb_build_object('order_id', o.id, 'status', 'request');
  return idem_end(p_idem_key, res);
end $$;

create or replace function cancel_order(p_idem_key text, p_order uuid, p_reason text default '') returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; o orders; res jsonb;
begin
  perform require_role('staff');
  prev := idem_begin(p_idem_key, 'cancel_order'); if prev is not null then return prev; end if;
  o := lock_order_for(p_order, 'cancel');                                      -- paid orders are NOT cancellable here: they go through request_refund
  perform release_lines(o.id, 'order cancelled');
  update orders set status = 'cancelled', reserved = false, hold_until = null, updated_at = now() where id = o.id;
  perform log_order(o.id, 'cancel', o.status, 'cancelled', p_reason);
  res := jsonb_build_object('order_id', o.id, 'status', 'cancelled');
  return idem_end(p_idem_key, res);
end $$;

create or replace function pack_order(p_idem_key text, p_order uuid) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; o orders; res jsonb;
begin
  perform require_role('staff');
  prev := idem_begin(p_idem_key, 'pack_order'); if prev is not null then return prev; end if;
  o := lock_order_for(p_order, 'pack');
  update orders set status = 'packed', updated_at = now() where id = o.id;
  perform log_order(o.id, 'pack', o.status, 'packed', '');
  res := jsonb_build_object('order_id', o.id, 'status', 'packed');
  return idem_end(p_idem_key, res);
end $$;

-- Hands the parcel over: the pieces leave the rack ONCE (stock_deducted), the hold is released in the same transaction.
create or replace function dispatch_order(p_idem_key text, p_order uuid, p_tracking text default '') returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; o orders; res jsonb; l record;
begin
  perform require_role('staff');
  prev := idem_begin(p_idem_key, 'dispatch_order'); if prev is not null then return prev; end if;
  o := lock_order_for(p_order, 'dispatch');
  if not o.stock_deducted then
    if not o.reserved then raise exception 'order has no stock held'; end if;
    perform lock_stock_rows(array(select variant_id from order_lines where order_id = o.id));
    for l in select variant_id, qty from order_lines where order_id = o.id order by variant_id loop
      perform apply_stock_event(l.variant_id, 'dispatch', -l.qty, -l.qty, o.id, null, 'dispatched');
    end loop;
  end if;
  update orders set status = 'dispatched', reserved = false, stock_deducted = true, tracking = coalesce(nullif(p_tracking,''), tracking), updated_at = now() where id = o.id;
  perform log_order(o.id, 'dispatch', o.status, 'dispatched', case when o.stock_deducted then 'sent again; stock already deducted' else 'stock deducted' end);
  res := jsonb_build_object('order_id', o.id, 'status', 'dispatched');
  return idem_end(p_idem_key, res);
end $$;

create or replace function mark_failed(p_idem_key text, p_order uuid, p_who text, p_note text default '') returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; o orders; res jsonb;
begin
  perform require_role('staff');
  prev := idem_begin(p_idem_key, 'mark_failed'); if prev is not null then return prev; end if;
  if p_who not in ('customer','partner','shop') then raise exception 'who failed: customer, partner or shop'; end if;
  o := lock_order_for(p_order, 'mark_failed');
  update orders set status = 'failed', updated_at = now() where id = o.id;
  perform log_order(o.id, 'mark_failed', o.status, 'failed', p_who || ': ' || coalesce(p_note,''));
  res := jsonb_build_object('order_id', o.id, 'status', 'failed');
  return idem_end(p_idem_key, res);
end $$;

create or replace function mark_delivered(p_idem_key text, p_order uuid) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; o orders; res jsonb;
begin
  perform require_role('staff');
  prev := idem_begin(p_idem_key, 'mark_delivered'); if prev is not null then return prev; end if;
  o := lock_order_for(p_order, 'mark_delivered');
  update orders set status = 'delivered', updated_at = now() where id = o.id;
  perform log_order(o.id, 'mark_delivered', o.status, 'delivered', '');
  res := jsonb_build_object('order_id', o.id, 'status', 'delivered');
  return idem_end(p_idem_key, res);
end $$;

-- A person decides a paid order must be refunded (e.g. no rider in 24 h). Releases any hold; the refund stays DUE.
create or replace function request_refund(p_idem_key text, p_order uuid, p_reason text) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; o orders; res jsonb; rid bigint;
begin
  perform require_role('manager');
  prev := idem_begin(p_idem_key, 'request_refund'); if prev is not null then return prev; end if;
  if coalesce(trim(p_reason),'') = '' then raise exception 'a reason is required'; end if;
  o := lock_order_for(p_order, 'request_refund');
  perform release_lines(o.id, 'refund approved by ' || actor_name());
  update orders set status = 'refund_due', reserved = false, updated_at = now() where id = o.id;
  insert into refunds (order_id, amount_paise, reason, created_by) values (o.id, o.paid_paise, p_reason, actor_name()) returning id into rid;
  perform log_order(o.id, 'request_refund', o.status, 'refund_due', p_reason);
  res := jsonb_build_object('order_id', o.id, 'status', 'refund_due', 'refund_id', rid);
  return idem_end(p_idem_key, res);
end $$;

-- The ONLY thing that completes a refund: a person recording the UPI reference they sent it with.
create or replace function mark_refund_sent(p_idem_key text, p_refund bigint, p_sent_ref text) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; r refunds; o orders; res jsonb;
begin
  perform require_role('manager');
  prev := idem_begin(p_idem_key, 'mark_refund_sent'); if prev is not null then return prev; end if;
  if coalesce(trim(p_sent_ref),'') = '' then raise exception 'the UPI reference of the refund is required'; end if;
  select * into r from refunds where id = p_refund for update;
  if not found or r.status <> 'due' then raise exception 'refund is not due'; end if;
  o := lock_order_for(r.order_id, 'refund_sent');
  update refunds set status = 'sent', sent_ref = trim(p_sent_ref), sent_by = actor_name(), sent_at = now() where id = r.id;
  insert into payments (order_id, kind, method, amount_paise, upi_ref, verified_by) values (r.order_id, 'refund', 'upi', r.amount_paise, trim(p_sent_ref), actor_name());
  update orders set status = 'refunded', updated_at = now() where id = o.id;
  perform log_order(o.id, 'refund_sent', o.status, 'refunded', 'refund sent, ref ' || trim(p_sent_ref));
  res := jsonb_build_object('order_id', o.id, 'status', 'refunded');
  return idem_end(p_idem_key, res);
end $$;

-- ───────────────────────── automatic expiry (run by a scheduler; also safe to call by hand) ─────────────────────────
-- Releases UNPAID holds past their time. Skips locked rows (a verify in progress wins), and can never touch an order
-- that is paid, packed, dispatched… or that has a verified payment row.
create or replace function expire_holds(p_now timestamptz default now()) returns int
language plpgsql security definer set search_path = public, auth as $$
declare o record; n int := 0;
begin
  for o in select id from orders where status = 'awaiting_payment' and hold_until <= p_now
             and not exists (select 1 from payments p where p.order_id = orders.id and p.kind = 'payment')
           order by id for update skip locked loop
    perform release_lines(o.id, 'hold expired');
    update orders set status = 'hold_expired', reserved = false, updated_at = now() where id = o.id and status = 'awaiting_payment';
    perform log_order(o.id, 'hold_expired', 'awaiting_payment', 'hold_expired', 'unpaid hold ran out; stock released');
    n := n + 1;
  end loop;
  return n;
end $$;

-- ───────────────────────── stock keeping ─────────────────────────
create or replace function receive_stock(p_idem_key text, p_variant uuid, p_qty int, p_reason text default 'received') returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb;
begin
  perform require_role('staff');
  prev := idem_begin(p_idem_key, 'receive_stock'); if prev is not null then return prev; end if;
  if p_qty < 1 then raise exception 'quantity must be positive'; end if;
  perform apply_stock_event(p_variant, 'receive', p_qty, 0, null, null, p_reason);
  return idem_end(p_idem_key, jsonb_build_object('ok', true));
end $$;

-- A physical count. Cannot go below what is held for customers.
create or replace function recount_stock(p_idem_key text, p_variant uuid, p_counted int, p_reason text) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; cur int;
begin
  perform require_role('manager');
  prev := idem_begin(p_idem_key, 'recount_stock'); if prev is not null then return prev; end if;
  select on_hand into cur from stock_levels where variant_id = p_variant for update;
  if cur is null then raise exception 'unknown variant'; end if;
  perform apply_stock_event(p_variant, 'recount', p_counted - cur, 0, null, null, p_reason);
  return idem_end(p_idem_key, jsonb_build_object('on_hand', p_counted));
end $$;

-- A returned item the shop inspected and decided to put back on the rack.
create or replace function return_to_stock(p_idem_key text, p_variant uuid, p_qty int, p_order uuid, p_sale uuid, p_reason text) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb;
begin
  perform require_role('manager');
  prev := idem_begin(p_idem_key, 'return_to_stock'); if prev is not null then return prev; end if;
  if p_qty < 1 then raise exception 'quantity must be positive'; end if;
  if (p_order is null) = (p_sale is null) then raise exception 'name the order or the sale being returned'; end if;
  if p_order is not null and not exists (select 1 from order_lines ol join orders o on o.id = ol.order_id
        where o.id = p_order and ol.variant_id = p_variant and o.stock_deducted and ol.qty >= p_qty) then raise exception 'that order did not take this item out of stock'; end if;
  if p_sale is not null and not exists (select 1 from sale_lines where sale_id = p_sale and variant_id = p_variant and qty >= p_qty) then raise exception 'that sale did not include this item'; end if;
  if (select coalesce(sum(d_on_hand),0) from stock_events where kind = 'return_in' and variant_id = p_variant and (order_id = p_order or sale_id = p_sale)) + p_qty
     > (select coalesce(sum(qty),0) from (select qty from order_lines where order_id = p_order and variant_id = p_variant union all select qty from sale_lines where sale_id = p_sale and variant_id = p_variant) q)
  then raise exception 'more returned than was sold'; end if;
  perform apply_stock_event(p_variant, 'return_in', p_qty, 0, p_order, p_sale, p_reason);
  return idem_end(p_idem_key, jsonb_build_object('ok', true));
end $$;


-- ───────────────────────── counter sale (POS backend; the screen comes later) ─────────────────────────
-- p_lines: [{barcode | product_id+size, qty, discount_paise?}]  p_payments: [{method, amount_paise, upi_ref?}]
-- One call = sale record + stock deducted once + payments + receipt number. Counter sales can only take FREE pieces
-- (on hand minus what is held for customers). Replaying the same key returns the same sale.
create or replace function complete_sale(p_idem_key text, p_lines jsonb, p_payments jsonb, p_discount_paise int default 0) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare prev jsonb; sale uuid; rn bigint; sub int := 0; ldisc int := 0; total int; paid int := 0;
        e jsonb; v record; res jsonb;
        rl_variant uuid[] := '{}'; rl_qty int[] := '{}'; rl_unit int[] := '{}'; rl_disc int[] := '{}'; i int; d int; q int;
begin
  perform require_role('staff');
  prev := idem_begin(p_idem_key, 'complete_sale'); if prev is not null then return prev; end if;
  if jsonb_typeof(p_lines) <> 'array' or jsonb_array_length(p_lines) < 1 then raise exception 'a sale needs at least one line'; end if;
  for e in select * from jsonb_array_elements(p_lines) loop
    select vr.id, coalesce(vr.price_paise, pr.price_paise) as unit into v from variants vr join products pr on pr.id = vr.product_id
      where (e ? 'barcode' and vr.barcode = e->>'barcode') or (not (e ? 'barcode') and vr.product_id = e->>'product_id' and vr.size = e->>'size');
    if not found then raise exception 'unknown item in sale'; end if;
    if v.id = any(rl_variant) then raise exception 'list each item once; use quantity'; end if;
    q := (e->>'qty')::int; d := coalesce((e->>'discount_paise')::int, 0);
    if q is null or q < 1 or q > setting('max_qty_per_line') then raise exception 'bad quantity'; end if;
    if d < 0 or d >= q * v.unit then raise exception 'line discount must be below the line total'; end if;
    rl_variant := rl_variant || v.id; rl_qty := rl_qty || q; rl_unit := rl_unit || v.unit; rl_disc := rl_disc || d;
    sub := sub + q * v.unit; ldisc := ldisc + d;
  end loop;
  if coalesce(p_discount_paise,0) < 0 then raise exception 'discount cannot be negative'; end if;
  if ldisc + coalesce(p_discount_paise,0) > 0 then perform require_role('manager'); end if;   -- discounts are a manager decision
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
  res := jsonb_build_object('sale_id', sale, 'receipt_no', rn, 'total_paise', total);
  return idem_end(p_idem_key, res);
end $$;

create or replace function get_receipt(p_sale uuid) returns jsonb
language plpgsql stable security definer set search_path = public, auth as $$
begin
  perform require_role('staff');
  return (select jsonb_build_object('receipt_no', s.receipt_no, 'at', s.at, 'subtotal_paise', s.subtotal_paise, 'discount_paise', s.discount_paise,
            'total_paise', s.total_paise, 'cashier', s.actor,
            'lines', (select jsonb_agg(jsonb_build_object('product_id', v.product_id, 'size', v.size, 'qty', sl.qty, 'unit_paise', sl.unit_paise, 'line_discount_paise', sl.line_discount_paise) order by v.product_id, v.size)
                      from sale_lines sl join variants v on v.id = sl.variant_id where sl.sale_id = s.id),
            'payments', (select jsonb_agg(jsonb_build_object('method', p.method, 'amount_paise', p.amount_paise)) from payments p where p.sale_id = s.id))
          from sales s where s.id = p_sale);
end $$;

-- ───────────────────────── store status (outage safety) ─────────────────────────
-- The shop app pings every ~minute. No ping for 3 minutes, or the switch on → get_availability says "check" for everything.
create or replace function store_ping() returns void language plpgsql security definer set search_path = public, auth as $$
begin perform require_role('staff'); update store_status set last_heartbeat = now() where id = 1; end $$;

create or replace function set_offline_switch(p_offline boolean, p_note text default '') returns void
language plpgsql security definer set search_path = public, auth as $$
begin perform require_role('manager'); update store_status set offline_switch = p_offline, note = p_note where id = 1; end $$;

-- ───────────────────────── owner analytics (real recorded money only) ─────────────────────────
-- Verified revenue = verified payment rows; refunds = rows a person recorded as sent. Website vs counter kept apart.
create or replace function owner_sales_summary(p_from timestamptz, p_to timestamptz)
returns table (channel text, verified_paise bigint, refunded_paise bigint, net_paise bigint, documents bigint)
language plpgsql stable security definer set search_path = public, auth as $$
begin
  perform require_role('owner');
  return query
    select c.channel,
           coalesce(sum(p.amount_paise) filter (where p.kind = 'payment'), 0)::bigint,
           coalesce(sum(p.amount_paise) filter (where p.kind = 'refund'), 0)::bigint,
           (coalesce(sum(p.amount_paise) filter (where p.kind = 'payment'), 0) - coalesce(sum(p.amount_paise) filter (where p.kind = 'refund'), 0))::bigint,
           count(distinct coalesce(p.order_id, p.sale_id))::bigint
    from (values ('website'), ('counter')) c(channel)
    left join payments p on p.paid_at >= p_from and p.paid_at < p_to
         and ((c.channel = 'website' and p.order_id is not null) or (c.channel = 'counter' and p.sale_id is not null))
    group by c.channel order by c.channel;
end $$;

-- ───────────────────────── access control ─────────────────────────
alter table staff enable row level security;           alter table app_settings enable row level security;
alter table store_status enable row level security;    alter table products enable row level security;
alter table variants enable row level security;        alter table stock_levels enable row level security;
alter table stock_events enable row level security;    alter table idempotency enable row level security;
alter table orders enable row level security;          alter table order_lines enable row level security;
alter table order_transitions enable row level security; alter table order_events enable row level security;
alter table payment_reports enable row level security; alter table sales enable row level security;
alter table sale_lines enable row level security;      alter table payments enable row level security;
alter table refunds enable row level security;

-- staff (any role) may READ operations data; only manager/owner may read the money ledger; nobody writes tables directly.
create policy staff_read on products          for select to authenticated using (current_role_rank() >= 1);
create policy staff_read on variants          for select to authenticated using (current_role_rank() >= 1);
create policy staff_read on stock_levels      for select to authenticated using (current_role_rank() >= 1);
create policy staff_read on stock_events      for select to authenticated using (current_role_rank() >= 1);
create policy staff_read on orders            for select to authenticated using (current_role_rank() >= 1);
create policy staff_read on order_lines       for select to authenticated using (current_role_rank() >= 1);
create policy staff_read on order_events      for select to authenticated using (current_role_rank() >= 1);
create policy staff_read on order_transitions for select to authenticated using (current_role_rank() >= 1);
create policy staff_read on payment_reports   for select to authenticated using (current_role_rank() >= 1);
create policy staff_read on store_status      for select to authenticated using (current_role_rank() >= 1);
create policy mgr_read   on refunds           for select to authenticated using (current_role_rank() >= 2);
create policy mgr_read   on payments          for select to authenticated using (current_role_rank() >= 2);
create policy mgr_read   on sales             for select to authenticated using (current_role_rank() >= 2);
create policy mgr_read   on sale_lines        for select to authenticated using (current_role_rank() >= 2);
create policy self_read  on staff             for select to authenticated using (user_id = auth.uid());

revoke all on all tables in schema public from anon, authenticated, public;
revoke all on all functions in schema public from public, anon, authenticated;
grant select on products, variants, stock_levels, stock_events, orders, order_lines, order_events, order_transitions, payment_reports,
                refunds, payments, sales, sale_lines, staff, store_status to authenticated;
-- the only things the public website may call:
grant execute on function get_availability(text[]), place_order_request(text,text,text,text,text,text,jsonb), report_payment(text,text,text,int) to anon, authenticated;
-- staff app surface (each function checks the caller's role itself):
grant execute on function confirm_and_reserve(text,uuid,int,int), verify_payment(text,uuid,text,int,text,timestamptz), release_hold(text,uuid),
  cancel_order(text,uuid,text), pack_order(text,uuid), dispatch_order(text,uuid,text), mark_failed(text,uuid,text,text), mark_delivered(text,uuid),
  request_refund(text,uuid,text), mark_refund_sent(text,bigint,text), receive_stock(text,uuid,int,text), recount_stock(text,uuid,int,text),
  return_to_stock(text,uuid,int,uuid,uuid,text), complete_sale(text,jsonb,jsonb,int), get_receipt(uuid), store_ping(), set_offline_switch(boolean,text),
  owner_sales_summary(timestamptz,timestamptz), current_role_rank() to authenticated;
-- expire_holds is for the scheduler only (service role / pg_cron), deliberately not granted to anon or authenticated.
