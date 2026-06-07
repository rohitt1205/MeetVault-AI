import re
import json

from app.mcp.mcp_manager import MCPManager
from app.mcp.github import github_connector
from app.mcp.outlook import outlook_connector
from app.mcp.calendar import calendar_connector
from app.mcp.slack import slack_connector
from app.mcp.salesforce import salesforce_connector
from app.mcp.connection_store import MCPConnectionStore
from app.rag.llm import generate_answer, generate_conversational_answer
from app.rag.prompts import CONVERSATIONAL_PROMPT, RAG_SYSTEM_PROMPT, WORK_SUMMARY_PROMPT
from app.services.answer_service import AnswerService
from app.services.chroma_service import ChromaService, MICROSOFT_SOURCE_TYPES
from app.services.embedding_service import EmbeddingService

QUERYABLE_SOURCE_TYPES = MICROSOFT_SOURCE_TYPES | {"rag_manual_ingest"}

STOPWORDS = {
    "a",
    "an",
    "and",
    "about",
    "ask",
    "brief",
    "for",
    "from",
    "give",
    "in",
    "is",
    "me",
    "of",
    "on",
    "please",
    "recording",
    "recordings",
    "summary",
    "summarize",
    "summarise",
    "the",
    "this",
    "to",
    "video",
    "what",
}
LOW_SIGNAL_WORDS = {"ah", "hmm", "okay", "ok", "um", "uh", "yeah", "yes", "you"}

JIRA_KEYWORDS = {
    "jira",
    "ticket",
    "tickets",
    "assigned",
    "task",
    "tasks",
    "issue",
    "issues",
    "sprint",
}
GITHUB_KEYWORDS = {
    "github",
    "pr",
    "prs",
    "pull request",
    "pull requests",
    "review",
    "reviews",
    "issue",
    "issues",
    "repo",
    "repos",
    "repository",
    "repositories",
}
OUTLOOK_KEYWORDS = {
    "outlook",
    "email",
    "emails",
    "mail",
    "mails",
    "inbox",
    "message",
    "messages",
}
CALENDAR_KEYWORDS = {
    "calendar",
    "meeting",
    "meetings",
    "schedule",
    "appointment",
    "appointments",
    "deadline",
    "deadlines",
    "sprint event",
    "sprint events",
    "availability",
}
SLACK_KEYWORDS = {
    "slack",
    "message",
    "messages",
    "chat",
    "mention",
    "mentions",
    "thread",
    "threads",
}
SALESFORCE_KEYWORDS = {
    "salesforce",
    "lead",
    "leads",
    "opportunity",
    "opportunities",
    "deal",
    "deals",
    "customer",
    "customers",
    "client",
    "clients",
    "pipeline",
}

EXPLICIT_PROVIDER_TOKENS = {
    "jira": {"jira"},
    "github": {"github", "repo", "repos", "repository", "repositories", "pull request", "pull requests", "pr", "prs", "review", "reviews", "issue", "issues"},
    "slack": {"slack"},
    "outlook": {"outlook"},
    "calendar": {"calendar"},
    "salesforce": {"salesforce"},
    "notion": {"notion"},
    "gmail": {"gmail"},
}

NOT_FOUND_ANSWER = "Information not found in the provided context."


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9]+", (value or "").lower())
        if len(token) > 1 and token not in STOPWORDS
    }


def _source_from_result(
    *,
    index: int,
    document: str,
    retrieved_ids: list,
    retrieved_distances: list,
    retrieved_metadatas: list,
) -> dict:
    return {
        "chunk_id": (
            retrieved_ids[index]
            if index < len(retrieved_ids)
            else f"source-{index + 1}"
        ),
        "distance": (
            retrieved_distances[index]
            if index < len(retrieved_distances)
            else None
        ),
        "text": document,
        "metadata": (
            retrieved_metadatas[index]
            if index < len(retrieved_metadatas)
            else {}
        ),
    }


