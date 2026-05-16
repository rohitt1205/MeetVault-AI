class ChunkService:
    @staticmethod
    def chunk_transcript(
        transcript: list[dict],
        *,
        meeting_id: str,
        meeting_title: str,
        source_type: str,
        max_words: int = 180,
        overlap_turns: int = 1,
    ) -> list[dict]:
        chunks = []
        current_turns = []
        current_word_count = 0

        def emit_chunk():
            if not current_turns:
                return

            chunk_index = len(chunks) + 1
            chunk_text = "\n".join(
                f"{turn.get('timestamp') or ''} {turn.get('speaker')}: {turn.get('text')}"
                for turn in current_turns
            ).strip()

            chunks.append({
                "chunk_id": f"{meeting_id}:{chunk_index}",
                "chunk_index": chunk_index,
                "meeting_id": meeting_id,
                "meeting_title": meeting_title,
                "source_type": source_type,
                "text": chunk_text,
                "metadata": {
                    "speaker_start": current_turns[0].get("speaker"),
                    "speaker_end": current_turns[-1].get("speaker"),
                    "start_timestamp": current_turns[0].get("timestamp"),
                    "end_timestamp": current_turns[-1].get("end_timestamp")
                    or current_turns[-1].get("timestamp"),
                    "turn_count": len(current_turns),
                },
            })

        for turn in transcript:
            text = turn.get("text") or ""
            turn_word_count = len(text.split())

            if current_turns and current_word_count + turn_word_count > max_words:
                emit_chunk()
                current_turns = current_turns[-overlap_turns:] if overlap_turns else []
                current_word_count = sum(
                    len((existing_turn.get("text") or "").split())
                    for existing_turn in current_turns
                )

            current_turns.append(turn)
            current_word_count += turn_word_count

        emit_chunk()
        return chunks
