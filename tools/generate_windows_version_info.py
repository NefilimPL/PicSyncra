"""Generate a PyInstaller Windows VERSIONINFO file."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import os
import re
from pathlib import Path


VERSION_ENV_VAR = "PICSYNCRA_VERSION"
DEFAULT_VERSION = "dev"
DEFAULT_PRODUCT_NAME = "PicSyncra"
DEFAULT_COMPANY_NAME = "NefilimPL"


@dataclass(frozen=True)
class BuildMetadata:
    product_name: str
    company_name: str
    legal_copyright: str
    source: str


def _clean_version(value: object) -> str:
    text = str(value or "").strip()
    return text or DEFAULT_VERSION


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def read_build_version(repo_root: Path, explicit_version: str | None = None) -> str:
    if explicit_version:
        return _clean_version(explicit_version)

    env_version = os.environ.get(VERSION_ENV_VAR)
    if env_version:
        return _clean_version(env_version)

    version_path = repo_root / "picsyncra" / "VERSION"
    try:
        return _clean_version(version_path.read_text(encoding="utf-8"))
    except OSError:
        return DEFAULT_VERSION


def version_to_windows_tuple(version: str) -> tuple[int, int, int, int]:
    cleaned = _clean_version(version)
    numbers = [int(match) for match in re.findall(r"\d+", cleaned)]
    if not numbers:
        return (0, 0, 0, 0)

    if cleaned.lower().startswith("dev-") and len(numbers) == 1:
        numbers = [0, 0, 0, numbers[0]]

    padded = (numbers + [0, 0, 0, 0])[:4]
    return tuple(min(part, 65535) for part in padded)


def _read_windows_registered_values() -> tuple[str, str]:
    if os.name != "nt":
        return ("", "")

    try:
        import winreg

        key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            try:
                organization = str(winreg.QueryValueEx(key, "RegisteredOrganization")[0])
            except OSError:
                organization = ""
            try:
                owner = str(winreg.QueryValueEx(key, "RegisteredOwner")[0])
            except OSError:
                owner = ""
    except OSError:
        return ("", "")

    return (organization.strip(), owner.strip())


def _metadata_from_github(env: dict[str, str]) -> BuildMetadata:
    repository = _first_text(env.get("GITHUB_REPOSITORY"))
    owner = _first_text(env.get("GITHUB_REPOSITORY_OWNER"))
    repo_name = ""
    if repository and "/" in repository:
        repo_owner, repo_name = repository.split("/", 1)
        owner = _first_text(owner, repo_owner)

    company_name = _first_text(owner, env.get("GITHUB_ACTOR"), DEFAULT_COMPANY_NAME)
    product_name = _first_text(repo_name, DEFAULT_PRODUCT_NAME)
    return BuildMetadata(
        product_name=product_name,
        company_name=company_name,
        legal_copyright=f"Copyright (C) {date.today().year} {company_name}",
        source="github",
    )


def _metadata_from_windows(env: dict[str, str]) -> BuildMetadata:
    organization, owner = _read_windows_registered_values()
    company_name = _first_text(
        organization,
        owner,
        env.get("USERDOMAIN") and env.get("USERNAME")
        and f"{env.get('USERDOMAIN')}\\{env.get('USERNAME')}",
        env.get("USERNAME"),
        DEFAULT_COMPANY_NAME,
    )
    return BuildMetadata(
        product_name=DEFAULT_PRODUCT_NAME,
        company_name=company_name,
        legal_copyright=f"Copyright (C) {date.today().year} {company_name}",
        source="windows",
    )


def resolve_build_metadata(
    *,
    metadata_source: str = "auto",
    product_name: str | None = None,
    company_name: str | None = None,
    legal_copyright: str | None = None,
    env: dict[str, str] | None = None,
) -> BuildMetadata:
    current_env = dict(os.environ if env is None else env)
    source = metadata_source
    if source == "auto":
        source = "github" if current_env.get("GITHUB_ACTIONS") == "true" else "windows"

    if source == "github":
        metadata = _metadata_from_github(current_env)
    elif source == "windows":
        metadata = _metadata_from_windows(current_env)
    else:
        raise ValueError(f"Unsupported metadata source: {metadata_source}")

    resolved_company_name = _first_text(company_name, metadata.company_name)
    return BuildMetadata(
        product_name=_first_text(product_name, metadata.product_name),
        company_name=resolved_company_name,
        legal_copyright=_first_text(
            legal_copyright,
            metadata.legal_copyright,
            f"Copyright (C) {date.today().year} {resolved_company_name}",
        ),
        source=metadata.source,
    )


def build_version_info_text(
    *,
    version: str,
    file_description: str,
    internal_name: str,
    original_filename: str,
    product_name: str,
    company_name: str,
    legal_copyright: str,
) -> str:
    numeric_version = version_to_windows_tuple(version)
    strings = {
        "CompanyName": company_name,
        "FileDescription": file_description,
        "FileVersion": version,
        "InternalName": internal_name,
        "LegalCopyright": legal_copyright,
        "OriginalFilename": original_filename,
        "ProductName": product_name,
        "ProductVersion": version,
    }
    string_structs = "\n".join(
        f"          StringStruct({key!r}, {value!r}),"
        for key, value in strings.items()
    )

    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numeric_version!r},
    prodvers={numeric_version!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904b0',
        [
{string_structs}
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a PyInstaller --version-file for Windows EXE builds."
    )
    parser.add_argument("--output", required=True, help="Path to write the version file.")
    parser.add_argument("--version", help="Version string to embed. Defaults to env/file.")
    parser.add_argument(
        "--metadata-source",
        choices=("auto", "github", "windows"),
        default="auto",
        help="Metadata source. auto uses GitHub Actions env on CI and Windows data locally.",
    )
    parser.add_argument(
        "--file-description",
        required=True,
        help="Windows FileDescription value.",
    )
    parser.add_argument(
        "--internal-name",
        required=True,
        help="Windows InternalName value.",
    )
    parser.add_argument(
        "--original-filename",
        required=True,
        help="Windows OriginalFilename value.",
    )
    parser.add_argument(
        "--product-name",
        help="Windows ProductName value. Defaults to GitHub repo name or PicSyncra.",
    )
    parser.add_argument(
        "--company-name",
        help="Windows CompanyName value. Defaults to GitHub owner or Windows registration.",
    )
    parser.add_argument(
        "--legal-copyright",
        help="Windows LegalCopyright value. Defaults to current year and company.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    version = read_build_version(repo_root, args.version)
    metadata = resolve_build_metadata(
        metadata_source=args.metadata_source,
        product_name=args.product_name,
        company_name=args.company_name,
        legal_copyright=args.legal_copyright,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_version_info_text(
            version=version,
            file_description=args.file_description,
            internal_name=args.internal_name,
            original_filename=args.original_filename,
            product_name=metadata.product_name,
            company_name=metadata.company_name,
            legal_copyright=metadata.legal_copyright,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