def _score_source(query: str, source: dict) -> float:
    metadata = source.get("metadata") or {}
    title = metadata.get("meeting_title") or ""
    source_type = metadata.get("source_type") or ""
    text = source.get("text") or ""
    distance = source.get("distance")

    query_tokens = _tokens(query)
    title_tokens = _tokens(title)
    text_tokens = _tokens(text)

    semantic_score = 0.0
    if isinstance(distance, (float, int)):
        semantic_score = 1 / (1 + max(float(distance), 0.0))

    title_overlap = len(query_tokens & title_tokens)
    text_overlap = len(query_tokens & text_tokens)
    compact_query = " ".join(
        token
        for token in re.findall(r"[a-zA-Z0-9]+", query.lower())
        if token not in STOPWORDS
    )
    compact_title = " ".join(re.findall(r"[a-zA-Z0-9]+", title.lower()))
    phrase_bonus = 3.0 if compact_query and compact_query in compact_title else 0.0
    source_bonus = (
        0.2
        if source_type in {"sharepoint_recording_transcription", "graph_recording_transcription"}
        else 0.0
    )

    return (
        semantic_score
        + (title_overlap * 2.5)
        + (text_overlap * 0.6)
        + phrase_bonus
        + source_bonus
    )


def _is_informative_text(text: str) -> bool:
    tokens = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    meaningful_tokens = [
        token
        for token in tokens
        if len(token) > 2 and token not in LOW_SIGNAL_WORDS
    ]
    if len(meaningful_tokens) < 5:
        return False

    unique_ratio = len(set(meaningful_tokens)) / len(meaningful_tokens)
    return unique_ratio >= 0.25


def _rank_sources(query: str, sources: list[dict], limit: int = 5) -> list[dict]:
    ranked = sorted(
        sources,
        key=lambda source: _score_source(query, source),
        reverse=True,
    )
    if not ranked:
        return []

    top_meeting_id = (ranked[0].get("metadata") or {}).get("meeting_id")
    if top_meeting_id:
        same_meeting = [
            source
            for source in ranked
            if (source.get("metadata") or {}).get("meeting_id") == top_meeting_id
        ]
        other_meetings = [
            source
            for source in ranked
            if (source.get("metadata") or {}).get("meeting_id") != top_meeting_id
        ]
        ranked = [*same_meeting, *other_meetings]

    return ranked[:limit]


def _is_queryable_source(source: dict) -> bool:
    metadata = source.get("metadata") or {}
    return (
        metadata.get("source_type") in QUERYABLE_SOURCE_TYPES
        and _is_informative_text(source.get("text") or "")
    )


def _is_not_found_answer(answer: str) -> bool:
    normalized = (answer or "").strip().lower()
    if normalized == NOT_FOUND_ANSWER.lower():
        return True
    return any(
        phrase in normalized
        for phrase in (
            "information not found",
            "do not contain the answer",
            "does not contain the answer",
            "not found in the provided context",
        )
    )


def _meeting_title_from_sources(sources: list[dict]) -> str:
    for source in sources:
        title = (source.get("metadata") or {}).get("meeting_title")
        if title:
            return str(title)
    return "this meeting"


def _topic_hint_from_sources(sources: list[dict]) -> str:
    if not sources:
        return "a recorded meeting conversation"

    text = re.sub(r"\s+", " ", (sources[0].get("text") or "").strip())
    if not text:
        return "a recorded meeting conversation"

    sentences = AnswerService._split_sentences(text)
    if sentences:
        return AnswerService._truncate_excerpt(sentences[0], limit=220)
    return AnswerService._truncate_excerpt(text, limit=220)


def _looks_like_transcript_dump(answer: str) -> bool:
    normalized = (answer or "").strip()
    if len(normalized) > 700:
        return True
    if normalized.count("\n- ") >= 2 and len(normalized) > 400:
        return True
    return False


def _generate_conversational_response(user_query: str, sources: list[dict]) -> dict:
    title = _meeting_title_from_sources(sources)
    topic_hint = _topic_hint_from_sources(sources)
    safe_query = (user_query or "").replace("{", "{{").replace("}", "}}")
    safe_hint = topic_hint.replace("{", "{{").replace("}", "}}")
    prompt = CONVERSATIONAL_PROMPT.format(
        meeting_title=title,
        query=safe_query,
        topic_hint=safe_hint,
    )

    llm_error = None
    try:
        answer = generate_conversational_answer(
            prompt,
            query=user_query,
            context=topic_hint,
        )
        if _is_not_found_answer(answer) or _looks_like_transcript_dump(answer):
            raise ValueError("Conversational model returned unusable text")
        answer_mode = "conversational"
    except Exception as exc:
        llm_error = str(exc)
        answer = (
            f"Hey — I'm MeetVault, your assistant for **{title}**. "
            "Ask me to summarize the meeting, list the main tips, or find a specific topic."
        )
        answer_mode = "conversational_fallback"

    return {
        "query": user_query,
        "answer": answer,
        "answer_mode": answer_mode,
        "llm_error": llm_error,
        "sources": sources[:2],
    }


