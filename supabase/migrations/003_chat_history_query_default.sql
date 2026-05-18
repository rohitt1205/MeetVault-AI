-- Meeting chats no longer store the last search string in query (see messages jsonb).
-- Keep legacy column compatible for inserts that omit query.

alter table public.chat_history
  alter column query set default '';

update public.chat_history
set query = ''
where query is null;
