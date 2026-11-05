-- O4U backend, migration 0011: ONE call that gives a product captured in Stockroom its relational rows, with its first quantities.
-- LOCAL ONLY until the owner approves; not applied to any hosted project. Idempotent. Adds no second inventory: stock still changes only
-- through apply_stock_event (here as ordinary 'receive' ledger rows, reason 'initial stock at capture').
--
--   sync_catalogue_product(key, product)
--     product: {id, article, name, brand?, category, colour?, price_paise, mrp_paise?,
--               sizes: [{size, qty (0 .. 10,000), price_paise?, barcode?}]}
--
-- Rules (every one is checked by backend/tests/run_db_tests.py):
--   * New product: created UNPUBLISHED (the owner publishes it; this function never changes `published`). Staff rank is enough.
--   * Existing product with the same id: nothing is overwritten by staff. A change to name, brand, article, colour, category, price or mrp needs
--     manager rank; an identical call is a no-op.
--   * Sizes: a missing size is created with its first quantity as one ledger row (qty 0 creates the size and no ledger row). An existing size is
--     NEVER touched: its quantity is not overwritten (changing stock is apply_stock_moves), and it is reported as "kept".
--   * Two phones capturing the same product at once take turns (advisory lock per product id): one creates it, the other finds it and keeps it.
--   * All or nothing; same key + same contents replays the stored answer; same key + different contents is refused.
--   * Bounded input (same style as 0009): plain single-line text, lengths, at most 14 sizes, 20,000 bytes.
create or replace function sync_catalogue_product(p_idem_key text, p_product jsonb) returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare
  prev jsonb; req text; pid text; art text; nm text; br text; cat text; col text; price int; mrp int; s jsonb; sz text; q int; vp int; bc text;
  vid uuid; exist products; changed boolean := false; created boolean := false; made jsonb := '[]'::jsonb; kept jsonb := '[]'::jsonb; seen text[] := '{}';
begin
  perform require_role('staff');
  if p_idem_key is not null and char_length(p_idem_key) > 100 then raise exception 'idempotency key is too long (max 100 characters)'; end if;
  if p_product is null or jsonb_typeof(p_product) <> 'object' then raise exception 'product must be an object'; end if;
  if octet_length(p_product::text) > 20000 then raise exception 'the request is too large'; end if;
  req := md5(p_product::text);
  prev := idem_begin(p_idem_key, 'sync_catalogue_product');
  if prev is not null then
    if prev->>'_req' is distinct from req then raise exception 'idempotency key already used with different contents'; end if;
    return prev - '_req';
  end if;

  pid := p_product->>'id'; art := trim(coalesce(p_product->>'article','')); nm := trim(coalesce(p_product->>'name','')); br := trim(coalesce(p_product->>'brand',''));
  cat := p_product->>'category'; col := trim(coalesce(p_product->>'colour',''));
  if pid is null or pid !~ '^[a-z0-9]+(-[a-z0-9]+)*$' or char_length(pid) > 100 then raise exception 'product id must be lowercase letters, digits and dashes (max 100)'; end if;
  if art = '' or nm = '' then raise exception 'article and name are required'; end if;
  if char_length(art) > 40 or char_length(nm) > 100 or char_length(br) > 60 or char_length(col) > 60 then raise exception 'article, name, brand or colour is too long'; end if;
  if art ~ '[\x01-\x1f\x7f]' or nm ~ '[\x01-\x1f\x7f]' or br ~ '[\x01-\x1f\x7f]' or col ~ '[\x01-\x1f\x7f]' then raise exception 'article, name, brand and colour must be plain single-line text'; end if;
  if cat is null or cat not in ('tshirts','tops','shirts','lowers','trousers','jeans','nightsuits','capris','accessories') then raise exception 'unknown category'; end if;
  begin price := (p_product->>'price_paise')::int; mrp := (p_product->>'mrp_paise')::int;
  exception when invalid_text_representation or numeric_value_out_of_range then raise exception 'prices must be whole numbers of paise'; end;
  if price is null or price <= 0 or price > 100000000 then raise exception 'price must be between 1 and 100,000,000 paise'; end if;
  if mrp is not null and (mrp < price or mrp > 100000000) then raise exception 'mrp must be at least the price'; end if;
  if jsonb_typeof(p_product->'sizes') is distinct from 'array' or jsonb_array_length(p_product->'sizes') not between 1 and 14 then raise exception 'between 1 and 14 sizes are required'; end if;

  perform pg_advisory_xact_lock(hashtextextended('o4u-sync-product:' || pid, 0));      -- two phones capturing the same product take turns
  select * into exist from products where id = pid for update;
  if not found then
    insert into products (id, article, name, brand, category, colour, price_paise, mrp_paise, published) values (pid, art, nm, br, cat, col, price, mrp, false);
    created := true;
  elsif (exist.article, exist.name, exist.brand, exist.category, exist.colour, exist.price_paise, exist.mrp_paise) is distinct from (art, nm, br, cat, col, price, mrp) then
    perform require_role('manager');
    update products set article = art, name = nm, brand = br, category = cat, colour = col, price_paise = price, mrp_paise = mrp where id = pid;
    changed := true;
  end if;

  for s in select value from jsonb_array_elements(p_product->'sizes') loop
    sz := trim(coalesce(s->>'size',''));
    if sz = '' or char_length(sz) > 12 or sz ~ '[\x01-\x1f\x7f]' then raise exception 'each size needs a short plain label'; end if;
    if upper(sz) = any(seen) then raise exception 'list each size once'; end if;
    seen := seen || upper(sz);
    begin q := (s->>'qty')::int; vp := (s->>'price_paise')::int;
    exception when invalid_text_representation or numeric_value_out_of_range then raise exception 'qty and price must be whole numbers'; end;
    if q is null or q < 0 or q > 10000 then raise exception 'qty must be 0 to 10,000'; end if;
    if vp is not null and (vp <= 0 or vp > 100000000) then raise exception 'size price out of range'; end if;
    bc := nullif(trim(coalesce(s->>'barcode','')), '');
    if bc is not null and (char_length(bc) > 40 or bc ~ '[\x01-\x1f\x7f]') then raise exception 'barcode must be short plain text'; end if;
    select id into vid from variants where product_id = pid and upper(size) = upper(sz);
    if found then
      kept := kept || jsonb_build_array(sz);
    else
      begin
        insert into variants (product_id, size, barcode, price_paise) values (pid, sz, bc, vp) returning id into vid;
      exception when unique_violation then raise exception 'that barcode already belongs to another size' using errcode = 'P0001';
      end;
      insert into stock_levels (variant_id, on_hand, reserved) values (vid, 0, 0);
      if q > 0 then perform apply_stock_event(vid, 'receive', q, 0, null, null, 'initial stock at capture'); end if;
      made := made || jsonb_build_array(jsonb_build_object('size', sz, 'qty', q));
    end if;
  end loop;

  perform idem_end(p_idem_key, jsonb_build_object('product_id', pid, 'created', created, 'updated', changed, 'sizes_created', made, 'sizes_kept', kept, '_req', req));
  return jsonb_build_object('product_id', pid, 'created', created, 'updated', changed, 'sizes_created', made, 'sizes_kept', kept);
end $$;

revoke all on function sync_catalogue_product(text, jsonb) from public, anon, authenticated;
grant execute on function sync_catalogue_product(text, jsonb) to authenticated;
