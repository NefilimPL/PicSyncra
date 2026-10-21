"""Local release descriptions with account-scoped read receipts."""
import json

from ..installation.module_state import read_module_set


def current_notice(context, store, user_id):
    if context is None:
        return None
    path = context.state_root / 'release-notice.json'
    if not path.exists():
        return None
    try:
        notice = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(notice, dict) or not isinstance(notice.get('version_id'), str):
        return None
    active = read_module_set(context)
    if active.release_id != notice.get('release_id'):
        return None
    if store.release_notice_seen(user_id, notice['version_id']):
        return None
    return notice
