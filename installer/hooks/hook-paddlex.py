"""Keep metadata used by PaddleX's OCR dependency checks in frozen runtimes.

collect_all only copies a distribution's own metadata. Even recursive
copy_metadata skips dependencies guarded by optional-extra markers.
"""

from importlib.metadata import distribution

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from PyInstaller.utils.hooks import copy_metadata


def collect_ocr_metadata():
    pending = [("paddlex", frozenset({"ocr-core"}))]
    visited = set()
    collected = {}
    while pending:
        name, extras = pending.pop()
        key = (canonicalize_name(name), extras)
        if key in visited:
            continue
        visited.add(key)
        # Fail the build for an incomplete OCR environment instead of shipping
        # an EXE whose modules import but whose pipeline cannot be constructed.
        installed = distribution(name)
        for source, destination in copy_metadata(name):
            collected[destination] = source
        for value in installed.requires or ():
            requirement = Requirement(value)
            if requirement.marker is not None and not any(
                requirement.marker.evaluate({"extra": extra}) for extra in (extras | {""})
            ):
                continue
            pending.append((requirement.name, frozenset(requirement.extras)))
    return [(source, destination) for destination, source in collected.items()]


datas = collect_ocr_metadata()