def _detect_tool_calls_with_llm(
    query: str,
    active_tools: list[dict],
) -> list[dict]:
    if not active_tools:
        return []
        
    schemas = []
    for tool in active_tools:
        schemas.append({
            "provider": tool["provider"],
            "tool_name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"]
        })
        
    prompt = f"""You are MeetVault's Query Routing Agent. Determine which of the available enterprise tools (if any) are needed to answer the user query.
    
Available Tools:
{json.dumps(schemas, indent=2)}

User Query: "{query}"

If a tool is relevant:
Return a JSON object with key "tool_calls" listing the tools to run and their extracted parameters.
Return ONLY valid JSON. No conversational text. No markdown formatting. If no tools match, return:
{{"tool_calls": []}}

Example Output:
{{"tool_calls": [{{"provider": "jira", "tool_name": "get_jira_tickets", "arguments": {{}}}}]}}
"""
    try:
        from app.rag.llm import generate_answer
        response_text = generate_answer(prompt, query=query, context="Query routing intent detection")
        if "```" in response_text:
            cleaned = re.search(r"```(?:json)?\s*(.*?)\s*```", response_text, re.DOTALL)
            if cleaned:
                response_text = cleaned.group(1)
        response_text = response_text.strip()
        data = json.loads(response_text)
        return data.get("tool_calls", [])
    except Exception as e:
        print(f"LLM tool detection failed, falling back to keyword routing: {e}")
        return []


def _detect_tool_calls_fallback(
    query: str,
    active_tools: list[dict],
) -> list[dict]:
    query_tokens = _tokens(query)
    is_work_summary = query.strip().lower() == "summarize my work today"
    
    explicit_providers = _explicit_provider_hints(query)
    
    matched = []
    for tool in active_tools:
        provider = tool["provider"]
        tool_name = tool["name"]
        
        if explicit_providers and provider.replace("mcp:", "", 1) not in explicit_providers:
            continue
            
        if is_work_summary:
            matched.append({"provider": provider, "tool_name": tool_name, "arguments": {}})
            continue
            
        if provider == "jira" and (query_tokens & JIRA_KEYWORDS):
            matched.append({"provider": provider, "tool_name": tool_name, "arguments": {}})
        elif provider == "github" and (query_tokens & GITHUB_KEYWORDS):
            matched.append({"provider": provider, "tool_name": tool_name, "arguments": {}})
        elif provider == "slack" and (query_tokens & SLACK_KEYWORDS):
            matched.append({"provider": provider, "tool_name": tool_name, "arguments": {}})
        elif provider == "salesforce" and (query_tokens & SALESFORCE_KEYWORDS):
            matched.append({"provider": provider, "tool_name": tool_name, "arguments": {}})
        elif provider == "outlook" and (query_tokens & OUTLOOK_KEYWORDS):
            matched.append({"provider": provider, "tool_name": tool_name, "arguments": {}})
        elif provider == "calendar" and (query_tokens & CALENDAR_KEYWORDS):
            matched.append({"provider": provider, "tool_name": tool_name, "arguments": {}})
        elif provider.startswith("mcp:"):
            desc_tokens = _tokens(tool.get("description", "")) | _tokens(tool_name)
            if query_tokens & desc_tokens:
                matched.append({"provider": provider, "tool_name": tool_name, "arguments": {}})
                
    return matched


