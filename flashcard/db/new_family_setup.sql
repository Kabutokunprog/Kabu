-- フラッシュ暗記: 新しい家族用のデータベースを一度に作るSQL
-- 使い方: 新しく作った Supabase プロジェクトの「SQL Editor」に全文を貼り付けて「Run」
-- (このアプリ専用の表はすべて flash_ で始まります)

create extension if not exists pgcrypto with schema extensions;

-- 家族の合言葉 (ハッシュだけを保存)
create table if not exists public.flash_members (
  role text primary key check (role = 'family'),
  pass_hash text not null,
  created_at timestamptz not null default now()
);

-- 使う人 (息子・娘など)
create table if not exists public.flash_profiles (
  id bigint generated always as identity primary key,
  name text not null,
  emoji text not null default '',
  avatar text not null default '',
  sort int not null default 0,
  created_at timestamptz not null default now()
);

-- 教材
create table if not exists public.flash_decks (
  id bigint generated always as identity primary key,
  profile_id bigint not null references public.flash_profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  title text not null,
  grade text not null default '',
  term text not null default '',
  subject text not null default '',
  card_kind text not null default 'qa' check (card_kind in ('word','qa')),
  source_text text not null default '',
  memo text not null default ''
);
create index if not exists flash_decks_profile on public.flash_decks(profile_id, created_at desc);

