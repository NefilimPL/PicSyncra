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
Full installation under SYSTEM in the user's Windows Sandbox still requires
retesting the rebuilt installer.

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