def _explicit_provider_hints(query: str) -> set[str]:
    lowered = (query or "").lower()
    query_tokens = _tokens(query)
    hints = set()

    # Explicit provider mentions always win.
    for provider, tokens in EXPLICIT_PROVIDER_TOKENS.items():
        if query_tokens & tokens:
            hints.add(provider)

    # Natural-language service hints when the provider name itself is omitted.
    jira_hints = (
        "assigned to me" in lowered
        or "my tickets" in lowered
        or "my ticket" in lowered
        or "jira ticket" in lowered
        or "jira tickets" in lowered
        or "jira issue" in lowered
        or "jira issues" in lowered
        or "due date" in lowered
        or "deadline" in lowered
    )
    github_hints = (
        "repo" in lowered
        or "repos" in lowered
        or "repository" in lowered
        or "repositories" in lowered
        or "pull request" in lowered
        or "pull requests" in lowered
        or " pr" in f" {lowered}"
        or "prs" in lowered
        or "review" in lowered
        or "issues" in lowered
        or "issue" in lowered
    )
    slack_hints = (
        "slack message" in lowered
        or "slack messages" in lowered
        or "slack mention" in lowered
        or "slack mentions" in lowered
        or "thread" in lowered
        or "chat" in lowered
    )
    outlook_hints = (
        "email" in lowered
        or "emails" in lowered
        or "mail" in lowered
        or "inbox" in lowered
    )
    calendar_hints = (
        "calendar" in lowered
        or "meeting" in lowered
        or "meetings" in lowered
        or "schedule" in lowered
        or "appointment" in lowered
    )
    salesforce_hints = (
        "salesforce" in lowered
        or "lead" in lowered
        or "opportunity" in lowered
        or "pipeline" in lowered
    )

    if not hints:
        if jira_hints and "github" not in lowered:
            hints.add("jira")
        elif slack_hints:
            hints.add("slack")
        elif github_hints:
            hints.add("github")
        elif outlook_hints:
            hints.add("outlook")
        elif calendar_hints:
            hints.add("calendar")
        elif salesforce_hints:
            hints.add("salesforce")

    return hints


def _filter_tool_calls_by_provider(
    tool_calls: list[dict],
    providers: set[str],
) -> list[dict]:
    if not providers:
        return tool_calls
    return [
        call
        for call in tool_calls
        if (call.get("provider") or "").replace("mcp:", "", 1) in providers
    ]


