from __future__ import annotations

from picsyncra.file_tokens import FileTokenRegistry


def test_registry_issues_an_opaque_token_for_a_trusted_path() -> None:
    registry = FileTokenRegistry()
    path = r"C:\\photos\\BLACK\\NO-LED\\5901234567890_01.jpg"

    token = registry.issue(path)

    assert path not in token
    assert registry.resolve(token) == path


def test_registry_rejects_an_expired_token() -> None:
    now = [100.0]
    registry = FileTokenRegistry(max_age_seconds=10, clock=lambda: now[0])
    token = registry.issue("/trusted/photo.jpg")
    now[0] = 111.0

    assert registry.resolve(token) is None
