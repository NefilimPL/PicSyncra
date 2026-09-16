from pathlib import Path


def test_installed_release_workflow_keeps_signing_secret_out_of_pull_requests() -> None:
    source = (Path(__file__).parents[1] / ".github/workflows/build-installer.yml").read_text(encoding="utf-8")
    assert "PICSYNCRA_RELEASE_SIGNING_KEY: ${{ secrets.PICSYNCRA_RELEASE_SIGNING_KEY }}" in source
    assert "if: github.event_name != 'pull_request'" in source
    assert "write_trusted_release_keys.py" in source
    assert "PicSyncra-installed-manifest.sig" in source
    assert 'dist/installed/ocr.zip' in source
    assert '--component ocr:ocr-$releaseId:dist/installed/ocr.zip' in source