def _get_mcp_context(
    user_query: str,
    user_key: str,
    graph_jwt: str | None = None,
    supabase_jwt: str | None = None,
) -> tuple[str, list[dict], bool]:
    """
    Analyzes the query and pulls context from connected tools dynamically using the ToolRegistry.
    """
    is_work_summary = user_query.strip().lower() == "summarize my work today"
    
    from app.mcp.tool_registry import MCPToolRegistry
    active_tools = MCPToolRegistry.get_active_tools(user_key, supabase_jwt)
    explicit_providers = _explicit_provider_hints(user_query)
    
    if explicit_providers:
        tool_calls = _detect_tool_calls_with_llm(user_query, active_tools)
        if not tool_calls:
            tool_calls = _detect_tool_calls_fallback(user_query, active_tools)
        tool_calls = _filter_tool_calls_by_provider(tool_calls, explicit_providers)
    else:
        tool_calls = _detect_tool_calls_with_llm(user_query, active_tools)
        if not tool_calls:
            tool_calls = _detect_tool_calls_fallback(user_query, active_tools)
        
    context_parts = []
    mcp_sources = []
    
    seen_calls = set()
    deduped_tool_calls = []
    for call in tool_calls:
        call_key = (call.get("provider"), call.get("tool_name"))
        if call_key not in seen_calls:
            seen_calls.add(call_key)
            deduped_tool_calls.append(call)
            
    for call in deduped_tool_calls:
        provider = call.get("provider")
        tool_name = call.get("tool_name")
        arguments = call.get("arguments") or {}
        
        try:
            result = MCPManager.execute_tool(
                provider, tool_name, arguments, user_key, graph_jwt, supabase_jwt
            )
            
            formatted_text = f"Result of {provider}:{tool_name} execution:\n{json.dumps(result, indent=2)}"
            
            if provider == "jira" and tool_name == "get_jira_tickets":
                if isinstance(result, list) and result:
                    ticket_str = "\n".join(
                        f"- [{t['ticket_id']}] {t['summary']} (Status: {t['status']}"
                        + (f", Due: {t['due_date']}" if t.get("due_date") else "")
                        + ")"
                        for t in result
                    )
                    formatted_text = f"### Jira Tasks Assigned to Me:\n{ticket_str}"
                else:
                    formatted_text = "### Jira Tasks Assigned to Me:\nNo open tickets found."
                    
            elif provider == "github":
                if tool_name == "get_github_issues":
                    if isinstance(result, list) and result:
                        formatted_text = "### GitHub Assigned Issues:\n" + "\n".join(
                            f"- #{i['issue_id']} {i['title']} ({i['repo']})" for i in result
                        )
                    else:
                        formatted_text = "### GitHub Assigned Issues:\nNo open issues."
                elif tool_name == "get_github_prs":
                    if isinstance(result, list) and result:
                        formatted_text = "### GitHub Pull Requests:\n" + "\n".join(
                            f"- #{p['pr_id']} {p['title']} (Status: {p['status']})" for p in result
                        )
                    else:
                        formatted_text = "### GitHub Pull Requests:\nNo open pull requests."
                elif tool_name == "get_github_reviews":
                    if isinstance(result, list) and result:
                        formatted_text = "### GitHub PRs Awaiting Review:\n" + "\n".join(
                            f"- #{r['pr_id']} {r['title']}" for r in result
                        )
                    else:
                        formatted_text = "### GitHub PRs Awaiting Review:\nNo pending reviews."
                elif tool_name == "get_github_repositories":
                    if isinstance(result, list) and result:
                        formatted_text = "### GitHub Repositories:\n" + "\n".join(
                            f"- {repo['full_name']} ({repo['url']})" for repo in result
                        )
                    else:
                        formatted_text = "### GitHub Repositories:\nNo accessible repositories found."
                        
            elif provider == "slack" and tool_name == "get_slack_mentions":
                if isinstance(result, list) and result:
                    mention_str = "\n".join(
                        f"- From @{m['user']} in #{m['channel']}: {m['text']}"
                        for m in result
                    )
                    formatted_text = f"### Slack Mentions & Messages:\n{mention_str}"
                else:
                    formatted_text = "### Slack Mentions & Messages:\nNo recent mentions found."
                    
            elif provider == "salesforce" and tool_name == "get_salesforce_opportunities":
                opps = result.get("opportunities", []) if isinstance(result, dict) else []
                leads = result.get("leads", []) if isinstance(result, dict) else []
                parts = []
                if opps:
                    parts.append(
                        "Opportunities:\n"
                        + "\n".join(
                            f"- {o['name']} (Value: ${o['amount']}, Stage: {o['stage']})"
                            for o in opps
                        )
                    )
                if leads:
                    parts.append(
                        "Leads:\n"
                        + "\n".join(
                            f"- {l['name']} (Company: {l['company']}, Status: {l['status']})"
                            for l in leads
                        )
                    )
                if parts:
                    formatted_text = "### Salesforce Customer Context:\n" + "\n\n".join(parts)
                else:
                    formatted_text = "### Salesforce Customer Context:\nNo opportunities or leads."
                    
            elif provider == "outlook" and tool_name == "get_outlook_emails":
                unread = result.get("unread_important", []) if isinstance(result, dict) else []
                flagged = result.get("flagged", []) if isinstance(result, dict) else []
                action = result.get("action_required", []) if isinstance(result, dict) else []
                parts = []
                if unread:
                    parts.append(
                        "Unread Important Emails:\n"
                        + "\n".join(f"- From: {e['from']} | Subject: {e['subject']}" for e in unread)
                    )
                if flagged:
                    parts.append(
                        "Flagged Emails:\n"
                        + "\n".join(f"- From: {e['from']} | Subject: {e['subject']}" for e in flagged)
                    )
                if action:
                    parts.append(
                        "Action Required / Follow-up Emails:\n"
                        + "\n".join(f"- From: {e['from']} | Subject: {e['subject']}" for e in action)
                    )
                if parts:
                    formatted_text = "### Outlook Emails:\n" + "\n\n".join(parts)
                else:
                    formatted_text = "### Outlook Emails:\nNo urgent emails."
                    
            elif provider == "calendar" and tool_name == "get_calendar_events":
                meetings = result.get("upcoming_meetings", []) if isinstance(result, dict) else []
                deadlines = result.get("deadlines", []) if isinstance(result, dict) else []
                parts = []
                if meetings:
                    parts.append(
                        "Upcoming Meetings:\n"
                        + "\n".join(f"- {m['subject']} (Organizer: {m['organizer']}, Start: {m['start']})" for m in meetings)
                    )
                if deadlines:
                    parts.append(
                        "Upcoming Deadlines:\n"
                        + "\n".join(f"- {d['subject']} (Due: {d['due_date']})" for d in deadlines)
                    )
                if parts:
                    formatted_text = "### Calendar Schedule:\n" + "\n\n".join(parts)
                else:
                    formatted_text = "### Calendar Schedule:\nNo upcoming events."

            context_parts.append(formatted_text)
            
            source_type = f"mcp_{provider.split(':')[0]}"
            mcp_sources.append({
                "chunk_id": f"mcp-{provider}-{tool_name}-live",
                "distance": 0.0,
                "text": f"Retrieved tool data from {provider}:{tool_name}.",
                "metadata": {
                    "source_type": source_type,
                    "meeting_title": f"{provider} integration",
                    "meeting_id": f"mcp-{provider}-{tool_name}-live",
                }
            })
            
        except Exception as e:
            print(f"Error executing tool {provider}:{tool_name}: {e}")
            context_parts.append(f"### {provider.capitalize()}:\nFailed to retrieve data from {provider} ({e}).")

    if is_work_summary:
        conns = MCPManager.get_all_connections(user_key, graph_jwt, supabase_jwt)
        for standard in ["jira", "github", "slack", "outlook", "calendar"]:
            conn_state = conns.get(standard, {})
            if not conn_state.get("connected"):
                if standard == "jira":
                    context_parts.append("### Jira Tasks Assigned to Me:\nJira is not connected. Connect Jira in Settings.")
                elif standard == "github":
                    context_parts.append("### GitHub Workspace:\nGitHub is not connected. Connect GitHub in Settings.")
                elif standard == "slack":
                    context_parts.append("### Slack Mentions & Messages:\nSlack is not connected. Connect Slack in Settings.")
                elif standard == "outlook":
                    context_parts.append("### Outlook Emails:\nOutlook is not connected. Sign in with Microsoft Graph scopes.")
                elif standard == "calendar":
                    context_parts.append("### Calendar Schedule:\nCalendar is not connected. Sign in with Microsoft Graph scopes.")

    return "\n\n---\n\n".join(context_parts), mcp_sources, is_work_summary


