from pathlib import Path
import hashlib
import json
import zipfile

from picsyncra.installation.contracts import ComponentRef, InstallContext


def test_verified_ocr_archive_becomes_active_only_for_current_release(tmp_path: Path) -> None:
    from picsyncra.installation.ocr_install import install_ocr_component

    program = tmp_path / "program"; state = tmp_path / "state"
    program.mkdir(); state.mkdir()
    (program / "versions" / "42").mkdir(parents=True)
    (program / "active.json").write_text('{"schema":1,"installation_id":"site","release_id":42}', encoding="utf-8")
    archive = tmp_path / "ocr.zip"
    with zipfile.ZipFile(archive, "w") as output: output.writestr("PicSyncra-OCR.exe", b"ocr")
    raw = archive.read_bytes()
    component = ComponentRef("ocr", "ocr-42", "ocr.zip", hashlib.sha256(raw).hexdigest(), len(raw))
    context = InstallContext("site", program, state, state / "config", state / "data.sqlite")

    assert install_ocr_component(context, component, archive) == "ocr-42"
    marker = json.loads((program / "components" / "ocr" / "active.json").read_text(encoding="utf-8"))
    assert marker["release_id"] == 42
