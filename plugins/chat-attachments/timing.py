"""Age selection and conservative local-chat activity guards."""
from datetime import datetime
import math
import re
import sqlite3
import time

from history import AttachmentError
from media import blobs, digest

QUIET_SECONDS = 120


def period_seconds(period):
    if not isinstance(period, str):
        raise AttachmentError('invalid_period', 'Use a time period such as 48 hours, 7 days or 30 minutes.')
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|[smhdw])\s*', period, re.I)
    if not match:
        raise AttachmentError('invalid_period', 'Use a time period such as 48 hours, 7 days or 30 minutes.')
    unit = match[2].lower()[0]
    seconds = float(match[1]) * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}[unit]
    if not math.isfinite(seconds) or not 60 <= seconds <= 315360000:
        raise AttachmentError('invalid_period', 'Choose a period from one minute to ten years.')
    return seconds


def timestamp(value):
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return parsed.timestamp()
    except (ValueError, OverflowError):
        pass
    return None


def eligible(records, files, cutoff):
    # Compaction copies must not reset an attachment's age. Prefer the latest
    # actual message/tool occurrence, falling back to a dated compaction copy.
    actual, copies = {}, {}
    for row in records:
        created = timestamp(row.get('timestamp'))
        if created is None:
            continue
        target = copies if row.get('type') == 'compacted' else actual
        for _, data, _, _ in blobs(row.get('payload', {})):
            sha = digest(data)
            target[sha] = max(target.get(sha, created), created)
    return [sha for sha, item in files.items() if item['convertible']
            and actual.get(sha, copies.get(sha, float('inf'))) <= cutoff]


def assert_idle(home, thread_id, path, records, now=None):
    now = time.time() if now is None else now
    if now - path.stat().st_mtime < QUIET_SECONDS:
        raise AttachmentError('chat_active', 'The chat has not been quiet for two minutes; deferred.')
    pending = set()
    saw_end = False
    for row in records:
        if row.get('type') != 'event_msg':
            continue
        payload = row.get('payload', {})
        kind = payload.get('type')
        turn = payload.get('turn_id') or payload.get('root_turn_id') or 'unknown'
        if kind in ('task_started', 'turn_started'):
            pending.add(turn)
        elif kind in ('task_complete', 'turn_complete', 'task_aborted', 'turn_aborted', 'task_failed', 'turn_failed'):
            pending.discard(turn)
            saw_end = True
    if pending or not saw_end:
        raise AttachmentError('chat_active', 'A completed idle turn cannot be established; deferred.')
    db = home / 'thread_history_1.sqlite'
    if db.is_file():
        try:
            with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=2) as con:
                columns = {r[1] for r in con.execute('PRAGMA table_info(thread_turns)')}
                if 'status' not in columns:
                    raise AttachmentError('activity_unknown', 'The display schema cannot confirm chat activity; deferred.')
                states = [r[0] for r in con.execute('SELECT status FROM thread_turns WHERE thread_id=?', (thread_id,))]
                if any(s not in ('completed', 'complete', 'failed', 'interrupted', 'aborted', 'cancelled', 'canceled') for s in states):
                    raise AttachmentError('chat_active', 'The display index reports an unfinished turn; deferred.')
        except sqlite3.Error:
            raise AttachmentError('activity_unknown', 'The display index is unavailable; deferred.')