-- カード
create table if not exists public.flash_cards (
  id bigint generated always as identity primary key,
  deck_id bigint not null references public.flash_decks(id) on delete cascade,
  position int not null default 0,
  question text not null,
  answer text not null,
  note text not null default '',
  example text not null default '',
  tag text not null default '',
  year int,
  importance int,
  explain text not null default '',
  explain_detail text not null default '',
  explain_choices jsonb not null default '{}'::jsonb,
  needs_regen boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists flash_cards_deck_pos on public.flash_cards(deck_id, position);

-- カードごとの成績・復習
create table if not exists public.flash_progress (
  card_id bigint primary key references public.flash_cards(id) on delete cascade,
  correct_count int not null default 0,
  wrong_count int not null default 0,
  last_result text not null default '',
  last_answered_at timestamptz,
  in_review boolean not null default false,
  review_streak int not null default 0,
  next_due_at timestamptz
);
create index if not exists flash_progress_review on public.flash_progress(in_review, next_due_at);

-- 学習の記録
create table if not exists public.flash_sessions (
  id bigint generated always as identity primary key,
  profile_id bigint not null references public.flash_profiles(id) on delete cascade,
  deck_id bigint references public.flash_decks(id) on delete set null,
  deck_title text not null default '',
  subject text not null default '',
  mode text not null default 'normal',
  total int not null default 0,
  correct int not null default 0,
  wrong_items jsonb not null default '[]'::jsonb,
  started_at timestamptz,
  finished_at timestamptz not null default now()
);
alter table public.flash_sessions add column if not exists answer_mode text not null default 'flip';
create index if not exists flash_sessions_profile on public.flash_sessions(profile_id, finished_at desc);

-- 1問ずつの記録 (科目ごとの成長グラフ用)
create table if not exists public.flash_answers (
  id bigint generated always as identity primary key,
  profile_id bigint not null references public.flash_profiles(id) on delete cascade,
  card_id bigint references public.flash_cards(id) on delete set null,
  deck_id bigint references public.flash_decks(id) on delete set null,
  subject text not null default '',
  correct boolean not null,
  ans_mode text not null default 'flip',
  study_mode text not null default 'normal',
  attempt_no int not null default 1,
  answered_at timestamptz not null default now()
);
create index if not exists flash_answers_profile on public.flash_answers(profile_id, answered_at);

create or replace function public.flash_growth(pid bigint) returns json
language sql stable set search_path = public as $$
  select json_build_object(
    'daily', (select coalesce(json_agg(x order by x.d), '[]'::json) from (
        select subject, ans_mode, (answered_at at time zone 'Asia/Tokyo')::date as d, count(*) as n, count(*) filter (where correct) as ok
        from public.flash_answers where profile_id = pid group by 1, 2, 3) x),
    'attempts', (select coalesce(json_agg(y), '[]'::json) from (
        select subject, ans_mode, least(attempt_no, 5) as a, count(*) as n, count(*) filter (where correct) as ok
        from public.flash_answers where profile_id = pid group by 1, 2, 3) y),
    'since', (select min(answered_at) from public.flash_answers where profile_id = pid)
  );
$$;

-- テスト
create table if not exists public.flash_tests (
  id bigint generated always as identity primary key,
  profile_id bigint not null references public.flash_profiles(id) on delete cascade,
  title text not null default '',
  subject text not null default '',
  deck_ids jsonb not null default '[]'::jsonb,
  questions jsonb not null default '[]'::jsonb,
  memo text not null default '',
  created_at timestamptz not null default now()
);
create index if not exists flash_tests_profile on public.flash_tests(profile_id, created_at desc);

create table if not exists public.flash_test_attempts (
  id bigint generated always as identity primary key,
  test_id bigint not null references public.flash_tests(id) on delete cascade,
  profile_id bigint not null references public.flash_profiles(id) on delete cascade,
  answers jsonb not null default '[]'::jsonb,
  results jsonb not null default '[]'::jsonb,
  score int not null default 0,
  total int not null default 0,
  started_at timestamptz,
  finished_at timestamptz not null default now()
);
create index if not exists flash_test_attempts_test on public.flash_test_attempts(test_id, finished_at desc);
create index if not exists flash_test_attempts_profile on public.flash_test_attempts(profile_id, finished_at desc);

-- 裏で進める作成ジョブと、預かった写真
create table if not exists public.flash_jobs (
  id bigint generated always as identity primary key,
  profile_id bigint not null references public.flash_profiles(id) on delete cascade,
  kind text not null default 'make',
  label text not null default '',
  status text not null default 'uploading',
  params jsonb not null default '{}'::jsonb,
  page_count int not null default 0,
  read_done int not null default 0,
  source_text text not null default '',
  deck_id bigint,
  card_count int not null default 0,
  error text not null default '',
  runner text,
  heartbeat_at timestamptz,
  gen_started_at timestamptz,
  dismissed boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists flash_jobs_profile on public.flash_jobs(profile_id, created_at desc);

create table if not exists public.flash_job_pages (
  job_id bigint not null references public.flash_jobs(id) on delete cascade,
  idx int not null,
  data text not null,
  primary key (job_id, idx)
);

-- 合言葉 (リクエストヘッダ x-flash-pass) から家族かどうかを判定
create or replace function public.flash_role() returns text
language sql stable security definer set search_path = public, extensions as $$
  select m.role from public.flash_members m
  where m.pass_hash = encode(extensions.digest(
    coalesce(nullif(current_setting('request.headers', true), '')::json->>'x-flash-pass', ''), 'sha256'), 'hex')
  limit 1;
$$;

create or replace function public.flash_whoami() returns text
language sql stable security definer set search_path = public as $$ select public.flash_role(); $$;

create or replace function public.flash_is_setup() returns boolean
language sql stable security definer set search_path = public as $$ select exists(select 1 from public.flash_members); $$;

-- 初回だけ: 家族の合言葉を決める (使う人「息子」「娘」も作る。名前はアプリの設定で変えられる)
create or replace function public.flash_setup(family_pass text) returns text
language plpgsql security definer set search_path = public, extensions as $$
begin
  if exists(select 1 from public.flash_members) then return 'already'; end if;
  if length(coalesce(family_pass,'')) < 6 then return 'invalid'; end if;
  insert into public.flash_members(role, pass_hash) values ('family', encode(extensions.digest(family_pass, 'sha256'), 'hex'));
  if not exists(select 1 from public.flash_profiles) then
    insert into public.flash_profiles(name, emoji, sort) values ('息子', '👦', 1), ('娘', '👧', 2);
  end if;
  return 'ok';
end $$;

create or replace function public.flash_change_pass(new_pass text) returns text
language plpgsql security definer set search_path = public, extensions as $$
begin
  if public.flash_role() is null then return 'forbidden'; end if;
  if length(coalesce(new_pass,'')) < 6 then return 'invalid'; end if;
  update public.flash_members set pass_hash = encode(extensions.digest(new_pass, 'sha256'), 'hex') where role = 'family';
  return 'ok';
end $$;

-- 合言葉が正しいときだけ読み書きできるようにする
alter table public.flash_members enable row level security;
alter table public.flash_profiles enable row level security;
alter table public.flash_decks enable row level security;
alter table public.flash_cards enable row level security;
alter table public.flash_progress enable row level security;
alter table public.flash_sessions enable row level security;
alter table public.flash_tests enable row level security;
alter table public.flash_test_attempts enable row level security;
alter table public.flash_jobs enable row level security;
alter table public.flash_job_pages enable row level security;
alter table public.flash_answers enable row level security;
revoke all on public.flash_members from anon, authenticated;

create policy flash_profiles_family on public.flash_profiles for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_decks_family on public.flash_decks for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_cards_family on public.flash_cards for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_progress_family on public.flash_progress for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_sessions_family on public.flash_sessions for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_tests_family on public.flash_tests for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_test_attempts_family on public.flash_test_attempts for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_jobs_family on public.flash_jobs for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_answers_family on public.flash_answers for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_job_pages_family on public.flash_job_pages for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
