"""Execute real model-preparation blocks without downloading large OCR models."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODEL_ENVIRONMENT = {
    'PADDLE_PDX_MODEL_SOURCE': 'bos',
    'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK': 'True',
    'HF_HUB_DISABLE_XET': '1',
}


def preparation_block(target):
    if target == 'actions':
        source = (ROOT / '.github/workflows/build-exe.yml').read_text(encoding='utf-8')
        start = source.index('$modelCache = Join-Path')
        end = source.index('foreach ($package', start)
        return textwrap.dedent(source[start:end]).replace('${{ github.run_id }}', 'test').replace('${{ github.run_attempt }}', '1')
    if target == 'installer':
        source = (ROOT / 'installer/build_installer.ps1').read_text(encoding='utf-8')
        start = source.index('$modelCache = Join-Path')
        return textwrap.dedent(source[start:source.index("Build-Onedir 'PicSyncra-OCR'", start)])
    source = (ROOT / 'Generator exe/build_web_exe.ps1').read_text(encoding='utf-8')
    start = source.index('$VisionModelCache = Join-Path')
    return textwrap.dedent(source[start:source.index('$VisionPyInstallerArguments += "--add-data"', start)])


@pytest.mark.parametrize('target', ['actions', 'installer', 'local'])
@pytest.mark.parametrize('missing_model', [False, True], ids=['complete', 'incomplete'])
def test_ocr_build_configures_sources_before_paddle_import_and_verifies_both_profiles(tmp_path, target, missing_model):
    shell = shutil.which('powershell') or shutil.which('pwsh')
    if shell is None: pytest.skip('PowerShell is required for Windows build acceptance')
    fake = tmp_path / 'stub'
    fake.mkdir()
    (fake / 'paddleocr.py').write_text('''
import json
import os
from pathlib import Path
required = {'PADDLE_PDX_MODEL_SOURCE':'bos', 'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK':'True', 'HF_HUB_DISABLE_XET':'1'}
for name, value in required.items():
    if os.environ.get(name) != value:
        raise RuntimeError('OCR download configuration was not set before import: ' + name)
def PaddleOCR(**kwargs):
    assert kwargs['enable_mkldnn'] is False
    for flag in ('use_doc_orientation_classify', 'use_doc_unwarping', 'use_textline_orientation'):
        assert kwargs[flag] is False
    cache = Path(os.environ['PADDLE_PDX_CACHE_HOME']) / 'official_models'
    for name in (kwargs['text_detection_model_name'], kwargs['text_recognition_model_name']):
        if name == os.environ.get('OCR_TEST_OMIT_MODEL'): continue
        destination = cache / name
        destination.mkdir(parents=True, exist_ok=True)
        (destination / 'model.bin').write_bytes(b'test-model')
    with Path(os.environ['OCR_TEST_CALLS']).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(kwargs) + '\\n')
''', encoding='utf-8')
    harness = tmp_path / 'prepare.ps1'
    harness.write_text('''param([string]$TestPython, [string]$Workspace)
$ErrorActionPreference = 'Stop'
$env:PICSYNCRA_PYTHON = $TestPython
$env:RUNNER_TEMP = $Workspace
$Python = $TestPython
$workRoot = $Workspace
$WorkPath = $Workspace
function Invoke-Native {
    $command, $arguments = $args
    & $command @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Python preparation failed' }
}
''' + preparation_block(target), encoding='utf-8-sig')
    calls = tmp_path / 'calls.jsonl'
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(fake),str(ROOT))), OCR_TEST_CALLS=str(calls))
    environment['OCR_TEST_OMIT_MODEL'] = 'PP-OCRv5_server_rec' if missing_model else ''
    for name in MODEL_ENVIRONMENT: environment.pop(name, None)
    result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(harness), sys.executable, str(tmp_path)],
                            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=40)
    output = result.stdout + result.stderr
    if missing_model:
        assert result.returncode != 0
        assert 'Brakuje modeli OCR' in output and 'accurate' in output
    else:
        assert result.returncode == 0, output
    prepared = [json.loads(line) for line in calls.read_text(encoding='utf-8').splitlines()]
    assert {call['text_detection_model_name'] for call in prepared} == {'PP-OCRv5_mobile_det', 'PP-OCRv5_server_det'}
    assert {call['text_recognition_model_name'] for call in prepared} == {'PP-OCRv5_mobile_rec', 'PP-OCRv5_server_rec'}
