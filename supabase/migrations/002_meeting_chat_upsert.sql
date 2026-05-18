-- PostgREST upsert needs a named UNIQUE constraint (partial indexes are unreliable).
-- Safe to re-run: dedupes rows, then replaces the partial unique index with a constraint.

alter table public.chat_history
  add column if not exists status text not null default 'ready',
  add column if not exists messages jsonb not null default '[]'::jsonb;

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

alter table public.chat_history
  drop constraint if exists chat_history_user_meeting_key;

alter table public.chat_history
  add constraint chat_history_user_meeting_key unique (user_id, meeting_id);

create index if not exists chat_history_user_meeting_idx
  on public.chat_history (user_id, meeting_id);
