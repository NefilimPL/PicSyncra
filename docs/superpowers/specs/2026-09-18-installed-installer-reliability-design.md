# Reliable Local Installed-Package Build Design

## Goal

Make the locally generated installed-package executable predictable and usable:
it must be emitted next to the other installed build artifacts, launch WEB with
its static assets, use PicSyncra icons, and handle a skipped or selected
portable-configuration import safely.

## Evidence and Root Causes

- Inno Setup currently uses its implicit output location and filename, producing
  `installer/Output/mysetup.exe` instead of an artifact in `dist/installed`.
- The `UninstallRun` task commands omit `RunOnceId`, which causes the compiler
  warning.
- `CreateInputDirPage` validates an empty entry as an invalid directory before
  the current `NextButtonClick` guard can treat it as optional.
- `[Dirs]` pre-creates the destination `...\\config` directory, while
  `copy_configuration()` correctly refuses to overwrite any existing
  destination. Selecting a portable configuration therefore makes the setup
  helper return a non-zero status.
- The installed build passes `--collect-submodules picsyncra` but does not add
  `picsyncra/web/static` as package data. The frozen WEB process consequently
  fails while mounting `StaticFiles`.
- The installed build has no `--icon` options and the Inno script has no
  `SetupIconFile`, although existing local-generator scripts build ICO files
  from `pic/PIC9_WEB.png` and `pic/PIC9_LOCAL.png`.

## Scope

### Artifact placement and generated files

`installer/build_installer.ps1` will pass the build root and release id as it
does today. `installer/PicSyncra.iss` will explicitly set:

- `OutputDir={#BuildRoot}`
- `OutputBaseFilename=PicSyncra-Setup-{#ReleaseId}`

The generated artifact will be `dist/installed/PicSyncra-Setup-<ReleaseId>.exe`.
`installer/Output/` will be ignored for direct manual compiler invocations or
older build outputs; existing `build/` and `dist/` ignore rules continue to
cover PyInstaller artifacts.

### Configuration import

The installer will introduce a boolean wizard page labelled to import portable
configuration. It will default to unchecked. When unchecked, the directory
page is skipped, neither `inspect` nor `import-config` is invoked for that
page, and the runtime creates/uses its normal ProgramData configuration root.

When checked, the existing directory-selection page is shown with its Browse
button. A directory is then deliberately required and must exist. The explicit
opt-in makes this validation correct rather than surprising.

The installer must not create the configuration destination directory in
`[Dirs]`: its parent state root exists, and `copy_configuration()` publishes a
new destination atomically. A runtime without an imported configuration can
create its normal default configuration location later.

### WEB resources and icons

The installed build script will package the same named WEB static assets used
by the portable WEB builder into `picsyncra/web/static` in the frozen runtime.
It will check that every required asset exists before invoking PyInstaller.

The script will generate temporary ICO files in the ignored build work root
from `pic/PIC9_WEB.png` and `pic/PIC9_LOCAL.png`. WEB uses the web icon;
LOCAL, Migrator and Controller use the local icon. The Inno script uses the
local ICO as `SetupIconFile`. Shortcut icons are inherited from their target
executables.

### Compiler warning

Each `[UninstallRun]` entry will receive a distinct stable `RunOnceId`.

## Non-goals

- Do not alter the release zip/manifest upload set in GitHub Actions.
- Do not replace Inno Setup or resolve its commercial license separately.
- Do not package every non-Python file beneath `picsyncra`; only explicitly
  required WEB files are bundled.

## Verification

Automated regression tests will inspect the installer script and local build
script to prove the output path, optional-import flow, atomic destination
contract, static-data arguments and icon settings. The focused installer tests
will run with `pytest`.

For an end-to-end local check, run `Generator exe\\BUILD_INSTALLER.bat 1
--without-ocr`, then verify that `dist/installed/PicSyncra-Setup-1.exe` exists.
Install it in a disposable Windows VM, test both skipped and selected portable
configuration paths, then launch PicSyncra WEB and load its static UI.
