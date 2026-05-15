class TranscriptService:

    @staticmethod
    def normalize_transcript(raw_transcript):

        normalized_transcript = []

        for item in raw_transcript:

            normalized_transcript.append({
                "speaker": item.get("speaker"),
                "timestamp": item.get("timestamp"),
                "text": item.get("text")
            })

        return normalized_transcript