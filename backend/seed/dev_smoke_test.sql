-- O4U backend: smoke test for a hosted DEVELOPMENT Supabase project, using only the invented "dev-" data from dev_seed_synthetic.sql.
-- Run in the Supabase SQL editor AFTER the seed. It plays the website (anon), staff, a manager and the owner by switching role and
-- identity inside one session, the same two settings PostgREST applies per request. The LAST result grid lists every check: PASS or FAIL.
-- It writes invented orders, payments and sales into the dev project (the seed data is not reset). Never run it where real data exists.
-- Needs one active owner, one manager and one staff row (seed/onboard_staff.sql). Nothing is sent anywhere; no keys are used.

drop table if exists pg_temp.smoke_results;
create temp table smoke_results (n serial primary key, check_name text, verdict text, detail text);

create or replace function pg_temp.rec(p_name text, p_ok boolean, p_detail text default '') returns void language plpgsql security definer as $f$
begin
  insert into pg_temp.smoke_results (check_name, verdict, detail) values (p_name, case when p_ok then 'PASS' else 'FAIL' end, left(coalesce(p_detail, ''), 300));
  raise notice '% | % %', case when p_ok then 'PASS' else 'FAIL' end, p_name, case when p_ok then '' else '-- ' || coalesce(p_detail, '') end;   -- notices survive even if a later error rolls the table back
end $f$;

-- a valid order reference for these lines: W<DDMM>-<4 random chars>-<2 check characters> (same check as the website)
create or replace function pg_temp.mkref(p_lines jsonb) returns text language plpgsql security definer as $f$
declare al text := '23456789ABCDEFGHJKMNPQRSTUVWXYZ'; b text;
begin
  b := 'W' || to_char(now(), 'DDMM') || '-' || substr(al, 1 + (random() * 30)::int, 1) || substr(al, 1 + (random() * 30)::int, 1)
       || substr(al, 1 + (random() * 30)::int, 1) || substr(al, 1 + (random() * 30)::int, 1);
  return b || '-' || public.o4u_check(b, (select jsonb_agg(jsonb_build_array(e->>'product_id', e->>'size', e->>'qty')) from jsonb_array_elements(p_lines) e));
end $f$;

do $smoke$
declare
  v_owner uuid; v_mgr uuid; v_staff uuid;
  v_green uuid; v_red uuid; v_xl uuid; v_tee_m uuid; v_tee_l uuid; v_low_m uuid;
  lines jsonb; oid uuid; oid2 uuid; oid3 uuid; r jsonb; msg text; n int; n0 int; n1 int; st text; arr text[]; ph text;
  res_ int; k text; oref text; cron_ok boolean; base_xl int; base_green int;
