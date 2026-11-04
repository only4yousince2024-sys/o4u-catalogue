-- O4U backend, migration 0010: ONE atomic, retry-safe call for the stock changes the Stockroom screens make. LOCAL ONLY until the owner approves;
-- not applied to any hosted project. Idempotent. Extends the existing inventory (apply_stock_event / stock_levels / stock_events), adds no second one.
--
-- Why: the page changes stock by READING a product, computing a new absolute number and WRITING it, then writing a history line in a second
-- request. Two phones, a slow network, an expired lock or a crash between the two writes can lose pieces or leave stock and history disagreeing.
-- Here the change is a DELTA applied to the locked current row, in the same transaction as its ledger row (apply_stock_event is the only writer
-- and inserts the stock_events row), so it can neither overwrite a newer value nor exist without its ledger entry.
--
--   apply_stock_moves(key, moves[, reason])      moves: [{variant_id | product_id + size,
--                                                        kind: sale | dispatch | return_in | receive | adjust | recount,
--                                                        change: non-zero integer (sale/dispatch negative, return_in/receive positive, adjust either),
--                                                        recount: counted (>= 0) + expect_on_hand (what the person saw), no change,
--                                                        reason?}]
-- All lines or none. Same key + same contents replays the stored answer (a lost response followed by a retry deducts once); the same key with
-- different contents is refused. Negative changes cannot take stock below what is held for customers. A recount applies only if on-hand is still
-- what the counter saw ("stock changed while counting"). 'recount' needs manager rank; everything else staff.
create or replace function apply_stock_moves(p_idem_key text, p_moves jsonb, p_reason text default '') returns jsonb
language plpgsql security definer set search_path = public, auth as $$
declare
  prev jsonb; req text; e jsonb; n int; i int := 0; v uuid; kind text; chg int; cnt int; exp int; cur int; rsv int;
  vids uuid[] := '{}'; res jsonb := '[]'::jsonb; one jsonb; lines jsonb := '[]'::jsonb; need_mgr boolean := false;
begin
  perform require_role('staff');
  if p_idem_key is not null and char_length(p_idem_key) > 100 then raise exception 'idempotency key is too long (max 100 characters)'; end if;
  if p_moves is null or jsonb_typeof(p_moves) <> 'array' then raise exception 'moves must be a list'; end if;
  if octet_length(p_moves::text) > 20000 then raise exception 'the request is too large'; end if;
  n := jsonb_array_length(p_moves);
  if n < 1 or n > setting('max_lines') then raise exception 'between 1 and % moves allowed', setting('max_lines'); end if;
  req := md5(p_moves::text || '|' || coalesce(p_reason, ''));
  prev := idem_begin(p_idem_key, 'apply_stock_moves');
  if prev is not null then
    if prev->>'_req' is distinct from req then raise exception 'idempotency key already used with different contents'; end if;
    return prev - '_req';
  end if;
  if exists (select 1 from jsonb_array_elements(p_moves) m where m->>'kind' = 'recount') then perform require_role('manager'); end if;

  -- resolve every line and take the stock rows in id order (no deadlocks between two callers)
  for e in select value from jsonb_array_elements(p_moves) loop
    i := i + 1;
    kind := e->>'kind';
    if kind is null or kind not in ('sale','dispatch','return_in','receive','adjust','recount') then raise exception 'line %: unknown kind %', i, kind; end if;
    if e ? 'variant_id' then v := (e->>'variant_id')::uuid;
    else select id into v from variants where product_id = e->>'product_id' and (size = e->>'size' or upper(size) = upper(e->>'size')) order by (size = e->>'size') desc limit 1;
    end if;
    if v is null or not exists (select 1 from variants where id = v) then raise exception 'line %: unknown item', i; end if;
    if v = any(vids) then raise exception 'line %: list each item once', i; end if;
    vids := vids || v;
    lines := lines || jsonb_build_array(e || jsonb_build_object('_v', v));
  end loop;
  perform lock_stock_rows(vids);

  for e in select value from jsonb_array_elements(lines) order by (value->>'_v') loop
    v := (e->>'_v')::uuid; kind := e->>'kind';
    select on_hand, reserved into cur, rsv from stock_levels where variant_id = v;
    if kind = 'recount' then
      cnt := (e->>'counted')::int; exp := (e->>'expect_on_hand')::int;
      if cnt is null or cnt < 0 or exp is null then raise exception 'a recount needs counted (0 or more) and expect_on_hand'; end if;
      if cur <> exp then raise exception 'stock changed while counting: the rack was % when you started, it is % now', exp, cur using errcode = 'P0001'; end if;
      if cnt < rsv then raise exception 'cannot count below the % piece(s) held for customers', rsv using errcode = 'P0001'; end if;
      chg := cnt - cur;
      if chg <> 0 then perform apply_stock_event(v, 'recount', chg, 0, null, null, coalesce(nullif(e->>'reason',''), nullif(p_reason,''), 'recount')); end if;
      update stock_levels set count_pending = false, count_pending_reason = null where variant_id = v;
    else
      chg := (e->>'change')::int;
      if chg is null or chg = 0 then raise exception 'a move needs a non-zero whole-number change'; end if;
      if kind in ('sale','dispatch') and chg > 0 then raise exception '% must take pieces off (negative change)', kind; end if;
      if kind in ('return_in','receive') and chg < 0 then raise exception '% must add pieces (positive change)', kind; end if;
      if abs(chg) > 100000 then raise exception 'change out of range'; end if;
      if chg < 0 and cur - rsv < -chg then
        raise exception 'only % free to take off (% on hand, % held for customers)', greatest(cur - rsv, 0), cur, rsv using errcode = 'P0001';
      end if;
      perform apply_stock_event(v, kind, chg, 0, null, null, coalesce(nullif(e->>'reason',''), nullif(p_reason,''), kind));
    end if;
    select jsonb_build_object('variant_id', v, 'product_id', vr.product_id, 'size', vr.size, 'kind', kind, 'before', cur, 'after', sl.on_hand, 'change', sl.on_hand - cur)
      into one from stock_levels sl join variants vr on vr.id = sl.variant_id where sl.variant_id = v;
    res := res || one;
  end loop;
  perform idem_end(p_idem_key, jsonb_build_object('moves', res, '_req', req));
  return jsonb_build_object('moves', res);
end $$;

revoke all on function apply_stock_moves(text, jsonb, text) from public, anon, authenticated;
grant execute on function apply_stock_moves(text, jsonb, text) to authenticated;
