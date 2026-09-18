# Installed Installer Reliability Implementation Plan

> For agentic workers: required sub-skill: use superpowers:executing-plans task by task. Steps use checkboxes.

**Goal:** Make locally built PicSyncra installers land in dist/installed, install without a forced portable-config path, start WEB with static assets, and display PicSyncra icons.

**Architecture:** installer/build_installer.ps1 remains the common local and CI build entry point. It creates temporary icons, declares WEB data arguments, builds onedir components, and calls Inno Setup. installer/PicSyncra.iss owns installer UX and output naming, and does not pre-create the atomic import destination.

**Tech Stack:** PowerShell, PyInstaller, Inno Setup 6 Pascal Script, pytest.

**Spec:** docs/superpowers/specs/2026-09-18-installed-installer-reliability-design.md

## Global Constraints

- Do not alter GitHub release upload contents.
- Preserve the stable AppId and mandatory WEB/Migrator components.
- An unchecked configuration import must not run the setup helper.
- A selected import publishes configuration to a non-existing destination.
- Bundle only named WEB static files and keep generated artifacts ignored.

---

### Task 1: Add installer packaging regression tests

**Files:**
- Modify: tests/test_installer_layout.py
- Modify: tests/test_installed_build_script.py

**Interfaces:**
- Consumes: text of installer/PicSyncra.iss and installer/build_installer.ps1.
- Produces: source-level regression checks before implementation.

- [ ] Step 1: Add a test in test_installer_layout.py requiring these strings in the installer:

    assert 'OutputDir={#BuildRoot}' in installer
    assert 'OutputBaseFilename=PicSyncra-Setup-{#ReleaseId}' in installer
    assert 'SetupIconFile={#BuildRoot}\\PicSyncra-Setup.ico' in installer
    assert 'RunOnceId: "stop-controller"' in installer
    assert 'RunOnceId: "delete-controller-task"' in installer
    assert 'ConfigurationImportPage := CreateInputOptionPage' in installer
    assert 'ConfigurationImportPage.Values[0] := False;' in installer
    assert 'not ConfigurationImportPage.Values[0]' in installer
    assert 'Name: "{commonappdata}\\PicSyncra\\primary-installation\\config"' not in installer

- [ ] Step 2: Run python -m pytest tests/test_installer_layout.py -q. Confirm RED because the output directives, option page, skip condition, and RunOnceIds are absent and the config directory line is present.

- [ ] Step 3: Add a test in test_installed_build_script.py requiring PNG-derived ICO generation, --icon, named static assets including runtime-status.js, destination picsyncra\\web\\static, and installer/Output/ in .gitignore.

- [ ] Step 4: Run python -m pytest tests/test_installed_build_script.py -q. Confirm RED because the installed build has neither icon nor static-data construction.

### Task 2: Implement Inno output and optional import

**Files:**
- Modify: installer/PicSyncra.iss
- Modify: .gitignore
- Test: tests/test_installer_layout.py

**Interfaces:**
- Consumes: BuildRoot and ReleaseId defines.
- Produces: PicSyncra-Setup-<ReleaseId>.exe under BuildRoot and explicit opt-in configuration import.

- [ ] Step 1: Under [Setup], add OutputDir={#BuildRoot}, OutputBaseFilename=PicSyncra-Setup-{#ReleaseId}, and SetupIconFile={#BuildRoot}\PicSyncra-Setup.ico.
- [ ] Step 2: Add distinct RunOnceId properties stop-controller and delete-controller-task to [UninstallRun].
- [ ] Step 3: Declare ConfigurationImportPage as TInputOptionWizardPage after the database page, add an unchecked import option, and position the existing directory page after it.
- [ ] Step 4: Add ShouldSkipPage returning (PageID = ConfigurationRootPage.ID) and (not ConfigurationImportPage.Values[0]). Gate directory validation and ImportSelectedConfiguration with the same flag.
- [ ] Step 5: Remove only the config directory [Dirs] entry. Retain the state root and other directories.
- [ ] Step 6: Add installer/Output/ to .gitignore.
- [ ] Step 7: Run python -m pytest tests/test_installer_layout.py -q. Confirm GREEN.

### Task 3: Package WEB static assets and create icons

**Files:**
- Modify: installer/build_installer.ps1
- Test: tests/test_installed_build_script.py

**Interfaces:**
- Consumes: pic/PIC9_WEB.png, pic/PIC9_LOCAL.png, and named files in picsyncra/web/static.
- Produces: temporary web/local ICO files, dist/installed/PicSyncra-Setup.ico, WEB static assets under _internal/picsyncra/web/static, and icons in user-launched executables.

- [ ] Step 1: Add a helper converting a supplied PNG to ICO through Pillow at 256,128,64,48,32,16. Create web.ico and local.ico below $workRoot\icons and copy local.ico to $distRoot\PicSyncra-Setup.ico.
- [ ] Step 2: Add a helper that verifies and returns --add-data pairs for app.css, app.js, autocomplete.js, index.html, latest-request.js, login.html, login.js, module-build-status.js, ocr-diagnostics.js, process-jobs.js, and runtime-status.js. Every pair targets picsyncra\web\static and a missing source throws a clear error.
- [ ] Step 3: Extend Build-Onedir with an icon and optional extra PyInstaller arguments. Pass --icon $IconPath. WEB receives web.ico and static data; Migrator, LOCAL, and Controller receive local.ico. Keep the non-user-facing helper spec unchanged.
- [ ] Step 4: Run python -m pytest tests/test_installed_build_script.py -q. Confirm GREEN.

### Task 4: Verify integrated package behavior

**Files:**
- Verify: installer/PicSyncra.iss
- Verify: installer/build_installer.ps1
- Verify: .gitignore
- Verify: focused installer tests

- [ ] Step 1: Run python -m pytest tests/test_installer_layout.py tests/test_installed_build_script.py -q. Confirm all pass.
- [ ] Step 2: After a prepared build, run ISCC.exe with /DBuildRoot=<absolute dist/installed> and /DReleaseId=1. Confirm no constant or UninstallRun warning and output dist/installed/PicSyncra-Setup-1.exe.
- [ ] Step 3: Run .\Generator exe\BUILD_INSTALLER.bat 1 --without-ocr when resources permit. Confirm the setup EXE and _internal\picsyncra\web\static\index.html.
- [ ] Step 4: Run git diff --check and git status --short. Confirm no whitespace errors and only planned files are changed.
