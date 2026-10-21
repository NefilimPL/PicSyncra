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
RestartApplications=no

[Tasks]
Name: "desktopicons"; Description: "Utwórz skróty PicSyncra na pulpicie"; Flags: unchecked
Name: "backendautostart"; Description: "Uruchamiaj panel WEB w tle po starcie Windows (także bez logowania użytkownika)"; Flags: unchecked

[Types]
Name: "full"; Description: "WEB i Migrator"
Name: "custom"; Description: "Wybór składników"; Flags: iscustom

[Components]
Name: "web"; Description: "Panel WEB"; Types: full custom; Flags: fixed
Name: "migrator"; Description: "Migrator"; Types: full custom; Flags: fixed
Name: "local"; Description: "Wersja lokalna (opcjonalna)"
#ifdef OcrSetId
Name: "ocr"; Description: "OCR — silnik i modele (opcjonalne, instalacja bez Internetu)"
#endif

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
Source: "{#BuildRoot}\PicSyncra-AppEntry\_internal\*"; DestDir: "{app}\apps\_internal"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildRoot}\PicSyncra-AppEntry\PicSyncra-AppEntry.exe"; DestDir: "{app}\apps"; DestName: "PicSyncra-WEB.exe"; Flags: ignoreversion; Components: web
Source: "{#BuildRoot}\PicSyncra-AppEntry\PicSyncra-AppEntry.exe"; DestDir: "{app}\apps"; DestName: "PicSyncra-Migrator.exe"; Flags: ignoreversion; Components: migrator
Source: "{#BuildRoot}\PicSyncra-AppEntry\PicSyncra-AppEntry.exe"; DestDir: "{app}\apps"; DestName: "PicSyncra.exe"; Flags: ignoreversion; Components: local
; A new helper runs outside the installed directories, including when the old
; controller/launcher cannot understand the new module update protocol.
Source: "{#BuildRoot}\helper\*"; DestDir: "{tmp}\PicSyncra-SetupHelper"; Flags: dontcopy noencryption recursesubdirs createallsubdirs
Source: "{#BuildRoot}\module-sets\{#BaseSetId}\*"; DestDir: "{app}\sets\{#BaseSetId}"; Check: (not WizardIsComponentSelected('local')) and (not OcrSelected); Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildRoot}\module-sets\{#LocalSetId}\*"; DestDir: "{app}\sets\{#LocalSetId}"; Components: local; Check: not OcrSelected; Flags: recursesubdirs createallsubdirs ignoreversion
#ifdef OcrSetId
Source: "{#BuildRoot}\module-sets\{#OcrSetId}\*"; DestDir: "{app}\sets\{#OcrSetId}"; Components: ocr; Check: not WizardIsComponentSelected('local'); Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildRoot}\module-sets\{#LocalOcrSetId}\*"; DestDir: "{app}\sets\{#LocalOcrSetId}"; Components: ocr; Check: WizardIsComponentSelected('local'); Flags: recursesubdirs createallsubdirs ignoreversion
#endif
Source: "{#BuildRoot}\PicSyncra-Controller\*"; DestDir: "{app}\controller"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildRoot}\helper\*"; DestDir: "{app}\controller\helper"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#BuildRoot}\module-initial-layout.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildRoot}\PicSyncra-Launcher\*"; DestDir: "{app}\launcher"; Flags: recursesubdirs createallsubdirs ignoreversion

[Registry]
Root: HKLM64; Subkey: "SOFTWARE\Classes\picsyncra-update"; ValueType: string; ValueData: "URL:PicSyncra one-time update authorization"; Flags: uninsdeletekey
Root: HKLM64; Subkey: "SOFTWARE\Classes\picsyncra-update"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKLM64; Subkey: "SOFTWARE\Classes\picsyncra-update\shell\open\command"; ValueType: string; ValueData: """{app}\launcher\PicSyncra-Launcher.exe"" --authorize-url ""%1"""
Root: HKLM64; Subkey: "SOFTWARE\PicSyncra\Installations\primary-installation"; ValueType: string; ValueName: "InstallationId"; ValueData: "primary-installation"
Root: HKLM64; Subkey: "SOFTWARE\PicSyncra\Installations\primary-installation"; ValueType: string; ValueName: "ProgramRoot"; ValueData: "{app}"
Root: HKLM64; Subkey: "SOFTWARE\PicSyncra\Installations\primary-installation"; ValueType: string; ValueName: "StateRoot"; ValueData: "{commonappdata}\PicSyncra\primary-installation"
Root: HKLM64; Subkey: "SOFTWARE\PicSyncra\Installations\primary-installation"; ValueType: string; ValueName: "DatabasePath"; ValueData: "{code:SelectedDatabasePath}"; Flags: uninsdeletekey

