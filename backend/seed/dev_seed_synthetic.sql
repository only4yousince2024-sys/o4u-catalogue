-- O4U backend: INVENTED catalogue and opening stock for a hosted DEVELOPMENT Supabase project. Nothing here is real.
-- Run once in the Supabase SQL editor AFTER migrations 0001-0006 and after seed/onboard_staff.sql. Safe to run twice.
-- Every id starts with "dev-" and every barcode with "DEV". Real products must never be put in this project.

do $$
begin
  if exists (select 1 from products where id not like 'dev-%') then
    raise exception 'This database already holds products that are not dev test data. Refusing to seed.';
  end if;
end $$;

insert into products (id, article, name, brand, category, colour, price_paise, mrp_paise, published) values
  ('dev-tee-pink',   'DEV-TEE', 'Pink Test Tee',        '', 'tshirts', 'Pink',  99900,  null,  true),
  ('dev-lower-blue', 'DEV-LOW', 'Blue Test Lower',      '', 'lowers',  'Blue',  149900, null,  true),
  ('dev-cap-red',    'DEV-CAP', 'Test Capri',           '', 'lowers',  'Red',   79900,  null,  true),
  ('dev-cap-green',  'DEV-CAP', 'Test Capri',           '', 'lowers',  'Green', 79900,  null,  true),
  ('dev-cap-blue',   'DEV-CAP', 'Test Capri',           '', 'lowers',  'Blue',  79900,  null,  true),
  ('dev-scarf-plain','DEV-SCF', 'Plain Test Scarf',     '', 'tshirts', 'Plain', 49900,  null,  true),
  ('dev-hidden-top', 'DEV-HID', 'Unpublished Test Top', '', 'tops',    'Grey',  59900,  null,  false)
on conflict (id) do nothing;

-- variants; the three capris share ONE printed barcode on size L (as real manufacturer barcodes do), size XL has none
insert into variants (product_id, size, barcode) values
  ('dev-tee-pink','M','DEV0000001'), ('dev-tee-pink','L','DEV0000002'), ('dev-tee-pink','XL','DEV0000003'),
  ('dev-lower-blue','M','DEV0000011'), ('dev-lower-blue','L','DEV0000012'),
  ('dev-cap-red','L','DEVSHARED01'), ('dev-cap-red','XL',null),
  ('dev-cap-green','L','DEVSHARED01'), ('dev-cap-green','XL',null),
  ('dev-cap-blue','L','DEVSHARED01'), ('dev-cap-blue','XL',null),
  ('dev-scarf-plain','Free','DEV0000021'),
  ('dev-hidden-top','M','DEV0000031')
on conflict (product_id, size) do nothing;

insert into stock_levels (variant_id) select id from variants v where product_id like 'dev-%'
  and not exists (select 1 from stock_levels s where s.variant_id = v.id);

-- opening balances: ONE ledger row per size. dev-cap-green L is flagged "count pending" (quantity not confirmed).
select import_opening_balance('dev-seed-opening-0001', 'dev-seed-synthetic-0001', '[
  {"product_id":"dev-tee-pink","size":"M","qty":5},
  {"product_id":"dev-tee-pink","size":"L","qty":3},
  {"product_id":"dev-tee-pink","size":"XL","qty":1},
  {"product_id":"dev-lower-blue","size":"M","qty":4},
  {"product_id":"dev-lower-blue","size":"L","qty":0},
  {"product_id":"dev-cap-red","size":"L","qty":2},
  {"product_id":"dev-cap-red","size":"XL","qty":2},
  {"product_id":"dev-cap-green","size":"L","qty":2,"pending":true,"reason":"synthetic: quantity on file disagrees"},
  {"product_id":"dev-cap-green","size":"XL","qty":2},
  {"product_id":"dev-cap-blue","size":"L","qty":2},
  {"product_id":"dev-cap-blue","size":"XL","qty":2},
  {"product_id":"dev-scarf-plain","size":"Free","qty":2},
  {"product_id":"dev-hidden-top","size":"M","qty":3}
]'::jsonb);

select (select count(*) from products where id like 'dev-%')   as products,
       (select count(*) from variants where product_id like 'dev-%') as variants,
       (select coalesce(sum(on_hand),0) from stock_levels sl join variants v on v.id = sl.variant_id where v.product_id like 'dev-%') as pieces,
       (select count(*) from stock_levels where count_pending) as count_pending,
       (select count(*) from stock_events where kind = 'opening_balance') as opening_rows;
