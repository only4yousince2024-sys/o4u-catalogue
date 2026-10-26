-- O4U backend, migration 0009: limits found by the real-HTTP tests (backend/api_tests). Idempotent. Development only until the owner approves otherwise.
-- Existing migrations are untouched; this one only REPLACES three functions and tightens one grant. No table changes, no data changes.
--
-- Found by sending real requests through PostgREST (see backend/api_tests/ERROR_CONTRACT.md):
--   1. A refused rate limit was raised with SQLSTATE P0429. PostgREST only turns P0001 and PTnnn codes into HTTP statuses, so the
--      customer's browser received HTTP 500 for "please wait a while". Now PT429 -> HTTP 429 (same message, same limits).
--   2. place_order_request accepted names/addresses/landmarks of any length (a 1 MB name was stored), control characters (escape
--      sequences, bells), a 20 MB request, a NULL phone/reference (reaching a column constraint with a raw 23502 error) and an
--      idempotency key of any length (a 1 MB key hit the index row-size limit and came back as HTTP 500, code 54000).
--   3. report_payment could be called without end: 60 calls on one order stored 60 payment_reports and 60 order_events rows, with an
--      unbounded claimed reference and any amount (negative, 2 billion).
--   4. The service role could execute the internal helper functions (apply_stock_event, idem_begin, log_order ...) over the Data API.
--      They are only meant to be called by the SECURITY DEFINER functions; the service role keeps expire_holds, onboarding and import.
--
-- Limits (characters): name 100, address 500, landmark 200, idempotency key 100, claimed payment reference 64, claimed amount
-- 0 .. 100,000,000 paise (Rs 10 lakh), 10 payment reports per order, order lines <= 20,000 bytes of JSON. Free text is one line
-- (no control characters), as the website already guarantees.

insert into app_settings (key, value) values ('max_payment_reports_per_order', 10) on conflict (key) do nothing;

create or replace function place_order_request(p_idem_key text, p_ref text, p_name text, p_phone text,
                                               p_address text, p_landmark text, p_lines jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare prev jsonb; o_id uuid; total int := 0; l record; v record; res jsonb; nlines int;
begin
  -- cheap shape checks first: nothing is looked up or stored for a request that is the wrong size
  if p_idem_key is not null and char_length(p_idem_key) > 100 then raise exception 'idempotency key is too long (max 100 characters)'; end if;
  if p_lines is not null and octet_length(p_lines::text) > 20000 then raise exception 'the order is too large'; end if;
  prev := idem_begin(p_idem_key, 'place_order_request'); if prev is not null then return prev; end if;
  if coalesce(trim(p_name),'') = '' or coalesce(trim(p_address),'') = '' then raise exception 'name and address are required'; end if;
  if char_length(trim(p_name)) > 100 then raise exception 'name is too long (max 100 characters)'; end if;
  if char_length(trim(p_address)) > 500 then raise exception 'address is too long (max 500 characters)'; end if;
  if char_length(trim(coalesce(p_landmark,''))) > 200 then raise exception 'landmark is too long (max 200 characters)'; end if;
  if p_name ~ '[\x01-\x1f\x7f]' or p_address ~ '[\x01-\x1f\x7f]' or coalesce(p_landmark,'') ~ '[\x01-\x1f\x7f]' then
    raise exception 'name, address and landmark must be plain single-line text';
  end if;
  if p_phone is null or p_phone !~ '^[0-9]{10}$' then raise exception 'phone must be 10 digits'; end if;
  if p_lines is null or jsonb_typeof(p_lines) <> 'array' then raise exception 'lines must be a list'; end if;
  nlines := jsonb_array_length(p_lines);
  if nlines < 1 or nlines > setting('max_lines') then raise exception 'between 1 and % lines allowed', setting('max_lines'); end if;
  if p_ref is null or p_ref !~ '^W[0-9]{4}-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{2}$' then raise exception 'bad order reference'; end if;
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
    raise exception 'too many order requests from this phone number - please wait a while or message the shop on WhatsApp' using errcode = 'PT429';
  end if;
  if (select count(*) from orders where created_at > now() - interval '1 hour') >= setting('rate_all_per_hour') then
    raise exception 'the shop is receiving a lot of requests right now - please try again shortly' using errcode = 'PT429';
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

-- A customer saying "I have paid". Information only, as before; now bounded. Inputs that cannot belong to any order get exactly the
-- same answer as an unknown order, so the response never tells a guesser anything.
create or replace function report_payment(p_ref text, p_phone text, p_claimed_ref text, p_claimed_paise int)
returns jsonb language plpgsql security definer set search_path = public as $$
declare o orders; extended boolean := false;
begin
  if p_ref is null or p_phone is null or char_length(p_ref) > 20 or char_length(p_phone) > 20 then raise exception 'order not found'; end if;
  if char_length(coalesce(p_claimed_ref,'')) > 64 then raise exception 'payment reference is too long (max 64 characters)'; end if;
  if coalesce(p_claimed_ref,'') ~ '[\x01-\x1f\x7f]' then raise exception 'payment reference must be plain text'; end if;
  if p_claimed_paise is not null and (p_claimed_paise < 0 or p_claimed_paise > 100000000) then raise exception 'amount is out of range'; end if;
  select * into o from orders where ref = p_ref and phone = p_phone for update;
  if not found then raise exception 'order not found'; end if;
  if (select count(*) from payment_reports where order_id = o.id) >= setting('max_payment_reports_per_order') then
    raise exception 'this payment has already been reported several times - please message the shop on WhatsApp' using errcode = 'PT429';
  end if;
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

-- CREATE OR REPLACE keeps the old grants; state them again so this file alone documents the public surface.
revoke all on function place_order_request(text,text,text,text,text,text,jsonb) from public, anon, authenticated;
grant execute on function place_order_request(text,text,text,text,text,text,jsonb) to anon, authenticated;
revoke all on function report_payment(text,text,text,int) from public, anon, authenticated;
grant execute on function report_payment(text,text,text,int) to anon, authenticated;

-- Internal helpers: only SECURITY DEFINER functions (running as their owner) call these. Nobody reaches them over the Data API.
revoke all on function actor_name(), apply_stock_event(uuid,text,int,int,uuid,uuid,text), idem_begin(text,text), idem_end(text,jsonb),
  lock_order_for(uuid,text), lock_stock_rows(uuid[]), log_order(uuid,text,text,text,text), o4u_check(text,jsonb), release_lines(uuid,text),
  require_role(text), reserve_lines(uuid), setting(text), forbid_change(), keep_one_owner(), variants_barcode_sync()
  from public, anon, authenticated, service_role;
