"""Real Inno regression for the exact Windows MAX_PATH compression boundary."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Inno and SUBST')
@pytest.mark.parametrize('fail', [False,True], ids=['success','compiler-error'])
def test_native_compilation_uses_short_paths_and_removes_only_its_drive(tmp_path, fail):
    compiler = shutil.which('ISCC.exe')
    shell = shutil.which('powershell') or shutil.which('pwsh')
    if not compiler or not shell: pytest.skip('Inno and PowerShell required')
    dist = tmp_path / 'dist'; dist.mkdir()
    payload = dist / 'payload'
    name = 'epilogue_per_row_per_col_scale.h'
    padding = 260 - len(str(payload)) - len(name) - 2
    if padding < 1: pytest.skip('Workspace is too long for the exact 260 character probe')
    source = payload / ('d' * padding) / name
    source.parent.mkdir(parents=True); source.write_bytes(b'inert test header')
    assert len(str(source)) == 260
    script = tmp_path / 'path-probe.iss'
    script.write_text('''[Setup]
AppName=Path probe
AppVersion=1
DefaultDirName={tmp}\\PathProbe
PrivilegesRequired=lowest
OutputDir={#BuildRoot}
OutputBaseFilename=path-probe
[Files]
Source: "{#BuildRoot}\\payload\\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs
[Code]
function InitializeSetup: Boolean;
begin
  Result := False;
end;
''' + ('\ninvalid directive to force a compiler failure\n' if fail else ''), encoding='utf-8')
    before = subprocess.run(['subst'],capture_output=True,check=True).stdout
    result = subprocess.run([shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',
        str(ROOT / 'installer/compile_installer.ps1'),'-BuildRoot',str(dist),'-ReleaseId','1',
        '-BaseSetId','a'*64,'-LocalSetId','b'*64,'-Compiler',compiler,'-ScriptPath',str(script)],
        capture_output=True,timeout=60)
    after = subprocess.run(['subst'],capture_output=True,check=True).stdout
    assert after == before, 'Compiler drive mapping leaked or changed an existing mapping'
    output = (result.stdout + result.stderr).decode(errors='replace')
    if fail:
        assert result.returncode != 0 and not (dist / 'path-probe.exe').exists()
        assert 'Inno' in output
    else:
        assert result.returncode == 0, output
        assert (dist / 'path-probe.exe').is_file()
        assert source.read_bytes() == b'inert test header'
