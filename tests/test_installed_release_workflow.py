from pathlib import Path


def test_installed_release_workflow_keeps_signing_secret_out_of_pull_requests() -> None:
    source = (Path(__file__).parents[1] / ".github/workflows/build-installer.yml").read_text(encoding="utf-8")
    assert "PICSYNCRA_RELEASE_SIGNING_KEY: ${{ secrets.PICSYNCRA_RELEASE_SIGNING_KEY }}" in source
    assert "if: github.event_name != 'pull_request'" in source
    assert "write_trusted_release_keys.py" in source
    assert 'PicSyncra-modules-manifest.json.sig' in source
    assert 'module-assets/content-*.bin' in source
    assert 'PicSyncra-Setup-*.exe' in source
    assert 'refs/tags/${{ steps.release.outputs.tag }}' in source
    assert source.index('Upload complete content') < source.index('Upload signed manifest last')
    assert 'Release channel mismatch' in source
    assert 'git merge-base --is-ancestor HEAD' in source
