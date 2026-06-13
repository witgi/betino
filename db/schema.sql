-- Supabase schema pre value-bets (spusti v Supabase -> SQL Editor -> New query -> Run)
-- Prihlasovanie riesi Supabase Auth (Google). Tu su len tabulky pre stavkovanie.

-- 1) Vysledky vsetkych tipov (verejne citatelne, zapisuje len denny cron service-key).
--    Web podla nich pocita osobne aj globalne statistiky.
create table if not exists public.tip_results (
  tip_key    text primary key,                -- "commence|home|away|market|selection"
  league     text,
  home       text,
  away       text,
  commence   timestamptz,
  market     text,
  selection  text,
  best_odds  numeric,
  result     text,                            -- 'pending' | 'win' | 'loss' | 'push'
  settled_at timestamptz,
  updated_at timestamptz default now()
);

alter table public.tip_results enable row level security;

-- ktokolvek (aj neprihlaseny) moze citat vysledky
drop policy if exists "tip_results read" on public.tip_results;
create policy "tip_results read" on public.tip_results
  for select using (true);
-- zapis robi len service_role (cron) -> ziadna insert/update policy pre beznych userov

-- 2) Stavky usera (co si REALNE oznacil ako "podane"). Kazdy vidi len svoje.
create table if not exists public.user_bets (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null default auth.uid() references auth.users(id) on delete cascade,
  tip_key    text not null,
  league     text,
  home       text,
  away       text,
  commence   timestamptz,
  market     text,
  selection  text,
  best_odds  numeric,
  bookmaker  text,
  stake      numeric,                          -- kolko user vsadil (default = odporucany vklad)
  placed_at  timestamptz default now(),
  unique (user_id, tip_key)
);

alter table public.user_bets enable row level security;

-- user vidi/meni LEN svoje stavky
drop policy if exists "own bets select" on public.user_bets;
create policy "own bets select" on public.user_bets
  for select using (auth.uid() = user_id);

drop policy if exists "own bets insert" on public.user_bets;
create policy "own bets insert" on public.user_bets
  for insert with check (auth.uid() = user_id);

drop policy if exists "own bets update" on public.user_bets;
create policy "own bets update" on public.user_bets
  for update using (auth.uid() = user_id);

drop policy if exists "own bets delete" on public.user_bets;
create policy "own bets delete" on public.user_bets
  for delete using (auth.uid() = user_id);

-- index na rychle joiny podla tip_key
create index if not exists user_bets_tip_key_idx on public.user_bets (tip_key);
