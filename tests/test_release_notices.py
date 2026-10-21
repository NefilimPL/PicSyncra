import json

from picsyncra.sqlite_store import SqliteStore
from picsyncra.web.release_notices import current_notice
from picsyncra.installation.module_state import activate_module_set
from tests.test_module_state import context, staged


def test_notice_is_local_matches_active_core_and_receipts_are_account_scoped(context):
    active = staged(context, 1)
    activate_module_set(context, active, expected_revision=0)
    core = next(module for module in active.modules if module.module_id == 'core')
    notice = dict(version_id='release:5', release_id=5, tag='v5', body='Nowe funkcje', url='https://github.com/NefilimPL/PicSyncra/releases/tag/v5')
    path = context.state_root / 'release-notice.json'
    path.write_text(json.dumps(notice), encoding='utf-8')
    store = SqliteStore(context.database_path)
    assert current_notice(context, store, 'alice') == notice
    store.acknowledge_release_notice('alice', notice['version_id'])
    assert current_notice(context, store, 'alice') is None
    assert current_notice(context, store, 'bob') == notice
    notice['release_id'] = 6
    path.write_text(json.dumps(notice), encoding='utf-8')
    assert current_notice(context, store, 'bob') is None
