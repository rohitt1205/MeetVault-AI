import hashlib
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from fastapi import HTTPException

from app.services.answer_service import AnswerService
from app.services.chroma_service import ChromaService, MICROSOFT_SOURCE_TYPES
from app.services.embedding_service import EmbeddingService
from app.services.graph_client import GraphClient
from app.services.meeting_service import MeetingService
from app.services.token_diagnostics_service import TokenDiagnosticsService


BRIEF_QUERY = (
    "Summarize this meeting for attendees. Include key discussion points, "
    "decisions, action items, and open questions."
)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class PostMeetingNotificationService:
    _lock = threading.Lock()

    @staticmethod
    def _enabled() -> bool:
        return _env_bool("POST_MEETING_EMAIL_ENABLED", True)

    @staticmethod
    def _store_path() -> Path:
        return Path(
            os.getenv(
                "POST_MEETING_NOTIFICATION_STORE_PATH",
                "./post_meeting_notifications.json",
            )
        )

    @staticmethod
    def _chat_url(meeting_id: str | None = None) -> str:
        base_url = (
            os.getenv("MEETVAULT_CHAT_URL")
            or os.getenv("FRONTEND_ORIGIN")
            or "http://127.0.0.1:5173"
        ).rstrip("/")
        if not meeting_id:
            return base_url
        return f"{base_url}/#meeting={meeting_id}"

    @staticmethod
    def _pending_ttl() -> timedelta:
        seconds = int(os.getenv("POST_MEETING_EMAIL_PENDING_TTL_SECONDS", "900"))
        return timedelta(seconds=max(60, seconds))

    @staticmethod
    def _load_store() -> dict:
        path = PostMeetingNotificationService._store_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _save_store(data: dict) -> None:
        path = PostMeetingNotificationService._store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _status(meeting_id: str) -> dict | None:
        return PostMeetingNotificationService._load_store().get(meeting_id)

    @staticmethod
    def status_for_meeting(meeting_id: str) -> dict:
        return PostMeetingNotificationService._status(meeting_id) or {
            "meeting_id": meeting_id,
            "status": "NOT_SENT",
        }

    @staticmethod
    def _pending_is_fresh(record: dict) -> bool:
        if record.get("status") != "PENDING":
            return False
        updated_at = record.get("updated_at")
        if not updated_at:
            return True
        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        return datetime.now(timezone.utc) - parsed < PostMeetingNotificationService._pending_ttl()

    @staticmethod
    def _claim_pending(meeting_id: str, meeting_title: str) -> bool:
        with PostMeetingNotificationService._lock:
            store = PostMeetingNotificationService._load_store()
            existing = store.get(meeting_id) or {}
            if existing.get("status") == "SENT":
                return False
            if PostMeetingNotificationService._pending_is_fresh(existing):
                return False

            store[meeting_id] = {
                **existing,
                "meeting_id": meeting_id,
                "meeting_title": meeting_title,
                "status": "PENDING",
                "updated_at": PostMeetingNotificationService._now(),
            }
            PostMeetingNotificationService._save_store(store)
            return True

    @staticmethod
    def _mark(meeting_id: str, **payload) -> dict:
        with PostMeetingNotificationService._lock:
            store = PostMeetingNotificationService._load_store()
            next_record = {
                **(store.get(meeting_id) or {}),
                "meeting_id": meeting_id,
                "updated_at": PostMeetingNotificationService._now(),
                **payload,
            }
            store[meeting_id] = next_record
            PostMeetingNotificationService._save_store(store)
            return next_record

    @staticmethod
    def _has_mail_scope(access_token: str) -> bool:
        diagnostics = TokenDiagnosticsService.inspect(access_token)
        return diagnostics.get("is_graph_token") and "Mail.Send" in diagnostics.get("scopes", [])

    @staticmethod
    def _can_resolve_calendar_event(meeting_id: str) -> bool:
        unsupported_prefixes = (
            "sharepoint-",
            "graph-recording-",
            "upload-",
            "onedrive:",
        )
        return not any(meeting_id.startswith(prefix) for prefix in unsupported_prefixes)

    @staticmethod
    def queue_after_index(access_token: str, meeting_id: str, meeting_title: str) -> dict:
        if not PostMeetingNotificationService._enabled():
            return {
                "meeting_id": meeting_id,
                "status": "DISABLED",
                "message": "Post-meeting email notifications are disabled.",
            }
        if not PostMeetingNotificationService._has_mail_scope(access_token):
            return {
                "meeting_id": meeting_id,
                "status": "SKIPPED",
                "message": "Current Microsoft token does not include Mail.Send.",
            }
        if not PostMeetingNotificationService._can_resolve_calendar_event(meeting_id):
            return {
                "meeting_id": meeting_id,
                "status": "SKIPPED",
                "message": "Post-meeting email requires a calendar-backed recording with attendee data.",
            }
        if not PostMeetingNotificationService._claim_pending(meeting_id, meeting_title):
            return PostMeetingNotificationService.status_for_meeting(meeting_id)

        thread = threading.Thread(
            target=PostMeetingNotificationService._send_claimed,
            args=(access_token, meeting_id, meeting_title),
            name=f"meetvault-post-meeting-email-{meeting_id[:16]}",
            daemon=True,
        )
        thread.start()
        return PostMeetingNotificationService.status_for_meeting(meeting_id)

    @staticmethod
    def send_now(access_token: str, meeting_id: str, meeting_title: str | None = None) -> dict:
        if not PostMeetingNotificationService._enabled():
            raise HTTPException(
                status_code=409,
                detail="Post-meeting email notifications are disabled.",
            )
        if not PostMeetingNotificationService._has_mail_scope(access_token):
            raise HTTPException(
                status_code=403,
                detail="Microsoft Graph token is missing Mail.Send.",
            )
        if not PostMeetingNotificationService._can_resolve_calendar_event(meeting_id):
            raise HTTPException(
                status_code=422,
                detail="Post-meeting email requires a calendar-backed recording with attendee data.",
            )

        title = meeting_title or meeting_id
        if not PostMeetingNotificationService._claim_pending(meeting_id, title):
            return PostMeetingNotificationService.status_for_meeting(meeting_id)
        return PostMeetingNotificationService._send_claimed(access_token, meeting_id, title)

    @staticmethod
    def _send_claimed(access_token: str, meeting_id: str, meeting_title: str) -> dict:
        try:
            event = MeetingService.get_meeting_event_with_attendees(access_token, meeting_id)
            title = event.get("title") or meeting_title or "Recorded meeting"
            recipients = PostMeetingNotificationService._recipients_from_event(event)
            if not recipients:
                return PostMeetingNotificationService._mark(
                    meeting_id,
                    status="SKIPPED",
                    meeting_title=title,
                    message="No attendee email addresses were available on the calendar event.",
                )

            brief = PostMeetingNotificationService._generate_brief(meeting_id)
            if not brief["bullets"]:
                return PostMeetingNotificationService._mark(
                    meeting_id,
                    status="SKIPPED",
                    meeting_title=title,
                    recipient_count=len(recipients),
                    message="No indexed transcript chunks were available for the email brief.",
                )

            chat_url = PostMeetingNotificationService._chat_url(meeting_id)
            html = PostMeetingNotificationService._render_email_card(
                meeting_title=title,
                bullets=brief["bullets"],
                chat_url=chat_url,
            )
            sent_count = PostMeetingNotificationService._send_mail(
                access_token=access_token,
                meeting_title=title,
                recipients=recipients,
                html=html,
            )
            return PostMeetingNotificationService._mark(
                meeting_id,
                status="SENT",
                meeting_title=title,
                recipient_count=sent_count,
                sent_at=PostMeetingNotificationService._now(),
                brief_hash=brief["hash"],
                chat_url=chat_url,
                message=f"Post-meeting brief sent to {sent_count} recipient(s).",
            )
        except Exception as exc:  # pragma: no cover - defensive background guard
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            return PostMeetingNotificationService._mark(
                meeting_id,
                status="FAILED",
                meeting_title=meeting_title,
                error_detail=detail,
                message="Post-meeting brief email failed.",
            )

    @staticmethod
    def _recipients_from_event(event: dict) -> list[dict]:
        people = []
        organizer_email = (event.get("organizer_email") or "").strip()
        if organizer_email:
            people.append({
                "name": event.get("organizer") or organizer_email,
                "email": organizer_email,
            })
        for attendee in event.get("attendees") or []:
            people.append({
                "name": attendee.get("name") or attendee.get("email"),
                "email": attendee.get("email"),
            })

        recipients = []
        seen = set()
        for person in people:
            email = (person.get("email") or "").strip()
            key = email.lower()
            if not EMAIL_PATTERN.match(email) or key in seen:
                continue
            seen.add(key)
            recipients.append({
                "emailAddress": {
                    "address": email,
                    "name": person.get("name") or email,
                }
            })
        return recipients

    @staticmethod
    def _generate_brief(meeting_id: str) -> dict:
        query_embedding = EmbeddingService.generate_query_embedding(BRIEF_QUERY)
        results = ChromaService.query_embeddings(
            query_embedding,
            meeting_id=meeting_id,
            n_results=8,
            candidate_pool_size=30,
            allowed_source_types=MICROSOFT_SOURCE_TYPES,
        )
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        ids = results.get("ids", [[]])[0]
        sources = [
            {
                "chunk_id": ids[index] if index < len(ids) else f"source-{index + 1}",
                "text": document,
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "distance": distances[index] if index < len(distances) else None,
            }
            for index, document in enumerate(documents)
        ]

        composed = AnswerService.compose(BRIEF_QUERY, sources)
        candidate_text = composed["text"] if composed else "\n".join(
            source.get("text") or "" for source in sources[:3]
        )
        bullets = PostMeetingNotificationService._extract_bullets(candidate_text)
        digest = hashlib.sha256("\n".join(bullets).encode("utf-8")).hexdigest()[:16]
        return {
            "bullets": bullets,
            "hash": digest,
            "source_count": len(sources),
        }

    @staticmethod
    def _extract_bullets(text: str, limit: int = 5) -> list[str]:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        raw_lines = [
            re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            for line in (text or "").splitlines()
            if line.strip()
        ]
        candidates = raw_lines or AnswerService._split_sentences(cleaned)

        bullets = []
        seen = set()
        for candidate in candidates:
            normalized = AnswerService._normalize_passage(candidate)
            normalized = re.sub(r"\s+", " ", normalized).strip(" -")
            if not normalized or not AnswerService._is_meaningful_passage(normalized):
                continue
            normalized = AnswerService._truncate_excerpt(normalized, limit=190)
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            bullets.append(normalized)
            if len(bullets) >= limit:
                break
        return bullets

    @staticmethod
    def _send_mail(
        *,
        access_token: str,
        meeting_title: str,
        recipients: list[dict],
        html: str,
    ) -> int:
        max_recipients = int(os.getenv("POST_MEETING_EMAIL_MAX_RECIPIENTS", "80"))
        selected = recipients[: max(1, max_recipients)]
        payload = {
            "message": {
                "subject": f"MeetVault brief: {meeting_title}",
                "body": {
                    "contentType": "HTML",
                    "content": html,
                },
                "toRecipients": selected,
            },
            "saveToSentItems": "true",
        }
        GraphClient.post("/me/sendMail", access_token, payload)
        return len(selected)

    @staticmethod
    def _plain_text(meeting_title: str, bullets: list[str], chat_url: str) -> str:
        bullet_text = "\n".join(f"- {bullet}" for bullet in bullets)
        return (
            f"Your MeetVault brief is ready for {meeting_title}.\n\n"
            f"{bullet_text}\n\n"
            f"Chat with MeetVault: {chat_url}"
        )

    @staticmethod
    def _render_email_card(meeting_title: str, bullets: list[str], chat_url: str) -> str:
        bullet_items = "\n".join(
            (
                "<li style=\"margin:0 0 10px 0; color:#dbeafe; line-height:1.55;\">"
                f"{escape(bullet)}</li>"
            )
            for bullet in bullets
        )
        safe_title = escape(meeting_title)
        safe_url = escape(chat_url, quote=True)
        return f"""
<!doctype html>
<html>
  <body style="margin:0; padding:0; background:#eaf2ff; font-family:Inter,Segoe UI,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#dbeafe 0%,#bfdbfe 45%,#e0f2fe 100%); padding:32px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px; border-collapse:separate; border-spacing:0;">
            <tr>
              <td style="border-radius:28px; overflow:hidden; background:linear-gradient(145deg,#0f2f8f 0%,#2563eb 46%,#06b6d4 100%); box-shadow:0 26px 70px rgba(30,64,175,0.35);">
                <div style="padding:30px 30px 26px 30px;">
                  <div style="display:inline-block; padding:7px 12px; border:1px solid rgba(255,255,255,0.35); border-radius:999px; color:#bfdbfe; font-size:12px; font-weight:800; letter-spacing:0.08em; text-transform:uppercase;">
                    Post-meeting brief
                  </div>
                  <h1 style="margin:18px 0 8px 0; color:#ffffff; font-size:30px; line-height:1.18; letter-spacing:0;">
                    Your MeetVault brief is ready
                  </h1>
                  <p style="margin:0; color:#dbeafe; font-size:16px; line-height:1.55;">
                    {safe_title}
                  </p>
                  <div style="margin:24px 0 0 0; padding:22px; border-radius:22px; background:rgba(15,23,42,0.28); border:1px solid rgba(255,255,255,0.22);">
                    <p style="margin:0 0 14px 0; color:#ffffff; font-size:14px; font-weight:800; letter-spacing:0.05em; text-transform:uppercase;">
                      Quick highlights
                    </p>
                    <ul style="margin:0; padding:0 0 0 20px;">
                      {bullet_items}
                    </ul>
                  </div>
                  <div style="margin-top:26px;">
                    <a href="{safe_url}" style="display:inline-block; background:#ffffff; color:#1d4ed8; text-decoration:none; font-size:15px; font-weight:900; padding:14px 22px; border-radius:16px; box-shadow:0 16px 30px rgba(15,23,42,0.18);">
                      Chat with us
                    </a>
                  </div>
                  <p style="margin:22px 0 0 0; color:#bfdbfe; font-size:12px; line-height:1.5;">
                    Generated from the indexed transcript stored in MeetVault. You can ask follow-up questions anytime.
                  </p>
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