begin
  if exists (select 1 from products where id not like 'dev-%') then
    raise exception 'This database holds products that are not dev test data. Refusing to run the smoke test.';
  end if;
  select user_id into v_owner from staff where role = 'owner'   and active order by created_at limit 1;
  select user_id into v_mgr   from staff where role = 'manager' and active order by created_at limit 1;
  select user_id into v_staff from staff where role = 'staff'   and active order by created_at limit 1;
  if v_owner is null or v_mgr is null or v_staff is null then
    raise exception 'Need one active owner, one manager and one staff row first (seed/onboard_staff.sql).';
  end if;
  v_green := (select id from variants where product_id = 'dev-cap-green' and size = 'L');
  v_red   := (select id from variants where product_id = 'dev-cap-red' and size = 'L');
  v_xl    := (select id from variants where product_id = 'dev-tee-pink' and size = 'XL');
  v_tee_m := (select id from variants where product_id = 'dev-tee-pink' and size = 'M');
  v_tee_l := (select id from variants where product_id = 'dev-tee-pink' and size = 'L');
  v_low_m := (select id from variants where product_id = 'dev-lower-blue' and size = 'M');
  if v_green is null or v_xl is null then raise exception 'Run dev_seed_synthetic.sql first.'; end if;

  -- ═══ 0. known starting state (owner/manager actions, all audited in the ledger) ═══
  perform set_config('request.jwt.claims', json_build_object('sub', v_mgr, 'role', 'authenticated')::text, true);
  execute 'set local role authenticated';
  perform store_ping();
  perform recount_stock('smoke-' || gen_random_uuid(), v_tee_m, (select reserved from stock_levels where variant_id = v_tee_m) + 5, 'smoke test: known start');
  perform recount_stock('smoke-' || gen_random_uuid(), v_tee_l, (select reserved from stock_levels where variant_id = v_tee_l) + 3, 'smoke test: known start');
  perform recount_stock('smoke-' || gen_random_uuid(), v_xl,    (select reserved from stock_levels where variant_id = v_xl) + 1, 'smoke test: known start');
  perform recount_stock('smoke-' || gen_random_uuid(), v_low_m, (select reserved from stock_levels where variant_id = v_low_m) + 4, 'smoke test: known start');
  perform recount_stock('smoke-' || gen_random_uuid(), v_red,   (select reserved from stock_levels where variant_id = v_red) + 2, 'smoke test: known start');
  perform recount_stock('smoke-' || gen_random_uuid(), v_green, (select reserved from stock_levels where variant_id = v_green) + 2, 'smoke test: known start');
  perform set_count_pending('smoke-' || gen_random_uuid(), v_green, 'smoke test: pretend this quantity is disputed');
  execute 'reset role';
  perform pg_temp.rec('start: staff and manager can act, shop heartbeat recorded', (select last_heartbeat > now() - interval '1 minute' from store_status where id = 1));

  select reserved into base_xl from stock_levels where variant_id = v_xl;                      -- earlier runs may have left holds: compare to these, not to zero
  select reserved into base_green from stock_levels where variant_id = v_green;

  -- ═══ 1. what the public website sees ═══
  update store_status set last_heartbeat = now() - interval '10 minutes';                       -- the shop app went silent
  perform set_config('request.jwt.claims', '', true); execute 'set local role anon';
  select array_agg(distinct state) into arr from get_availability();
  execute 'reset role';
  perform pg_temp.rec('outage: every size reads "check" when the shop app is silent', arr = array['check'], coalesce(arr::text, 'none'));
  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  perform store_ping();
  execute 'reset role';

  perform set_config('request.jwt.claims', '', true); execute 'set local role anon';
  select g.state || ':' || coalesce(g.n::text, '') into st from get_availability(array['dev-tee-pink']) g where g.size = 'M';
  perform pg_temp.rec('labels: 5 free reads available, no number', st = 'available:', st);
  select g.state || ':' || coalesce(g.n::text, '') into st from get_availability(array['dev-tee-pink']) g where g.size = 'XL';
  perform pg_temp.rec('labels: 1 free reads low, Only 1', st = 'low:1', st);
  select g.state || ':' || coalesce(g.n::text, '') into st from get_availability(array['dev-lower-blue']) g where g.size = 'L';
  perform pg_temp.rec('labels: 0 free reads ask', st = 'ask:0', st);
  select g.state || ':' || coalesce(g.n::text, '') into st from get_availability(array['dev-cap-green']) g where g.size = 'L';
  perform pg_temp.rec('labels: an uncounted size reads check, never available', st = 'check:', st);
  select count(*) into n from get_availability(array['dev-hidden-top']);
  execute 'reset role';
  perform pg_temp.rec('labels: an unpublished product is not listed', n = 0);

  -- ═══ 2. website order request -> one-tap lifecycle ═══
  ph := '90000' || lpad((random() * 99999)::int::text, 5, '0');
  lines := '[{"product_id":"dev-tee-pink","size":"M","qty":2},{"product_id":"dev-lower-blue","size":"M","qty":1}]'::jsonb;
  select on_hand, reserved into n0, res_ from stock_levels where variant_id = v_tee_m;
  perform set_config('request.jwt.claims', '', true); execute 'set local role anon';
  r := place_order_request('smoke-' || gen_random_uuid(), pg_temp.mkref(lines), 'Dev Test Customer', ph, '1 Test Street, Testville', 'near test park', lines);
  execute 'reset role';
  oid := (r->>'order_id')::uuid;
  perform pg_temp.rec('order: website request created as a REQUEST with the catalogue total', r->>'status' = 'request' and (r->>'items_total_paise')::int = 2 * 99900 + 149900, r::text);
  perform pg_temp.rec('order: a request holds no stock', (select reserved from stock_levels where variant_id = v_tee_m) = res_ and (select count(*) from stock_events where order_id = oid) = 0);

  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  begin perform confirm_and_reserve('smoke-' || gen_random_uuid(), oid, 5000, 500); msg := null; exception when others then msg := sqlerrm; end;
  perform pg_temp.rec('roles: staff cannot give a discount', msg like '%manager%', msg);
  r := confirm_and_reserve('smoke-' || gen_random_uuid(), oid, 5000, 0);
  execute 'reset role';
  perform pg_temp.rec('Confirm & Reserve: awaiting payment, agreed bill = items + delivery', r->>'status' = 'awaiting_payment' and (r->>'agreed_paise')::int = 354700, r::text);
  perform pg_temp.rec('Confirm & Reserve: two-hour hold and stock held', (select reserved from orders where id = oid) and (select extract(epoch from hold_until - now()) from orders where id = oid) between 7000 and 7200);

  oref := (select o.ref from orders o where o.id = oid);
  perform set_config('request.jwt.claims', '', true); execute 'set local role anon';
  r := report_payment(oref, ph, 'CUSTOMER-SAYS-PAID', 354700);
  execute 'reset role';
  perform pg_temp.rec('payment: "I have paid" is information only', (r->>'verified')::boolean is false and (select status from orders where id = oid) = 'awaiting_payment' and (select count(*) from payments where order_id = oid) = 0, r::text);

  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  r := verify_payment('smoke-' || gen_random_uuid(), oid, 'upi', 354700, 'DEVUPI' || substr(md5(random()::text), 1, 8), now());
  execute 'reset role';
  perform pg_temp.rec('Payment verified: paid, hold lifted, one payment row', r->>'status' = 'paid' and (select hold_until is null from orders where id = oid) and (select count(*) from payments where order_id = oid) = 1, r::text);
  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  k := 'smoke-' || gen_random_uuid();
  r := dispatch_order(k, oid, 'DEV-TRACK-1');
  perform dispatch_order(k, oid, 'DEV-TRACK-1');                                               -- a retry with the same key
  execute 'reset role';
  perform pg_temp.rec('Dispatch: stock deducted exactly once even when the tap is repeated', (select on_hand from stock_levels where variant_id = v_tee_m) = n0 - 2 and (select stock_deducted from orders where id = oid), (select on_hand from stock_levels where variant_id = v_tee_m)::text);

  -- ═══ 3. the last piece goes to one customer ═══
  lines := '[{"product_id":"dev-tee-pink","size":"XL","qty":1}]'::jsonb;
  perform set_config('request.jwt.claims', '', true); execute 'set local role anon';
  oid2 := ((place_order_request('smoke-' || gen_random_uuid(), pg_temp.mkref(lines), 'Dev Customer A', '90000' || lpad((random() * 99999)::int::text, 5, '0'), '2 Test Street', '', lines))->>'order_id')::uuid;
  oid3 := ((place_order_request('smoke-' || gen_random_uuid(), pg_temp.mkref(lines), 'Dev Customer B', '90000' || lpad((random() * 99999)::int::text, 5, '0'), '3 Test Street', '', lines))->>'order_id')::uuid;
  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  perform confirm_and_reserve('smoke-' || gen_random_uuid(), oid2, 5000, 0);
  begin perform confirm_and_reserve('smoke-' || gen_random_uuid(), oid3, 5000, 0); msg := null; exception when others then msg := sqlerrm; end;
  execute 'reset role';
  perform pg_temp.rec('last piece: the second customer is refused, no oversell', msg like 'not enough stock%' and (select reserved from stock_levels where variant_id = v_xl) = base_xl + 1, msg);

  -- ═══ 4. expiry, and a payment that arrives late ═══
  update orders set hold_until = now() - interval '1 minute' where id = oid2;                  -- pretend two hours passed (admin edit, dev only)
  n := expire_holds();
  perform pg_temp.rec('expiry: the unpaid hold is released and the stock returns', n >= 1 and (select status from orders where id = oid2) = 'hold_expired' and (select reserved from stock_levels where variant_id = v_xl) = base_xl, 'released ' || n);
  perform pg_temp.rec('expiry: running it again releases nothing more', expire_holds() = 0);
  perform pg_temp.rec('expiry: the earlier PAID order was untouched', (select status from orders where id = oid) = 'dispatched');
  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  r := verify_payment('smoke-' || gen_random_uuid(), oid2, 'upi', 99900 + 5000, 'DEVUPI' || substr(md5(random()::text), 1, 8), now());
  execute 'reset role';
  perform pg_temp.rec('late payment: stock still free, so it is re-held and paid', r->>'status' = 'paid' and (r->>'late')::boolean and (select reserved from stock_levels where variant_id = v_xl) = base_xl + 1, r::text);

  -- ═══ 5. shared barcodes, uncounted stock ═══
  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  select count(*) into n from lookup_barcode('DEVSHARED01');
  begin perform complete_sale('smoke-' || gen_random_uuid(), '[{"barcode":"DEVSHARED01","qty":1}]'::jsonb, '[{"method":"cash","amount_paise":79900}]'::jsonb, 0); msg := null; exception when others then msg := sqlerrm; end;
  execute 'reset role';
  perform pg_temp.rec('barcode: one printed barcode lists all three colours', n = 3, n::text);
  perform pg_temp.rec('barcode: scanning it alone is refused (cashier must choose the colour)', msg like 'ambiguous barcode%', msg);
  select on_hand into n0 from stock_levels where variant_id = v_red;
  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  r := complete_sale('smoke-' || gen_random_uuid(), format('[{"barcode":"DEVSHARED01","variant_id":"%s","qty":1}]', v_red)::jsonb, '[{"method":"cash","amount_paise":79900}]'::jsonb, 0);
  execute 'reset role';
  perform pg_temp.rec('barcode: the chosen colour sells, the others are untouched', (select on_hand from stock_levels where variant_id = v_red) = n0 - 1 and (select on_hand from stock_levels where variant_id = v_green) = 2, r::text);
  perform pg_temp.rec('counter sale: receipt number issued, recorded as a counter sale', (r->>'receipt_no') is not null and (select count(*) from payments where sale_id = (r->>'sale_id')::uuid) = 1);

  lines := '[{"product_id":"dev-cap-green","size":"L","qty":1}]'::jsonb;
  perform set_config('request.jwt.claims', '', true); execute 'set local role anon';
  oid3 := ((place_order_request('smoke-' || gen_random_uuid(), pg_temp.mkref(lines), 'Dev Customer C', '90000' || lpad((random() * 99999)::int::text, 5, '0'), '4 Test Street', '', lines))->>'order_id')::uuid;
  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  begin perform confirm_and_reserve('smoke-' || gen_random_uuid(), oid3, 5000, 0); msg := null; exception when others then msg := sqlerrm; end;
  execute 'reset role';
  perform pg_temp.rec('uncounted stock: a website hold on it is refused', msg like 'stock count pending%' and (select reserved from stock_levels where variant_id = v_green) = base_green, msg);
  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  begin perform recount_stock('smoke-' || gen_random_uuid(), v_green, 2, 'staff cannot'); msg := null; exception when others then msg := sqlerrm; end;
  execute 'reset role';
  perform pg_temp.rec('uncounted stock: only a manager can record the count', msg like '%manager%', msg);
  perform set_config('request.jwt.claims', json_build_object('sub', v_mgr, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  perform recount_stock('smoke-' || gen_random_uuid(), v_green, 2, 'smoke test: counted on the shelf');
  perform confirm_and_reserve('smoke-' || gen_random_uuid(), oid3, 5000, 0);
  execute 'reset role';
  perform pg_temp.rec('uncounted stock: after a manager counts it, it can be held again', (select not count_pending from stock_levels where variant_id = v_green) and (select status from orders where id = oid3) = 'awaiting_payment');

  -- ═══ 6. who can do what ═══
  perform set_config('request.jwt.claims', '', true); execute 'set local role anon';
  begin perform count(*) from orders; msg := null; exception when others then msg := sqlerrm; end;
  execute 'reset role';
  perform pg_temp.rec('access: the public cannot read orders', msg like 'permission denied%', msg);
  perform set_config('request.jwt.claims', '', true); execute 'set local role anon';
  begin perform confirm_and_reserve('smoke-' || gen_random_uuid(), oid, 1, 0); msg := null; exception when others then msg := sqlerrm; end;
  execute 'reset role';
  perform pg_temp.rec('access: the public cannot confirm orders', msg like 'permission denied%', msg);
  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  select count(*) into n from payments;
  begin perform owner_sales_summary(now() - interval '1 day', now() + interval '1 day'); msg := null; exception when others then msg := sqlerrm; end;
  execute 'reset role';
  perform pg_temp.rec('access: staff cannot read payments or the owner summary', n = 0 and msg like '%owner%', 'payments visible: ' || n || '; ' || coalesce(msg, ''));
  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  begin update stock_levels set on_hand = 999; msg := null; exception when others then msg := sqlerrm; end;
  execute 'reset role';
  perform pg_temp.rec('access: nobody edits stock directly', msg like 'permission denied%', msg);
  perform set_config('request.jwt.claims', json_build_object('sub', v_owner, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  select verified_paise into n from owner_sales_summary(now() - interval '1 day', now() + interval '1 day') where channel = 'website';
  select verified_paise into n1 from owner_sales_summary(now() - interval '1 day', now() + interval '1 day') where channel = 'counter';
  execute 'reset role';
  perform pg_temp.rec('owner: sees verified website and counter revenue separately', n >= 354700 + 104900 and n1 >= 79900, 'website ' || n || ', counter ' || n1);

  -- ═══ tidy up this run's own holds so the test can be run again ═══
  perform set_config('request.jwt.claims', json_build_object('sub', v_staff, 'role', 'authenticated')::text, true); execute 'set local role authenticated';
  perform cancel_order('smoke-' || gen_random_uuid(), oid3, 'smoke test tidy-up');
  perform dispatch_order('smoke-' || gen_random_uuid(), oid2, 'DEV-TRACK-2');
  execute 'reset role';

  -- ═══ 7. the books balance ═══
  perform pg_temp.rec('ledger: every shelf count equals the sum of its ledger rows',
    not exists (select 1 from stock_levels sl where sl.on_hand <> coalesce((select sum(d_on_hand) from stock_events e where e.variant_id = sl.variant_id), 0)
                                                  or sl.reserved <> coalesce((select sum(d_reserved) from stock_events e where e.variant_id = sl.variant_id), 0)));
  perform pg_temp.rec('ledger: no negative or over-reserved stock', not exists (select 1 from stock_levels where on_hand < 0 or reserved < 0 or reserved > on_hand));
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    execute $q$select exists (select 1 from cron.job where jobname = 'o4u-expire-holds' and active)$q$ into cron_ok;
  else cron_ok := false; end if;
  perform pg_temp.rec('scheduler: pg_cron job present (informational; FAIL here means use the Edge Function fallback)', cron_ok);
exception when others then
  execute 'reset role';
  raise notice 'SMOKE TEST STOPPED BY AN ERROR: %', sqlerrm;
  perform pg_temp.rec('SMOKE TEST STOPPED BY AN ERROR', false, sqlerrm);
end $smoke$;

select n, check_name, verdict, detail from pg_temp.smoke_results order by n;
