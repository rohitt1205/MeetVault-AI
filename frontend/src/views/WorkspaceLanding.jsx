export default function WorkspaceLanding({ onOpenMeetings }) {
  return (
    <section className="workspace-landing" aria-label="Workspace home">
      <p className="eyebrow">Workspace</p>
      <h2>Your meeting intelligence hub</h2>
      <p>
        Pick a meeting chat from the sidebar, or open <strong>Show Meetings</strong> to browse Teams
        recordings and start a new conversation.
      </p>
      <button className="ghost-button" type="button" onClick={onOpenMeetings}>
        Browse meetings
      </button>
    </section>
  )
}