def retrieve_and_answer(
    user_query: str,
    meeting_id: str | None = None,
    user_key: str = "demo",
    graph_jwt: str | None = None,
    supabase_jwt: str | None = None,
) -> dict:
    """
    Retrieves relevant transcript chunks from ChromaDB and generates a grounded answer.
    """
    explicit_providers = _explicit_provider_hints(user_query)
    mcp_context, mcp_sources, is_work_summary = _get_mcp_context(
        user_query,
        user_key,
        graph_jwt=graph_jwt,
        supabase_jwt=supabase_jwt,
    )

    if is_work_summary:
        prompt = WORK_SUMMARY_PROMPT.format(context=mcp_context)
        llm_error = None
        try:
            answer = generate_answer(prompt, query=user_query, context=mcp_context)
            answer_mode = "work_summary"
        except Exception as exc:
            llm_error = str(exc)
            answer = (
                "Here is the retrieved status dashboard:\n\n"
                f"{mcp_context}\n\n"
                "*(Note: The LLM synthesis failed, displaying raw context above.)*"
            )
            answer_mode = "work_summary_fallback"

        return {
            "query": user_query,
            "answer": answer,
            "answer_mode": answer_mode,
            "llm_error": llm_error,
            "sources": mcp_sources,
        }

    query_embedding = EmbeddingService.generate_query_embedding(user_query)

    results = ChromaService.query_embeddings(
        query_embedding,
        meeting_id=meeting_id,
        n_results=5,
        candidate_pool_size=80,
        allowed_source_types=QUERYABLE_SOURCE_TYPES,
    )

    retrieved_documents = results.get("documents", [[]])[0]
    retrieved_metadatas = results.get("metadatas", [[]])[0]
    retrieved_distances = results.get("distances", [[]])[0]
    retrieved_ids = results.get("ids", [[]])[0]

    if not retrieved_documents:
        if mcp_context:
            safe_query = user_query.replace("{", "{{").replace("}", "}}")
            final_prompt = RAG_SYSTEM_PROMPT.format(
                context=mcp_context,
                query=safe_query,
            )
            llm_error = None
            try:
                answer = generate_answer(
                    final_prompt, query=user_query, context=mcp_context
                )
                answer_mode = "mcp_only_answer"
            except Exception as exc:
                llm_error = str(exc)
                answer = f"I found the following tool context:\n\n{mcp_context}"
                answer_mode = "mcp_only_fallback"

            return {
                "query": user_query,
                "answer": answer,
                "answer_mode": answer_mode,
                "llm_error": llm_error,
                "sources": mcp_sources,
            }

        return {
            "query": user_query,
            "answer": "I don't have any meeting transcripts or connected tool context to answer that.",
            "answer_mode": "no_context",
            "sources": [],
        }

    candidate_sources = [
        _source_from_result(
            index=index,
            document=document,
            retrieved_ids=retrieved_ids,
            retrieved_distances=retrieved_distances,
            retrieved_metadatas=retrieved_metadatas,
        )
        for index, document in enumerate(retrieved_documents)
    ]
    sources = _rank_sources(
        user_query,
        [source for source in candidate_sources if _is_queryable_source(source)],
    )

    all_sources = [*sources, *mcp_sources]

    if explicit_providers and mcp_context:
        safe_query = user_query.replace("{", "{{").replace("}", "}}")
        final_prompt = RAG_SYSTEM_PROMPT.format(
            context=mcp_context,
            query=safe_query,
        )
        llm_error = None
        try:
            answer = generate_answer(
                final_prompt, query=user_query, context=mcp_context
            )
            answer_mode = "mcp_only_answer"
        except Exception as exc:
            llm_error = str(exc)
            answer = f"I found the following tool context:\n\n{mcp_context}"
            answer_mode = "mcp_only_fallback"

        return {
            "query": user_query,
            "answer": answer,
            "answer_mode": answer_mode,
            "llm_error": llm_error,
            "sources": mcp_sources,
        }

    if not all_sources:
        return {
            "query": user_query,
            "answer": (
                "I found embeddings in ChromaDB, but none from Microsoft Graph, "
                "SharePoint, OneDrive recordings, or connected MCP tools matched this query yet."
            ),
            "answer_mode": "no_microsoft_context",
            "sources": [],
        }

    if AnswerService.is_vague_or_social_query(user_query):
        return _generate_conversational_response(user_query, all_sources)

    context_text = "\n\n---\n\n".join(
        f"Source: {(source.get('metadata') or {}).get('meeting_title') or 'Untitled meeting'}\n{source.get('text') or ''}"
        for source in all_sources
        if (source.get("metadata") or {}).get("source_type") not in (
            "mcp_jira", "mcp_github", "mcp_outlook", "mcp_calendar", "mcp_slack", "mcp_salesforce"
        )
    )
    if mcp_context:
        context_text = f"{context_text}\n\n---\n\n{mcp_context}".strip()

    safe_query = user_query.replace("{", "{{").replace("}", "}}")
    final_prompt = RAG_SYSTEM_PROMPT.format(
        context=context_text,
        query=safe_query,
    )

    llm_error = None
    try:
        answer = generate_answer(
            final_prompt, query=user_query, context=context_text
        )
        answer_mode = "rag_answer"
    except Exception as exc:
        llm_error = str(exc)
        fallback_answer = AnswerService.compose(user_query, all_sources)
        if fallback_answer:
            answer = fallback_answer["text"]
            answer_mode = fallback_answer["mode"]
        else:
            answer = (
                "I found relevant transcript chunks, but the answer model is not "
                "available right now. Review the retrieved sources below."
            )
            answer_mode = "retrieval_only"

    if _is_not_found_answer(answer) or _looks_like_transcript_dump(answer):
        if AnswerService.is_vague_or_social_query(user_query):
            return _generate_conversational_response(user_query, all_sources)

        fallback_answer = AnswerService.compose(user_query, all_sources)
        if fallback_answer:
            answer = fallback_answer["text"]
            answer_mode = fallback_answer["mode"]
        else:
            title = _meeting_title_from_sources(all_sources)
            answer = (
                f"I couldn't find a clear answer to that in **{title}**. "
                "Try asking for a summary, the main tips, or a specific topic from the meeting."
            )
            answer_mode = "clarification"

    return {
        "query": user_query,
        "answer": answer,
        "answer_mode": answer_mode,
        "llm_error": llm_error,
        "sources": all_sources,
    }
