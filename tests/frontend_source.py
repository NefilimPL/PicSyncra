"""Read source characterization ranges across extracted browser scripts.

Function markers preserve their original positions for older range-based tests.
The replacement is read from the real owner file; it is never a saved copy.
Browser execution and script ordering are checked independently.
"""
from pathlib import Path
import re


def read_frontend_source(path: Path) -> str:
    source = path.read_text(encoding='utf-8')
    def expand(match):
        owner, name = match.groups()
        owned = (path.parent / owner).read_text(encoding='utf-8')
        start = re.search(r'^(?:async )?function ' + re.escape(name) + r'\(', owned, re.M)
        assert start, f'Missing function {name} in {owner}'
        end = owned.index('\n}', start.end()) + 2
        return owned[start.start():end]
    return re.sub(r'^// @module-function ([\w-]+\.js) (\w+)$', expand, source, flags=re.M)
