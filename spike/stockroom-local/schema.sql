-- SPIKE ONLY. A temporary JSON document table so the existing Stockroom page can be tried on a local database.
-- This is NOT a proposed production schema.
create table if not exists spike_docs (
  collection text not null,
  id text not null,
  data jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (collection, id)
);
create table if not exists spike_leases (
  collection text not null,
  id text not null,
  holder text not null,
  expires_at timestamptz not null,
  primary key (collection, id)
);
create table if not exists spike_assets (
  id text primary key,
  content_type text not null,
  bytes int not null,
  created_at timestamptz not null default now()
);
create or replace function spike_notify() returns trigger language plpgsql as $$
begin
  perform pg_notify('spike_changes', coalesce(new.collection, old.collection));
  return null;
end $$;
drop trigger if exists spike_docs_notify on spike_docs;
create trigger spike_docs_notify after insert or update or delete on spike_docs for each row execute function spike_notify();

-- the relational backend (backend/migrations) is the ONLY owner of stock: tell open pages when it changes
create or replace function spike_notify_stock() returns trigger language plpgsql as $$
begin
  perform pg_notify('spike_changes', 'products');
  return null;
end $$;
drop trigger if exists stock_levels_notify on stock_levels;
create trigger stock_levels_notify after insert or update or delete on stock_levels for each statement execute function spike_notify_stock();
