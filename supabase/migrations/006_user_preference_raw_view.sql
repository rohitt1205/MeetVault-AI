-- Optional raw-mode display preference (plain text vs rendered markdown).
-- Safe to run more than once.

alter table public.user_preferences
  add column if not exists raw_view_mode text not null default 'markdown';

alter table public.user_preferences
  drop constraint if exists user_preferences_raw_view_mode_check;

alter table public.user_preferences
  add constraint user_preferences_raw_view_mode_check
  check (raw_view_mode in ('plain', 'markdown'));
