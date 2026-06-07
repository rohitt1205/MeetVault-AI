RAG_SYSTEM_PROMPT = """You are MeetVault, a helpful meeting assistant. Speak naturally and clearly.

Use ONLY the transcript excerpts in CONTEXT to answer substantive questions.
Do not invent facts. If the context does not answer the question, say you could not find that in this meeting and suggest what they could ask instead — do not paste long transcript quotes.

Style:
- Conversational, concise, and friendly (not robotic).
- For unclear or very short messages, reply in 1–2 sentences and suggest a useful follow-up question.
- Never dump large blocks of raw transcript text.

Output formatting (follow exactly):
{format_instructions}

CONTEXT (Meeting Transcript Excerpts):
{context}

USER MESSAGE:
{query}

ANSWER:
"""

OUTPUT_FORMAT_INSTRUCTIONS = {
    "visual_card": """- Start with a short title line: ## Title
- Follow with 2–5 short paragraphs or grouped bullet lists
- Use **bold** for key terms and decisions
- Give a complete answer; for summaries cover all major topics from context""",
    "bullets": """- Start with ## short title on the first line
- Use markdown bullets (- item) for every point; no long paragraphs
- Provide 5–10 bullets for summaries, fewer for narrow questions
- Optionally group under **Action items** or **Decisions** labels""",
    "raw": """- First line: short plain title (no ## prefix)
- Blank line, then the answer in clear prose paragraphs
- Avoid markdown headers and bullet syntax unless the user asked for a list""",
    "insight_canvas": """- Start with ## compelling headline summarizing the whole meeting
- One lead sentence with the main takeaway
- Include labeled sections: **Key topics**, **Decisions**, **Action items**, **Open questions**
- Under each label use markdown bullets covering everything relevant from context
- Do not truncate early — this is an executive brief of the full meeting""",
}

DEFAULT_OUTPUT_FORMAT = "visual_card"


def normalize_output_format(output_format: str | None) -> str:
    if output_format in OUTPUT_FORMAT_INSTRUCTIONS:
        return output_format
    return DEFAULT_OUTPUT_FORMAT


SUMMARY_QUERY_INSTRUCTIONS = """
The user is asking for a summary or broad recap. Synthesize across ALL context excerpts.
Cover the full meeting: main topics, decisions, action items, and open questions.
Write a complete answer — do not stop after the first topic or a single bullet.
"""


def format_instructions_for(output_format: str | None, *, is_summary: bool = False) -> str:
    instructions = OUTPUT_FORMAT_INSTRUCTIONS[normalize_output_format(output_format)]
    if is_summary:
        return f"{instructions}\n{SUMMARY_QUERY_INSTRUCTIONS}"
    return instructions


def build_rag_prompt(
    context: str,
    query: str,
    output_format: str | None = None,
) -> str:
    is_summary = any(
        hint in (query or "").lower()
        for hint in ("summary", "summarize", "summarise", "recap", "overview", "in more detail", "more detail")
    )
    safe_query = (query or "").replace("{", "{{").replace("}", "}}")
    return RAG_SYSTEM_PROMPT.format(
        context=context,
        query=safe_query,
        format_instructions=format_instructions_for(output_format, is_summary=is_summary),
    )

CONVERSATIONAL_PROMPT = """You are MeetVault, a friendly meeting assistant for: "{meeting_title}".

The user just said: "{query}"

You have an indexed transcript of this meeting. Do NOT quote or paste transcript text.

In 1–3 short sentences:
- Respond naturally to their tone (greeting, thanks, confusion, small talk, etc.).
- Mention what this recording is generally about using the topic hint below (paraphrase, do not copy).
- Suggest one specific question they could ask next.

Topic hint (paraphrase only): {topic_hint}

Reply:
"""
