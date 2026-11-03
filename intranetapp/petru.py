import logging
import hashlib
import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

CACHE_KEY = "petru_upcoming_events"
STALE_KEY = "petru_upcoming_events_stale"
CACHE_TTL = 600  # 10 min


def _normalize(rows):
    now = timezone.now()
    seen, out = set(), []
    for r in rows:
        start = parse_datetime(r.get("target_schedule_start") or "")
        end = parse_datetime(r.get("target_schedule_end") or "")
        title = (r.get("title") or "").strip()
        if not title or not start:
            continue

        # Source data has duplicates that differ only by letter case
        key = (title.casefold(), start)
        if key in seen:
            continue
        seen.add(key)

        # Source data sometimes has end < start (typo) -> don't show a bad range
        date_warning = bool(end and end < start)
        if date_warning:
            end = None

        if (end or start) < now and not date_warning:
            continue  # already finished

        out.append({
            "key": hashlib.sha1(f"{title.casefold()}|{start.isoformat()}".encode()).hexdigest()[:12],
            "title": title,
            "offices": r.get("requesting_offices") or [],
            "start": start,
            "end": end,
            "mode": r.get("learning_mode") or "",
            "venue": (r.get("venue") or "").strip(),
            "provider": (r.get("activity_provider") or "").strip(),
            "activity_type": (r.get("activity_type") or "").strip(),
            "date_warning": date_warning,
        })
    out.sort(key=lambda e: e["start"])
    return out


def get_petru_events():
    """Returns (events, is_stale). Never raises."""
    events = cache.get(CACHE_KEY)
    if events is None:
        try:
            resp = requests.get(
                settings.PETRU_API_URL,
                headers={"X-API-Key": settings.PETRU_API_KEY},
                timeout=5,
                verify=settings.PETRU_VERIFY_SSL,
            )
            resp.raise_for_status()
            events = _normalize(resp.json().get("data", []))
            cache.set(CACHE_KEY, events, CACHE_TTL)
            cache.set(STALE_KEY, events, 60 * 60 * 24)
        except Exception:
            logger.exception("PETRU fetch failed")
            return cache.get(STALE_KEY) or [], True

    now = timezone.now()
    for e in events:
        e["ongoing"] = e["start"] <= now <= (e["end"] or e["start"])
    return events, False