-- Run in Supabase SQL editor (or via CLI) before using meeting-scoped chats.
-- Safe to re-run: cleans duplicates, then adds columns + unique index.

alter table public.chat_history
  add column if not exists status text not null default 'ready',
  add column if not exists messages jsonb not null default '[]'::jsonb;

-- Legacy workspace rows (old SharePoint id format) are not used for meeting chats.
delete from public.chat_history
where meeting_id like 'sharepoint-%';

-- Keep the newest row per (user_id, meeting_id); drop older duplicates.
delete from public.chat_history
where id in (
  select id
  from (
    select
      id,
      row_number() over (
        partition by user_id, meeting_id
        order by created_at desc nulls last, id desc
      ) as row_num
    from public.chat_history
    where meeting_id is not null
  ) ranked
  where row_num > 1
);

drop index if exists public.chat_history_user_meeting_unique;

create unique index chat_history_user_meeting_unique
  on public.chat_history (user_id, meeting_id)
  where meeting_id is not null;

create index if not exists chat_history_user_meeting_idx
  on public.chat_history (user_id, meeting_id);
