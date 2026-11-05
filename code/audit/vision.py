"""Reading the screenshots.

Eleven of the ninety-four evidence files are application screenshots: an admin console,
a search index inspector, a backup restore panel, a connector manager, an analytics
profile, a support ticket, an object storage browser, a deleted-account reference. They
are ordinary business screens, not pictures of a verdict, so what is wanted from them is
the same five facts every other reader extracts -- which system, which resource, what
kind of record, what state, and whose it is.

Cost is bounded by construction. The corpus is fixed, so each image is read **once** and
the result cached on the file's own hash: eleven calls for five hundred and eighteen
cases, not five hundred and eighteen. Re-runs are free, and changing the prompt or the
model invalidates the cache rather than silently serving the old reading.

A model reading a picture is the least reliable step in this pipeline, so it is also the
most constrained. It is asked for a fixed schema, at temperature zero; anything it
returns that is not in the allowed vocabulary is dropped rather than coerced; and a file
it cannot read stays in `unread`, where it is visible, instead of quietly contributing
nothing.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from .dataset import EvidenceFile
from .evidence import (DECLARED_STATES, KNOWN_CATEGORY_WORDS, NOT_IDENTIFIERS,
                       Observation, system_for)
from .identity import norm
from .llm import Client, LLMError

SYSTEM = """You read screenshots of internal business applications and report only the
facts visible on screen. You never infer, never guess a value that is not shown, and
never decide whether anything is compliant.

Return one JSON object and nothing else:

{
  "screen": "<what application screen this is, 2-5 words>",
  "subject": {"name": "", "user_id": "", "email": "", "phone": ""},
  "records": [
    {
      "resource_id": "<an identifier like account_1234, search_52, support_864, analytics_90, data_flow_11, backup_77, audit_record_3, export_5, tombstone_17>",
      "system": "<account_service|search_service|analytics_platform|support_platform|export_service|integration_service|backup_service|security_service|identity_service>",
      "category": "<USER_PROFILE|SEARCH_INDEX_ENTRY|ANALYTICS_PROFILE|MARKETING_PROFILE|SUPPORT_MESSAGE|SUPPORT_ATTACHMENT|USER_EXPORT|DATA_FLOW|BACKUP_ARCHIVE|SECURITY_AUDIT_LOG|ACCOUNT_TOMBSTONE|LEGAL_HOLD_RECORD>",
      "state": "<PRESENT|ABSENT|REDACTED|ANONYMIZED|ACTIVE|DISABLED|BLOCKED>",
      "identifiers_shown": ["<every name, email address, phone number or user id displayed for THIS record>"]
    }
  ]
}

Rules:
- Use "" for any field not visible. Never invent an identifier or a resource id.
- "state": PRESENT if the record is shown as existing; ABSENT if shown as deleted, not
  found or removed; REDACTED or ANONYMIZED if the screen shows its identifying fields
  removed or replaced; ACTIVE / DISABLED for a connector, sync or data flow; ACTIVE or
  BLOCKED for a backup or restore entry depending on whether restore is permitted.
- A record that still displays a name, email address or phone number has those values in
  "identifiers_shown", even if the screen also calls it deleted.
- If the screen shows no record of these kinds, return "records": []."""

#: Fields a screenshot may show for a record, mapped to the canonical PII names.
_PII_HINTS = ("@", "+")


class VisionReader:
    """One cached model call per image, producing the same Observations as any reader."""

    def __init__(self, client: Client, *, model: str | None = None,
                 cache_dir: Path | None = None) -> None:
        self.client = client
        self.model = model or client.vision_model
        self.cache_dir = cache_dir or (Path(__file__).resolve().parents[2]
                                       / ".cache" / "vision")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.failures: list[tuple[str, str]] = []

    def read(self, ev: EvidenceFile, path: Path) -> list[Observation]:
        try:
            payload = self._extract(ev, path)
        except (LLMError, ValueError, KeyError) as why:
            self.failures.append((ev.file_id, f"{type(why).__name__}: {why}"))
            return []
        return list(self._to_observations(ev, payload))

    # -- the call ----------------------------------------------------------------- #

    def _extract(self, ev: EvidenceFile, path: Path) -> dict:
        raw = path.read_bytes()
        digest = hashlib.sha256(
            raw + SYSTEM.encode("utf-8") + self.model.encode("utf-8")).hexdigest()
        cached = self.cache_dir / f"{digest}.json"
        if cached.is_file():
            return json.loads(cached.read_text(encoding="utf-8"))

        suffix = path.suffix.lower().lstrip(".")
        media = "jpeg" if suffix in ("jpg", "jpeg") else suffix
        content = [
            {"type": "text",
             "text": f"Screenshot captured at {ev.captured_at.isoformat()}, "
                     f"source system: {ev.origin}."},
            {"type": "image_url",
             "image_url": {"url": f"data:image/{media};base64,"
                                  + base64.b64encode(raw).decode("ascii")}},
        ]
        payload = self.client.ask_json(SYSTEM, content, model=self.model,
                                       max_tokens=1600, cache=False)
        cached.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload

    # -- shaping ------------------------------------------------------------------ #

    def _to_observations(self, ev: EvidenceFile, payload: dict):
        subject = payload.get("subject") or {}
        shared = {norm(str(subject.get(k) or ""))
                  for k in ("user_id", "email", "phone")}
        shared = {s for s in shared if s and s not in NOT_IDENTIFIERS}

        for record in payload.get("records") or []:
            if not isinstance(record, dict):
                continue
            resource_id = str(record.get("resource_id") or "").strip()
            if not resource_id or not system_for(resource_id):
                # Anything we cannot place in a known resource family is dropped. A
                # screenshot is the one source that can hallucinate an identifier, so
                # nothing it invents is allowed past this line.
                continue

            category = str(record.get("category") or "").strip().upper()
            if category not in KNOWN_CATEGORY_WORDS:
                category = ""
            state = DECLARED_STATES.get(norm(str(record.get("state") or "")), "")

            obs = Observation(
                file_id=ev.file_id, captured_at=ev.captured_at,
                resource_id=resource_id,
                system_id=system_for(resource_id) or str(record.get("system") or ""),
                category=category,
                present=None if state in ("", "ABSENT") else True,
                declared_state=state, reader="vision")
            if state == "ABSENT":
                obs.present = False

            shown = [str(v) for v in (record.get("identifiers_shown") or []) if v]
            for value in shown:
                key = norm(value)
                if not key or key in NOT_IDENTIFIERS:
                    continue
                obs.subject_keys.add(key)
                if "@" in value:
                    obs.add_pii("email", value)
                elif value.startswith("+"):
                    obs.add_pii("phone", value)
                elif not value.lower().startswith("user_"):
                    obs.add_pii("name", value)
            obs.subject_keys |= shared
            yield obs
