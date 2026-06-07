-- Stores per-user presentation preferences for AI answers.
-- Safe to run more than once.

create table if not exists public.user_preferences (
  user_id uuid primary key references auth.users(id) on delete cascade,
  output_format text not null default 'visual_card',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint user_preferences_output_format_check
    check (output_format in ('visual_card', 'bullets', 'raw', 'insight_canvas'))
);

alter table public.user_preferences enable row level security;

grant select, insert, update, delete on public.user_preferences to authenticated;

drop policy if exists user_preferences_select_own on public.user_preferences;
create policy user_preferences_select_own
  on public.user_preferences
  for select
  to authenticated
  using (auth.uid() = user_id);

drop policy if exists user_preferences_insert_own on public.user_preferences;
create policy user_preferences_insert_own
  on public.user_preferences
  for insert
  to authenticated
  with check (auth.uid() = user_id);

drop policy if exists user_preferences_update_own on public.user_preferences;
create policy user_preferences_update_own
  on public.user_preferences
  for update
  to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists user_preferences_delete_own on public.user_preferences;
create policy user_preferences_delete_own
  on public.user_preferences
  for delete
  to authenticated
  using (auth.uid() = user_id);
