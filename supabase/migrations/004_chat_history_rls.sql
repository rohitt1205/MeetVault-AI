-- Ensure authenticated users can read/write only their own chat_history rows.

alter table public.chat_history enable row level security;

drop policy if exists chat_history_select_own on public.chat_history;
create policy chat_history_select_own
  on public.chat_history
  for select
  to authenticated
  using (auth.uid() = user_id);

drop policy if exists chat_history_insert_own on public.chat_history;
create policy chat_history_insert_own
  on public.chat_history
  for insert
  to authenticated
  with check (auth.uid() = user_id);

drop policy if exists chat_history_update_own on public.chat_history;
create policy chat_history_update_own
  on public.chat_history
  for update
  to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists chat_history_delete_own on public.chat_history;
create policy chat_history_delete_own
  on public.chat_history
  for delete
  to authenticated
  using (auth.uid() = user_id);
