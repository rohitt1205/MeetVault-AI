class ChunkService:

    @staticmethod
    def chunk_transcript(transcript, chunk_size=2):

        chunks = []

        current_chunk = []

        for item in transcript:

            current_chunk.append(item)

            if len(current_chunk) >= chunk_size:

                chunk_text = " ".join(
                    [entry["text"] for entry in current_chunk]
                )

                chunks.append({
                    "chunk_id": len(chunks) + 1,
                    "text": chunk_text,
                    "metadata": current_chunk
                })

                current_chunk = []

        if current_chunk:

            chunk_text = " ".join(
                [entry["text"] for entry in current_chunk]
            )

            chunks.append({
                "chunk_id": len(chunks) + 1,
                "text": chunk_text,
                "metadata": current_chunk
            })

        return chunks