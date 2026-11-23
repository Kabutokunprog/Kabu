-- フラッシュ暗記: 家族共通の合言葉 + 学習者(息子・娘)ごとのプロフィールに変更
-- (001 は Supabase に適用済み。この 002 は Supabase の SQL Editor で実行する)
drop policy if exists flash_decks_read on public.flash_decks;
drop policy if exists flash_decks_ins on public.flash_decks;
drop policy if exists flash_decks_upd on public.flash_decks;
drop policy if exists flash_decks_del on public.flash_decks;
drop policy if exists flash_cards_read on public.flash_cards;
drop policy if exists flash_cards_ins on public.flash_cards;
drop policy if exists flash_cards_upd on public.flash_cards;
drop policy if exists flash_cards_del on public.flash_cards;
drop policy if exists flash_progress_read on public.flash_progress;
drop policy if exists flash_progress_ins on public.flash_progress;
drop policy if exists flash_progress_upd on public.flash_progress;
drop policy if exists flash_progress_del on public.flash_progress;
drop function if exists public.flash_setup(text, text);
drop function if exists public.flash_change_pass(text, text);

delete from public.flash_members;
alter table public.flash_members drop constraint if exists flash_members_role_check;
alter table public.flash_members add constraint flash_members_role_check check (role = 'family');

create table if not exists public.flash_profiles (
  id bigint generated always as identity primary key,
  name text not null,
  emoji text not null default '',
  sort int not null default 0,
  created_at timestamptz not null default now()
);
alter table public.flash_profiles enable row level security;

alter table public.flash_decks add column if not exists profile_id bigint not null references public.flash_profiles(id) on delete cascade;
create index if not exists flash_decks_profile on public.flash_decks(profile_id, created_at desc);

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

drop policy if exists flash_profiles_all on public.flash_profiles;
drop policy if exists flash_decks_all on public.flash_decks;
drop policy if exists flash_cards_all on public.flash_cards;
drop policy if exists flash_progress_all on public.flash_progress;
create policy flash_profiles_all on public.flash_profiles for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_decks_all on public.flash_decks for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_cards_all on public.flash_cards for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
create policy flash_progress_all on public.flash_progress for all using ((select public.flash_role()) is not null) with check ((select public.flash_role()) is not null);