[Icons]
Name: "{autoprograms}\PicSyncra WEB"; Filename: "{app}\apps\PicSyncra-WEB.exe"; Components: web
Name: "{autoprograms}\PicSyncra Migrator"; Filename: "{app}\apps\PicSyncra-Migrator.exe"; Components: migrator
Name: "{autoprograms}\PicSyncra"; Filename: "{app}\apps\PicSyncra.exe"; Components: local
Name: "{autodesktop}\PicSyncra WEB"; Filename: "{app}\apps\PicSyncra-WEB.exe"; Tasks: desktopicons; Components: web
Name: "{autodesktop}\PicSyncra Migrator"; Filename: "{app}\apps\PicSyncra-Migrator.exe"; Tasks: desktopicons; Components: migrator
Name: "{autodesktop}\PicSyncra"; Filename: "{app}\apps\PicSyncra.exe"; Tasks: desktopicons; Components: local
Name: "{autoprograms}\PicSyncra Aktualizator"; Filename: "{app}\launcher\PicSyncra-Launcher.exe"

[Run]
Filename: "{app}\launcher\PicSyncra-Launcher.exe"; Description: "Otwórz launcher PicSyncra (panel WEB i ikona w trayu)"; Flags: postinstall nowait skipifsilent; Check: SetupCompletedSuccessfully

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN ""PicSyncra Controller primary-installation"""; RunOnceId: "stop-controller"; Flags: runhidden waituntilterminated
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""PicSyncra Controller primary-installation"" /F"; RunOnceId: "delete-controller-task"; Flags: runhidden waituntilterminated

[Code]
const
  ControllerTaskParameters = '/Create /TN "PicSyncra Controller primary-installation" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR "\"{app}\controller\PicSyncra-Controller.exe\" --installation-id primary-installation" /F';

var
  DataRootPage: TInputDirWizardPage;
  ExistingDatabasePage: TInputFileWizardPage;
  ConfigurationImportPage: TInputOptionWizardPage;
  ConfigurationRootPage: TInputDirWizardPage;
  SetupSucceeded: Boolean;
  HadPreviousInstallation: Boolean;

function SetupCompletedSuccessfully: Boolean;
begin
  Result := SetupSucceeded;
end;

function OcrSelected: Boolean;
begin
#ifdef OcrSetId
  Result := WizardIsComponentSelected('ocr');
#else
  Result := False;
#endif
end;

function JsonBoolean(Value: Boolean): String;
begin
  if Value then Result := 'true' else Result := 'false';
end;

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
var
  ExistingDatabase: String;
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
  if RegQueryStringValue(HKLM64, 'SOFTWARE\PicSyncra\Installations\primary-installation',
    'DatabasePath', ExistingDatabase) then begin
    ExistingDatabasePage.Values[0] := ExistingDatabase;
    DataRootPage.Values[0] := ExtractFileDir(ExistingDatabase);
  end;

  ConfigurationImportPage := CreateInputOptionPage(ExistingDatabasePage.ID,
    'Import konfiguracji', 'Czy chcesz zaimportować konfigurację portable?',
    'Przy aktualizacji dotychczasowa konfiguracja zostaje zachowana. Import dotyczy tylko nowej instalacji.',
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
  Result := ((PageID = ConfigurationRootPage.ID) and
    (not ConfigurationImportPage.Values[0])) or
    (((PageID = ConfigurationImportPage.ID) or (PageID = ConfigurationRootPage.ID)) and
      DirExists(StateRoot + '\config'));
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
  ErrorText: AnsiString;
  ResultCode: Integer;
begin
  RequestPath := ExpandConstant('{app}\controller\helper\setup-request.json');
  if not SaveStringToFile(RequestPath, UTF8Encode(RequestJson), False) then
    RaiseException('Nie można zapisać chronionego żądania instalatora.');
  try
    if (not Exec(ExpandConstant('{app}\controller\helper\PicSyncra-SetupHelper.exe'),
      Command + ' --request "' + RequestPath + '"', ExpandConstant('{app}'),
      SW_HIDE, ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
    begin
      if LoadStringFromFile(ChangeFileExt(RequestPath, '.error.txt'), ErrorText) then
        RaiseException('PicSyncra: ' + UTF8Decode(ErrorText));
      RaiseException('Pomocnik instalatora PicSyncra zakończył się błędem (kod ' + IntToStr(ResultCode) + ').');
    end;
  finally
    DeleteFile(RequestPath);
    DeleteFile(ChangeFileExt(RequestPath, '.error.txt'));
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  RequestPath: String;
  ResultCode: Integer;
  ErrorText: AnsiString;
begin
  Result := '';
  SetupSucceeded := False;
  HadPreviousInstallation := FileExists(ExpandConstant('{app}\active.json'));
  try
    WizardForm.StatusLabel.Caption := 'Sprawdzanie instalacji i zatrzymywanie backendu przed wymianą plików…';
    ExtractTemporaryFiles('{tmp}\PicSyncra-SetupHelper\*');
    RequestPath := ExpandConstant('{tmp}\PicSyncra-SetupHelper\prepare-request.json');
    if not SaveStringToFile(RequestPath, '{"installation_id":"primary-installation","enabled":false}', False) then
      RaiseException('Nie można zapisać żądania instalatora.');
    if (not Exec(ExpandConstant('{tmp}\PicSyncra-SetupHelper\PicSyncra-SetupHelper.exe'),
      'prepare-upgrade --request "' + RequestPath + '"', '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then begin
      if LoadStringFromFile(ChangeFileExt(RequestPath, '.error.txt'), ErrorText) then
        RaiseException(UTF8Decode(ErrorText));
      RaiseException('Nie można przygotować instalacji. Pliki nie zostały zmienione (kod ' + IntToStr(ResultCode) + ').');
    end;
  except
    Result := GetExceptionMessage;
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

procedure RunControllerTask(const Parameters, FailureMessage: String);
var
  ResultCode: Integer;
begin
  ResultCode := 0;
  if (not Exec(ExpandConstant('{sys}\schtasks.exe'),
    ExpandConstant(Parameters), '', SW_HIDE, ewWaitUntilTerminated, ResultCode)) or
    (ResultCode <> 0) then
    RaiseException(FailureMessage + ' (kod ' + IntToStr(ResultCode) + ').');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  StartupJson: String;
  FailureMessage: String;
begin
  if CurStep = ssPostInstall then begin
    if WizardIsTaskSelected('backendautostart') then
      StartupJson := '{"installation_id":"primary-installation","enabled":true}'
    else
      StartupJson := '{"installation_id":"primary-installation","enabled":false}';
    try
    WizardForm.StatusLabel.Caption := 'Weryfikowanie bazy i aktywowanie modułów z instalatora…';
    InspectSelectedDatabase;
    ImportSelectedConfiguration;
    RunSetupHelper('initialize-modules', '{"installation_id":"primary-installation","program_root":"' + JsonEscape(ExpandConstant('{app}')) + '","state_root":"' + JsonEscape(StateRoot) + '","database_path":"' + JsonEscape(SelectedDatabasePath('')) + '","include_local":' + JsonBoolean(WizardIsComponentSelected('local')) + ',"include_ocr":' + JsonBoolean(OcrSelected) + '}');
    RunSetupHelper('configure-startup', StartupJson);
    RunControllerTask(ControllerTaskParameters,
      'Nie można zarejestrować zadania kontrolera PicSyncra');
    RunControllerTask('/Run /TN "PicSyncra Controller primary-installation"',
      'Nie można uruchomić zadania kontrolera PicSyncra');
    WizardForm.StatusLabel.Caption := 'Sprawdzanie uruchomienia kontrolera i panelu WEB…';
    RunSetupHelper('verify-startup', StartupJson);
    SetupSucceeded := True;
    except
      FailureMessage := GetExceptionMessage;
      if HadPreviousInstallation or FileExists(ExpandConstant('{app}\active.json')) then begin
        try
          RunSetupHelper('rollback-upgrade', StartupJson);
          if HadPreviousInstallation then begin
            RunControllerTask('/Run /TN "PicSyncra Controller primary-installation"',
              'Nie można ponownie uruchomić kontrolera po cofnięciu');
            RunSetupHelper('resume-previous', StartupJson);
          end;
        except
          FailureMessage := FailureMessage + #13#10 + 'Odzyskiwanie: ' + GetExceptionMessage;
        end;
      end else if not FileExists(ExpandConstant('{app}\active.json')) then begin
        { A failed first activation has no previous installation to resume.
          Remove only its registration so another Setup can retry safely. }
        try
          RunSetupHelper('unregister', '{"installation_id":"primary-installation"}');
        except
          Log('Nie udało się usunąć rejestracji niedokończonej pierwszej instalacji: ' + GetExceptionMessage);
        end;
      end;
      RaiseException(FailureMessage);
    end;
  end;
end;
