"""The workspace's OpenAI integration: encrypted key + consent, kept in OrgPrefs.data["ai_render"].

Stored:  key_enc (Fernet token), key_hint ("sk-…AbCd"), key_added_by / key_added_at, key_checked_at,
         consent {by, at, version}
`public_state()` is the only view that leaves the server: it never contains the key or its ciphertext.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from aicad.airender import CONSENT_TEXT, CONSENT_VERSION, keystore, options
from aicad.platform.db import utcnow
from aicad.platform.metering import prefs, set_prefs
from aicad.platform.models import Organization

PREF = "ai_render"


def state(db: Session, org: Organization) -> dict[str, Any]:
    v = prefs(db, org).get(PREF)
    return dict(v) if isinstance(v, dict) else {}


def _save(db: Session, org: Organization, st: dict[str, Any]) -> None:
    set_prefs(db, org, **{PREF: st})


def public_state(db: Session, org: Organization) -> dict[str, Any]:
    st = state(db, org)
    consent = st.get("consent") if isinstance(st.get("consent"), dict) else None
    consent_ok = bool(consent and consent.get("version") == CONSENT_VERSION)
    return {"has_key": bool(st.get("key_enc")), "key_hint": st.get("key_hint") if st.get("key_enc") else None,
            "key_added_at": st.get("key_added_at"), "key_added_by": st.get("key_added_by_name"),
            "key_checked_at": st.get("key_checked_at"),
            "consent": {"given": consent_ok, "at": consent.get("at") if consent_ok and consent else None,
                        "by": consent.get("by_name") if consent_ok and consent else None,
                        "text": CONSENT_TEXT, "version": CONSENT_VERSION},
            "model": options.model()}


def set_key(db: Session, org: Organization, key: str, user_id: str, user_name: str) -> None:
    st = state(db, org)
    now = utcnow().isoformat(timespec="seconds")
    st.update(key_enc=keystore.encrypt(key), key_hint=keystore.mask(key), key_added_by=user_id,
              key_added_by_name=user_name, key_added_at=now, key_checked_at=now)
    _save(db, org, st)


def clear_key(db: Session, org: Organization) -> bool:
    st = state(db, org)
    had = bool(st.get("key_enc"))
    for k in ("key_enc", "key_hint", "key_added_by", "key_added_by_name", "key_added_at", "key_checked_at"):
        st.pop(k, None)
    _save(db, org, st)
    return had


def get_key(db: Session, org: Organization) -> str | None:
    """The plain key, for the provider call only. None when no key is stored."""
    enc = state(db, org).get("key_enc")
    return keystore.decrypt(enc) if enc else None


def set_consent(db: Session, org: Organization, given: bool, user_id: str, user_name: str) -> None:
    st = state(db, org)
    if given:
        st["consent"] = {"by": user_id, "by_name": user_name, "at": utcnow().isoformat(timespec="seconds"),
                         "version": CONSENT_VERSION}
    else:
        st.pop("consent", None)
    _save(db, org, st)


def has_consent(db: Session, org: Organization) -> bool:
    return bool(public_state(db, org)["consent"]["given"])
