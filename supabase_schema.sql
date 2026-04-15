-- ============================================================
-- Tables
-- ============================================================

create table users (
  id uuid default gen_random_uuid() primary key,
  email text unique not null,
  created_at timestamp with time zone default now()
);

create table subscriptions (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references users(id) on delete cascade not null,
  filter_type text not null check (filter_type in ('town', 'waterbody')),
  filter_value text not null,
  created_at timestamp with time zone default now(),
  unique(user_id, filter_type, filter_value)
);

-- Single-row table to track which stocking IDs we've already seen
create table stocking_state (
  id int primary key default 1,
  last_seen_ids jsonb not null default '[]',
  updated_at timestamp with time zone default now()
);

insert into stocking_state (id, last_seen_ids) values (1, '[]');

-- ============================================================
-- Row Level Security
-- Lock down direct table access — all frontend operations go
-- through RPC functions below (security definer).
-- The GitHub Actions service role key bypasses RLS entirely.
-- ============================================================

alter table users enable row level security;
alter table subscriptions enable row level security;
alter table stocking_state enable row level security;


-- ============================================================
-- RPC Functions (called from the frontend with the anon key)
-- ============================================================

-- Save or update a user's town subscriptions.
-- Replaces all existing subscriptions for this email.
create or replace function set_user_subscriptions(user_email text, towns text[])
returns void
language plpgsql
security definer
as $$
declare
  v_user_id uuid;
begin
  -- Create user if they don't exist
  insert into users (email)
  values (user_email)
  on conflict (email) do nothing;

  select id into v_user_id from users where email = user_email;

  -- Replace all subscriptions
  delete from subscriptions where user_id = v_user_id;

  insert into subscriptions (user_id, filter_type, filter_value)
  select v_user_id, 'town', unnest(towns);
end;
$$;

-- Get a user's current town subscriptions (for the manage page).
create or replace function get_user_subscriptions(user_email text)
returns table(filter_value text)
language sql
security definer
as $$
  select s.filter_value
  from subscriptions s
  join users u on u.id = s.user_id
  where u.email = user_email
    and s.filter_type = 'town';
$$;

-- Remove a user and all their subscriptions.
create or replace function unsubscribe_user(user_email text)
returns void
language sql
security definer
as $$
  delete from users where email = user_email;
$$;

-- ============================================================
-- Grant anon role permission to call the RPC functions
-- ============================================================

grant execute on function set_user_subscriptions(text, text[]) to anon;
grant execute on function get_user_subscriptions(text) to anon;
grant execute on function unsubscribe_user(text) to anon;
