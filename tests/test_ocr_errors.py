import pytest
import subprocess
import sys

from picsyncra.installation.ocr_errors import format_ocr_error as host_format
from picsyncra.services.ocr_errors import format_ocr_error as module_format


@pytest.fixture(params=[host_format, module_format], ids=["embedded-host", "ocr-module"])
def format_ocr_error(request):
    return request.param


def test_long_wrappers_do_not_hide_dependency_cause(format_ocr_error):
    root = ModuleNotFoundError("missing OCR dependency")
    wrapper = RuntimeError("pipeline " * 1000)
    wrapper.__cause__ = root
    message = format_ocr_error(wrapper)
    assert message.startswith("ModuleNotFoundError: missing OCR dependency")
    assert len(message) <= 2048


def test_exception_cycles_are_bounded_and_suppressed_context_is_private(format_ocr_error):
    root = ValueError("cause")
    wrapper = RuntimeError("wrapper")
    wrapper.__cause__ = root
    root.__cause__ = wrapper
    assert format_ocr_error(wrapper).count("wrapper") == 1
    private = RuntimeError("public")
    private.__context__ = ValueError("hidden")
    private.__suppress_context__ = True
    assert "hidden" not in format_ocr_error(private)


def test_updated_ocr_imports_without_helpers_from_a_newer_embedded_host():
    script = '''
import importlib.abc
import sys
class OlderHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "picsyncra.installation.ocr_errors":
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, OlderHost())
import picsyncra.services.image_dimensions
import picsyncra.services.ocr_worker_process
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
