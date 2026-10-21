"""Execute release metadata handoff without network access or an EXE build."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_installed_release_workflow_keeps_signing_secret_out_of_pull_requests() -> None:
    source = (ROOT / '.github/workflows/build-installer.yml').read_text(encoding='utf-8')
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


@pytest.mark.parametrize('culture', ['en-US', 'pl-PL'])
@pytest.mark.parametrize('date_kind', ['string', 'datetime', 'offset'])
def test_release_publication_time_reaches_builder_as_iso_in_any_powershell_culture(tmp_path, culture, date_kind):
    shell = shutil.which('pwsh') or shutil.which('powershell')
    if shell is None:
        pytest.skip('PowerShell is needed for the release metadata handoff test')
    source = (ROOT / '.github/workflows/build-installer.yml').read_text(encoding='utf-8')
    resolve = source.split('      - name: Resolve the actual target Release', 1)[1].split('      - uses:', 1)[0]
    script = textwrap.dedent(resolve.split('        run: |\n', 1)[1])
    # PowerShell 7 deserializes ISO dates automatically. Emulate both its date
    # types on Windows PowerShell 5.1 too, which leaves the same field a string.
    harness = tmp_path / 'resolve-release.ps1'
    harness.write_text(r'''
param([string]$Culture, [string]$DateKind)
$ErrorActionPreference = 'Stop'
[Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::GetCultureInfo($Culture)
function gh {
    $global:LASTEXITCODE = 0
    return '{"id":5,"tag_name":"v5-dev.1","draft":false,"prerelease":true,"target_commitish":"dev2","published_at":"2026-10-09T11:51:54+02:00"}'
}
function ConvertFrom-Json {
    param([Parameter(ValueFromPipeline=$true)][string]$InputObject)
    process {
        $release = Microsoft.PowerShell.Utility\ConvertFrom-Json -InputObject $InputObject
        if ($DateKind -eq 'datetime') {
            $release.published_at = [DateTimeOffset]::Parse('2026-10-09T11:51:54+02:00').UtcDateTime
        } elseif ($DateKind -eq 'offset') {
            $release.published_at = [DateTimeOffset]::Parse('2026-10-09T11:51:54+02:00')
        } else { $release.published_at = '2026-10-09T11:51:54+02:00' }
        return $release
    }
}
''' + script, encoding='utf-8')
    output = tmp_path / 'github-output.txt'
    result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(harness), culture, date_kind],
        capture_output=True, text=True, timeout=30,
        env=dict(os.environ, TARGET_RELEASE_ID='5', REQUESTED_CHANNEL='dev',
                 GITHUB_REPOSITORY='test/repository', GITHUB_OUTPUT=str(output)))
    assert result.returncode == 0, result.stdout + result.stderr
    raw = output.read_bytes()
    outputs = dict(line.split('=', 1) for line in raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig').splitlines())
    published_at = outputs['published_at']
    assert re.match(r'^\d{4}-\d{2}-\d{2}T', published_at), published_at
    actual = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
    assert actual.tzinfo is not None
    assert actual == datetime(2026, 10, 9, 9, 51, 54, tzinfo=timezone.utc)
    assert outputs['channel'] == 'dev' and outputs['source_branch'] == 'dev2'
    # This is the exact timestamp passed through Actions env to the Python
    # manifest builder. Exercise its validation as part of the handoff.
    from tools.build_installed_modules import generate_module_release_manifest
    from picsyncra.installation.module_manifest import parse_module_manifest
    from tests.module_fixtures import release_payload
    payload = release_payload()
    modules = parse_module_manifest(payload).modules
    metadata = {key: value for key, value in payload.items() if key not in {'schema','platform','minimum_controller','minimum_launcher','modules','migrations'}}
    metadata.update(channel='dev', source_branch='dev2', prerelease=True, published_at=published_at)
    generate_module_release_manifest(release_metadata=metadata, modules=modules)
