from picsyncra import brand, github_status


def test_github_status_uses_the_canonical_picsyncra_repository() -> None:
    assert brand.APP_NAME == "PicSyncra"
    assert brand.GITHUB_REPOSITORY == "NefilimPL/PicSyncra"
    assert github_status.GITHUB_REPO_FULL_NAME == brand.GITHUB_REPOSITORY
