# Controller startup investigation — 2026-10-05

Reported failure: the installed WEB manager in Windows Sandbox on another
computer displayed "Kontroler instalacji nie uruchomil backendu WWW", including
when started as administrator.

Three independent Windows integration failures were reproduced:

1. The installer `/TR` quoting split a `Program Files` executable path into
   multiple command arguments. Registration now uses one correctly escaped
   task action and checks both scheduler command exit codes.
2. Pipe authorization passed a primary process token to
   `CheckTokenMembership`, which requires an impersonation token. Native
   Windows testing returned error 1309. The caller token is now duplicated
   for membership testing and every acquired handle is closed. The SYSTEM /
   Administrators ACL is unchanged.
3. With authorization working, a real controller start failed at
   `win32job.CreateJobObject(None, None)`: pywin32 rejected the name as a
   non-string. An empty name creates the intended anonymous job. The native
   job regression verifies that closing the job terminates its owned child.

The previous direct frozen WEB smoke test did not exercise these boundaries.
The replacement smoke check invokes the real manager start/stop functions,
named-pipe transport, dispatcher, controller, Windows Job Object and frozen
WEB in an isolated build directory. It verifies the health endpoint and
static UI. Its test pipe permits the current test user only; it does not
create a scheduled task or HKLM registration. Administrator token membership
and Windows task-command parsing are covered by separate native regressions.
The user subsequently confirmed that the corrected installer starts the panel
in Windows Sandbox on the other computer.

Verification results:

- Whole suite: 1906 passed, 3 skipped, 66 subtests passed (25 existing
  deprecation warnings).
- Focused installer, controller and update tests: 32 passed.
- Real manager-to-controller start/stop smoke: passed, with a healthy frozen
  WEB process and a served static UI.
- Executed the packaged controller's embedded bytecode against native Windows
  APIs: anonymous job creation and process-token membership both passed.
- `git diff --check`: passed.
- Final Inno Setup compilation: exit 0, no compiler warnings. The corrected
  artifact is `dist/installer-fixed/PicSyncra-Setup-1-fixed.exe`; the normal
  `dist/installed/PicSyncra-Setup-1.exe` is an identical verified copy.

Publication status checked through the public GitHub API on 2026-10-05:

- Latest release `v0.5.5` has only the three portable EXE assets.
- The active workflow list does not include `build-installer.yml`.
- The local installed-package workflow defines four component ZIP assets
  and a signed manifest, but those assets are not currently published.
- The updater downloads the complete non-OCR release bundle. Installed OCR
  is updated with it; absent OCR is not downloaded. Independent updates of
  only changed WEB/Migrator/LOCAL modules are not implemented.
- The local trusted-public-key mapping is empty, so a local unsigned build
  deliberately cannot accept remote updates.

## Missing OCR/update controls in the installed WEB panel

The installed WEB HTML referenced `installation-updates.js` and
`legacy-migration.js`, but the builder's static-asset list omitted both. The
shipped directory confirmed their absence. Without `InstallationUpdates`,
the renderer returns before creating the installed-update controls, including
the OCR download button. This affects local builds and Actions builds alike.

Both scripts are now packaged. The existing build harness now checks that all
static assets referenced by the packaged main and login pages are present.
It failed on those two missing scripts before the fix and passed afterward.
Verification: 25 focused Python tests and 4 JavaScript updater tests passed;
the real controller/frozen-WEB smoke served both scripts with the expected
contents. Inno Setup compiled the replacement installer successfully.

Artifact: `dist/installer-updates-fixed/PicSyncra-Setup-1-updates-fixed.exe`.
SHA256: `CAAE731E63739A2B342871E1A4EC7CDB5708D8726124338578ACBE469BE9AA6E`.
The button alone does not provide an OCR download source: signed installed
release assets and compiled trusted public keys are still required.

## Modular installer acceptance — 2026-10-05, dev2

The release-only limitation above describes the earlier installer. The current
implementation uses independent module identities, signed schema-2 manifests,
exact HTTP ranges, one controller transaction, and shared WEB/launcher plans.
Rollback selections remain drafts until confirmation; successful rollback pins
those modules across client and controller restarts. LOCAL and Migrator hold an
installation lease before loading application code and throughout their lifetime.

Independent whole-change review found and prompted regression fixes for broken
WEB startup, stale maintenance after interruption, unsafe manual start after
failed recovery, standalone writers, application payload ownership, configuration
inspection, and disk/write preflight. Follow-up review checked the missing-set
recovery path and host-selection race. An unhealthy restored backend is stopped
and remains gated in `recovery_required`.

Fresh verification of the final source and local build:

- Python: **1972 passed, 3 skipped, 66 subtests passed**, with 25 existing
  deprecation warnings. Log: `build/modular-full-tests-acceptance.log`.
- Browser JavaScript: **39 passed**; edited scripts pass `node --check`.
- Emitted assets reconstructed: **11 modules** in the local no-OCR build;
  controller/content/recovery acceptance: **12 passed**.
- Real Windows named pipe, dispatcher, controller and Job Object launched the
  selected frozen WEB; health and module-related static assets were served.
- Actual frozen launcher EXE with packaged Tcl/Tk read the catalog through a
  real pipe, selected two modules, prepared one rollback plan and canceled it
  with both choices preserved and zero execution requests. The isolated test
  registration provider and UAC bypass are test hooks, absent from production.
- Separate frozen selected-import probe loaded old FTP/current SQL and refused
  startup after the selected FTP file disappeared.
- **22 critical packaged modules** match the reviewed source bytecode in the
  controller, launcher and WEB/Migrator/LOCAL hosts.
- Repeated full installer compilation: exit 0; final Inno compile 306.735 s.
  `git diff --check` passed.

Artifact: `dist/installed/PicSyncra-Setup-1.exe` (378,960,509 bytes).
SHA256: `C91EBED5E96E8164ABE0F6C5545470C1F1A099183AC38965B64C4701EF1BC855`.

The acceptance fixtures do not modify HKLM or register scheduled tasks. Native
Tk smoke required execution outside the test sandbox's Tcl restriction; the
packaged GUI passed. Interruption recovery is tested with injected process
failure and real SQLite/configuration files, not a physical power interruption.
Real GitHub publication/signing secrets and downloading full OCR models remain
external release steps. No Release was published and no production signing key
was created or changed. The local installer has no compiled trusted public key,
so it displays controls but cannot download an official unsigned OCR/update
source. Actions must publish signed complete module assets from the release tag.
