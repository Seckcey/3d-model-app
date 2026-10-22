"""Outbox email backend used until an SMTP relay is configured.

Each message is written as a JSON file in OUTBOX_DIR with owner-only
permissions. Only someone with shell access to the server can read it, via
``python manage.py outbox``. Messages never contain customer drawings.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

KEEP_MESSAGES = 500


def outbox_dir() -> Path:
    path = Path(settings.OUTBOX_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


class OutboxEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages) -> int:
        directory = outbox_dir()
        sent = 0
        for message in email_messages:
            now = datetime.now(UTC)
            record = {
                "id": uuid.uuid4().hex,
                "sent_at": now.isoformat(),
                "from": message.from_email,
                "to": list(message.to),
                "subject": message.subject,
                "body": message.body,
            }
            name = f"{now:%Y%m%dT%H%M%S%f}-{record['id'][:8]}.json"
            path = directory / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, indent=2)
            sent += 1
        self._prune(directory)
        return sent

    @staticmethod
    def _prune(directory: Path) -> None:
        files = sorted(directory.glob("*.json"))
        for old in files[:-KEEP_MESSAGES]:
            old.unlink(missing_ok=True)


def read_outbox(limit: int = 20, to: str | None = None) -> list[dict]:
    directory = outbox_dir()
    messages: list[dict] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if to and to.lower() not in [addr.lower() for addr in data.get("to", [])]:
            continue
        messages.append(data)
        if len(messages) >= limit:
            break
    return messages
