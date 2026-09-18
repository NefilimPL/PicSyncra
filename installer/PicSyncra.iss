; Base installed PicSyncra package.  Version activation and registration are
; deliberately delegated to PicSyncra-SetupHelper through protected request
; files; no secret is placed in an Inno command-line parameter.

#define AppName "PicSyncra"
#define AppId "{{C70B4E13-B158-4E9F-867F-3F0E04DB2283}}"
#ifndef BuildRoot
  #define BuildRoot "..\dist\installed"
#endif
#ifndef ReleaseId
  #define ReleaseId "1"
#endif

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#ReleaseId}
OutputDir={#BuildRoot}
OutputBaseFilename=PicSyncra-Setup-{#ReleaseId}
SetupIconFile={#BuildRoot}\PicSyncra-Setup.ico
DefaultDirName={autopf}\PicSyncra
DefaultGroupName=PicSyncra
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
UninstallDisplayName=PicSyncra
Uninstallable=yes
SetupMutex=Global\PicSyncra.Setup

[Types]
Name: "full"; Description: "WEB i Migrator"
Name: "custom"; Description: "Wybór składników"; Flags: iscustom

[Components]
Name: "web"; Description: "Panel WEB"; Types: full custom; Flags: fixed
Name: "migrator"; Description: "Migrator"; Types: full custom; Flags: fixed
Name: "local"; Description: "Wersja lokalna (opcjonalna)"

[Dirs]
; ProgramData is intentionally not cleaned by the uninstaller: it may contain
; a selected external database, configuration and rollback backups.
Name: "{commonappdata}\PicSyncra\primary-installation"; Flags: uninsneveruninstall
Name: "{commonappdata}\PicSyncra\primary-installation\data"; Flags: uninsneveruninstall
Name: "{commonappdata}\PicSyncra\primary-installation\logs"; Flags: uninsneveruninstall
Name: "{commonappdata}\PicSyncra\primary-installation\cache"; Flags: uninsneveruninstall
Name: "{commonappdata}\PicSyncra\primary-installation\backups"; Flags: uninsneveruninstall
Name: "{commonappdata}\PicSyncra\primary-installation\control"; Flags: uninsneveruninstall
Name: "{commonappdata}\PicSyncra\primary-installation\staging"; Flags: uninsneveruninstall

[Files]
Source: "{#BuildRoot}\versions\{#ReleaseId}\web\*"; DestDir: "{app}\versions\{#ReleaseId}\web"; Components: web; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildRoot}\versions\{#ReleaseId}\migrator\*"; DestDir: "{app}\versions\{#ReleaseId}\migrator"; Components: migrator; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildRoot}\versions\{#ReleaseId}\local\*"; DestDir: "{app}\versions\{#ReleaseId}\local"; Components: local; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildRoot}\PicSyncra-Controller\*"; DestDir: "{app}\controller"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildRoot}\helper\*"; DestDir: "{app}\controller\helper"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildRoot}\active.json"; DestDir: "{app}"; Flags: onlyifdoesntexist ignoreversion

[Registry]
Root: HKLM64; Subkey: "SOFTWARE\PicSyncra\Installations\primary-installation"; ValueType: string; ValueName: "InstallationId"; ValueData: "primary-installation"
Root: HKLM64; Subkey: "SOFTWARE\PicSyncra\Installations\primary-installation"; ValueType: string; ValueName: "ProgramRoot"; ValueData: "{app}"
Root: HKLM64; Subkey: "SOFTWARE\PicSyncra\Installations\primary-installation"; ValueType: string; ValueName: "StateRoot"; ValueData: "{commonappdata}\PicSyncra\primary-installation"
Root: HKLM64; Subkey: "SOFTWARE\PicSyncra\Installations\primary-installation"; ValueType: string; ValueName: "DatabasePath"; ValueData: "{code:SelectedDatabasePath}"; Flags: uninsdeletekey

[Icons]
Name: "{autoprograms}\PicSyncra WEB"; Filename: "{app}\versions\{#ReleaseId}\web\PicSyncra-WEB.exe"; Components: web
Name: "{autoprograms}\PicSyncra Migrator"; Filename: "{app}\versions\{#ReleaseId}\migrator\PicSyncra-Migrator.exe"; Components: migrator
Name: "{autoprograms}\PicSyncra"; Filename: "{app}\versions\{#ReleaseId}\local\PicSyncra.exe"; Components: local

[Run]
Filename: "{sys}\schtasks.exe"; Parameters: "/Create /TN ""PicSyncra Controller primary-installation"" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR """"""{app}\controller\PicSyncra-Controller.exe"" --installation-id primary-installation"""" /F"; Flags: runhidden waituntilterminated
Filename: "{sys}\schtasks.exe"; Parameters: "/Run /TN ""PicSyncra Controller primary-installation"""; Flags: runhidden waituntilterminated

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN ""PicSyncra Controller primary-installation"""; RunOnceId: "stop-controller"; Flags: runhidden waituntilterminated
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""PicSyncra Controller primary-installation"" /F"; RunOnceId: "delete-controller-task"; Flags: runhidden waituntilterminated

[Code]
var
  DataRootPage: TInputDirWizardPage;
  ExistingDatabasePage: TInputFileWizardPage;
  ConfigurationImportPage: TInputOptionWizardPage;
  ConfigurationRootPage: TInputDirWizardPage;

function StateRoot: String;
begin
  Result := ExpandConstant('{commonappdata}\PicSyncra\primary-installation');
end;

function SelectedDatabasePath(Param: String): String;
begin
  if ExistingDatabasePage.Values[0] <> '' then
    Result := ExistingDatabasePage.Values[0]
  else
    Result := AddBackslash(DataRootPage.Values[0]) + 'picsyncra.sqlite';
end;

procedure InitializeWizard;
begin
  DataRootPage := CreateInputDirPage(wpSelectDir,
    'Dane PicSyncra', 'Wybierz katalog danych',
    'Konfiguracja pozostaje w ProgramData. Baza może pozostać w wybranej lokalizacji.',
    False, '');
  DataRootPage.Add('Katalog dla nowej bazy:');
  DataRootPage.Values[0] := StateRoot + '\data';

  ExistingDatabasePage := CreateInputFilePage(DataRootPage.ID,
    'Istniejąca baza', 'Wybierz istniejącą bazę SQLite',
    'To pole jest opcjonalne. Pusta wartość utworzy bazę w wybranym katalogu danych.');
  ExistingDatabasePage.Add('Istniejąca baza:',
    'Bazy SQLite (*.sqlite;*.db)|*.sqlite;*.db|Wszystkie pliki|*.*', 'sqlite');

  ConfigurationImportPage := CreateInputOptionPage(ExistingDatabasePage.ID,
    'Import konfiguracji', 'Czy chcesz zaimportować konfigurację portable?',
    'Pozostaw opcję niezaznaczoną, aby aplikacja użyła domyślnej konfiguracji.',
    False, False);
  ConfigurationImportPage.Add('Importuj konfigurację portable');
  ConfigurationImportPage.Values[0] := False;

  ConfigurationRootPage := CreateInputDirPage(ConfigurationImportPage.ID,
    'Import konfiguracji', 'Wybierz konfigurację portable do importu',
    'Wybierz katalog konfiguracji portable do importu.',
    False, '');
  ConfigurationRootPage.Add('Katalog konfiguracji portable:');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = ConfigurationRootPage.ID) and
    (not ConfigurationImportPage.Values[0]);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = DataRootPage.ID then begin
    if DataRootPage.Values[0] = '' then begin
      MsgBox('Wskaż katalog dla nowej bazy.', mbError, MB_OK);
      Result := False;
    end;
  end else if CurPageID = ExistingDatabasePage.ID then begin
    if (ExistingDatabasePage.Values[0] <> '') and
       (not FileExists(ExistingDatabasePage.Values[0])) then begin
      MsgBox('Wybrana baza nie istnieje.', mbError, MB_OK);
      Result := False;
    end;
  end else if CurPageID = ConfigurationRootPage.ID then begin
    if ConfigurationImportPage.Values[0] and
       (not DirExists(ConfigurationRootPage.Values[0])) then begin
      MsgBox('Wybrany katalog konfiguracji nie istnieje.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function JsonEscape(Value: String): String;
begin
  Result := Value;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
end;

procedure RunSetupHelper(const Command, RequestJson: String);
var
  RequestPath: String;
  ResultCode: Integer;
begin
  RequestPath := ExpandConstant('{app}\controller\helper\setup-request.json');
  if not SaveStringToFile(RequestPath, RequestJson, False) then
    RaiseException('Nie można zapisać chronionego żądania instalatora.');
  try
    if (not Exec(ExpandConstant('{app}\controller\helper\PicSyncra-SetupHelper.exe'),
      Command + ' --request "' + RequestPath + '"', ExpandConstant('{app}'),
      SW_HIDE, ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
      RaiseException('Pomocnik instalatora PicSyncra zakończył się błędem.');
  finally
    DeleteFile(RequestPath);
  end;
end;

procedure ImportSelectedConfiguration;
var
  RequestJson: String;
begin
  if not ConfigurationImportPage.Values[0] then
    exit;
  RequestJson := '{"source_config_root":"' + JsonEscape(ConfigurationRootPage.Values[0]) +
    '","destination_config_root":"' + JsonEscape(StateRoot + '\config') +
    '","database_path":"' + JsonEscape(SelectedDatabasePath('')) + '"}';
  RunSetupHelper('import-config', RequestJson);
end;

procedure InspectSelectedDatabase;
var
  RequestJson: String;
begin
  if ExistingDatabasePage.Values[0] = '' then
    exit;
  RequestJson := '{"database_path":"' + JsonEscape(ExistingDatabasePage.Values[0]) + '"}';
  RunSetupHelper('inspect', RequestJson);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then begin
    { Stop only the registered controller before replacing its own onedir files.
      A missing task on a first installation is harmless. }
    Exec(ExpandConstant('{sys}\schtasks.exe'),
      '/End /TN "PicSyncra Controller primary-installation"', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode);
  end;
  if CurStep = ssPostInstall then begin
    InspectSelectedDatabase;
    ImportSelectedConfiguration;
  end;
end;
