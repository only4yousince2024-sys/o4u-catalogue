-- O4U backend, migration 0012: changing a product's PRICE in the shared catalogue, with a version check, an audit trail and a manager-only rule.
-- LOCAL ONLY until the owner approves; not applied to any hosted project. Idempotent. Never touches stock, `published` or any other product field.
--
--   set_catalogue_prices(key, product_id, expect_price_paise, price_paise, size_prices)
--     expect_price_paise: the price the person saw when they started editing (NULL = no check). If the price is different now, nothing is changed.
--     price_paise:        the product's base price (1 .. 100,000,000 paise).
--     size_prices:        {"M": 109900, "XL": null} - a per-size price where it differs from the base; null clears that size's override. Sizes not listed are left alone.
--
-- Rules: manager rank (provisional: the owner decides whether staff may change prices); all or nothing; same key + same contents replays the stored answer,
-- same key + different contents is refused; the new price may not exceed the printed MRP when a discount (mrp_paise) is recorded; every change is one row in
-- price_events (append-only, readable by managers and the owner).
create table if not exists price_events (
  id bigserial primary key,
  product_id text not null references products(id),
  size text,                                       -- null = the product's base price
  old_paise int, new_paise int,
  actor text not null,
  at timestamptz not null default now()
);
create index if not exists price_events_product on price_events (product_id);
drop trigger if exists price_events_immutable on price_events;
create trigger price_events_immutable before update or delete on price_events for each row execute function forbid_change();
alter table price_events enable row level security;
drop policy if exists manager_read on price_events;
create policy manager_read on price_events for select to authenticated using ((select current_role_rank()) >= 2);
revoke all on price_events from public, anon, authenticated, service_role;
revoke all on sequence price_events_id_seq from public, anon, authenticated, service_role;
grant select on price_events to authenticated;

create or replace function set_catalogue_prices(p_idem_key text, p_product_id text, p_expect_price_paise int, p_price_paise int, p_size_prices jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path = public, auth as $$
declare
  prev jsonb; req text; pr products; k text; v jsonb; n int; vid uuid; old int; changed int := 0; out jsonb := '{}'::jsonb; seen text[] := '{}';
begin
  perform require_role('manager');
  if p_idem_key is not null and char_length(p_idem_key) > 100 then raise exception 'idempotency key is too long (max 100 characters)'; end if;
  if p_product_id is null or char_length(p_product_id) > 100 then raise exception 'unknown product'; end if;
  if p_price_paise is null or p_price_paise < 1 or p_price_paise > 100000000 then raise exception 'price must be between 1 and 100,000,000 paise'; end if;
  if p_expect_price_paise is not null and (p_expect_price_paise < 1 or p_expect_price_paise > 100000000) then raise exception 'expected price out of range'; end if;
  if p_size_prices is null or jsonb_typeof(p_size_prices) <> 'object' then raise exception 'size prices must be an object'; end if;
  if (select count(*) from jsonb_object_keys(p_size_prices)) > 14 then raise exception 'too many sizes'; end if;
  req := md5(p_product_id || '|' || coalesce(p_expect_price_paise::text, '') || '|' || p_price_paise || '|' || p_size_prices::text);
  prev := idem_begin(p_idem_key, 'set_catalogue_prices');
  if prev is not null then
    if prev->>'_req' is distinct from req then raise exception 'idempotency key already used with different contents'; end if;
    return prev - '_req';
  end if;

  select * into pr from products where id = p_product_id for update;
  if not found then raise exception 'unknown product'; end if;
  if p_expect_price_paise is not null and pr.price_paise <> p_expect_price_paise then
    raise exception 'price changed while editing: it was % when you started, it is % now', p_expect_price_paise, pr.price_paise using errcode = 'P0001';
  end if;
  if pr.mrp_paise is not null and p_price_paise > pr.mrp_paise then
    raise exception 'the price cannot be above the printed MRP (% paise) recorded for this product', pr.mrp_paise using errcode = 'P0001';
  end if;
  if pr.price_paise <> p_price_paise then
    update products set price_paise = p_price_paise where id = p_product_id;
    insert into price_events (product_id, size, old_paise, new_paise, actor) values (p_product_id, null, pr.price_paise, p_price_paise, actor_name());
    changed := changed + 1;
  end if;

  for k, v in select key, value from jsonb_each(p_size_prices) loop
    if upper(k) = any(seen) then raise exception 'list each size once'; end if;
    seen := seen || upper(k);
    if jsonb_typeof(v) not in ('null', 'number') or (jsonb_typeof(v) = 'number' and (v::text !~ '^[0-9]+$' or (v::text)::numeric < 1 or (v::text)::numeric > 100000000)) then
      raise exception 'a size price must be a whole number of paise (1 .. 100,000,000) or null';
    end if;
    if pr.mrp_paise is not null and jsonb_typeof(v) = 'number' and (v::text)::int > pr.mrp_paise then
      raise exception 'the price cannot be above the printed MRP (% paise) recorded for this product', pr.mrp_paise using errcode = 'P0001';
    end if;
    select id, price_paise into vid, old from variants where product_id = p_product_id and upper(size) = upper(k);
    if not found then raise exception 'unknown size %', k using errcode = 'P0001'; end if;
    n := case when jsonb_typeof(v) = 'number' then (v::text)::int else null end;
    if old is distinct from n then
      update variants set price_paise = n where id = vid;
      insert into price_events (product_id, size, old_paise, new_paise, actor) values (p_product_id, upper(k), old, n, actor_name());
      changed := changed + 1;
    end if;
    out := out || jsonb_build_object(upper(k), n);
  end loop;

  perform idem_end(p_idem_key, jsonb_build_object('product_id', p_product_id, 'price_paise', p_price_paise, 'size_prices', out, 'changed', changed, '_req', req));
  return jsonb_build_object('product_id', p_product_id, 'price_paise', p_price_paise, 'size_prices', out, 'changed', changed);
end $$;

revoke all on function set_catalogue_prices(text, text, int, int, jsonb) from public, anon, authenticated;
grant execute on function set_catalogue_prices(text, text, int, int, jsonb) to authenticated;
