// Classic script: definitions only; shared application state is initialized by app.js.

function renderSettingsApp() {
  const s = state.settings;
  const form = document.createElement("form");
  form.className = "settings-form";
  const configNote = document.createElement("p");
  configNote.className = "settings-note wide-field";
  configNote.textContent =
    `Panel webowy uzywa tej samej lokalizacji i config.json co lokalna aplikacja uruchomiona na backendzie. local_settings.json: ${
      s.local_settings_path || "nieznany"
    }`;
  const runtimeWarning = document.createElement("p");
  runtimeWarning.className = "settings-note wide-field";
  runtimeWarning.textContent = s.runtime_warning ? `Ostrzezenie runtime: ${s.runtime_warning}` : "";
  const versionNote = document.createElement("p");
  versionNote.className = "settings-note wide-field";
  versionNote.textContent = `Wersja programu: ${s.version || "dev"}`;
  const productFieldsNote = document.createElement("p");
  productFieldsNote.className = "settings-note wide-field";
  productFieldsNote.textContent =
    "Pusta nazwa zachowuje etykiete domyslna. Wylaczone pola sa pomijane przy zapisie i przetwarzaniu.";
  form.append(
    settingsFieldGroup("Runtime aplikacji",
      versionNote,
      configNote,
      runtimeWarning,
      selectField("data_mode", "Tryb danych", s.data_mode || "legacy", [
        ["legacy", "Pliki legacy"],
        ["sqlite", "SQLite"],
      ]),
      inputField("image_dir", "Lokalizacja zdjec", s.image_dir || s.base_dir, {
        placeholder: "np. C:\\PicSyncra albo \\\\SERWER\\Udzial\\Zdjecia",
        description:
          "Folder, w ktorym backend trzyma zdjecia i cache podgladow. " +
          "Dla uslugi Windows najlepiej uzywac pelnej sciezki lokalnej albo UNC; dyski mapowane typu Z:\\ moga nie byc widoczne.",
      }),
      selectField("database_location_mode", "Lokalizacja SQLite", s.database_location_mode || "image_dir", [
        ["image_dir", "Przy zdjeciach"],
        ["custom", "Wskazana sciezka"],
        ["exe_dir", "Przy backendzie"],
      ]),
      inputField("database_path", "Plik SQLite", s.database_path || "", {
        placeholder: "np. C:\\PicSyncra\\picsyncra.sqlite",
        description: "Uzywane tylko dla lokalizacji: wskazana sciezka.",
      }),
      actionRow(
        repairSqliteDatabaseButton(),
        manualSqliteBackupButton(),
        backupHistoryButton()
      )
    ),
    settingsFieldGroup("Kopie zapasowe SQLite",
      sqliteBackupScheduleGrid(s.sqlite_backup || {}),
      inputField("sqlite_backup_max_copies", "Maksymalna liczba kopii", s.sqlite_backup?.max_copies || 10, {
        type: "number",
        min: 1,
        max: 999,
      }),
      inputField(
        "sqlite_backup_archive_dirs",
        "Dodatkowe katalogi archiwalnych kopii",
        (s.sqlite_backup?.archive_dirs || []).join("\n"),
        {
          textarea: true,
          placeholder: "np. D:\\Archiwum\\PicSyncraBACKUP",
          description: "Po jednej zaufanej lokalizacji w wierszu. Nowe kopie nadal trafiaja do domyslnego BACKUP.",
        }
      )
    ),
    settingsFieldGroup("Indeks lokalny",
      checkField(
        "local_file_index",
        "Indeks plikow lokalnych",
        s.local_file_index,
        "Backend sprawdza lokalne pliki przy wczytywaniu statusow slotow."
      ),
      actionRow(diagnosticButton("local", "Test folderow backendu"), fileIndexRefreshButton())
    ),
    settingsFieldGroup("Widok panelu",
      panelTimeZoneField(s.web_display?.time_zone || "UTC"),
      checkField(
        "user_show_timing_details",
        "Pokazuj blok Pomiary",
        showTimingDetails(),
        "Ustawienie tylko dla aktualnego uzytkownika. Pokazuje lub ukrywa blok Pomiary z czasami kolejki i operacji."
      )
    ),
    settingsFieldGroup("Pola produktu",
      productFieldsNote,
      productFieldSettingsList(s.product_fields || {})
    )
  );
  settingsSaveButton(form, (data) => ({
    app: {
      image_dir: data.get("image_dir"),
      data_mode: data.get("data_mode"),
      database_location_mode: data.get("database_location_mode"),
      database_path: data.get("database_path"),
      local_file_index: data.has("local_file_index"),
      product_fields: collectProductFieldSettings(data),
    },
    sqlite_backup: collectSqliteBackupSchedule(form),
    web_display: {
      time_zone: data.get("web_display_time_zone"),
    },
  }));
  form.addEventListener("submit", () => {
    const data = new FormData(form);
    setTimingDetailsVisible(data.has("user_show_timing_details"));
  });
  settingsOutput.appendChild(form);
}

function renderSettingsProcessing() {
  const p = state.settings.processing || {};
  const formats = state.settings.processing_formats?.length
    ? state.settings.processing_formats
    : ["JPG", "PNG", "WEBP", "BMP", "GIF", "TIFF"];
  const form = document.createElement("form");
  form.className = "settings-form";
  const note = document.createElement("p");
  note.className = "settings-note wide-field";
  note.textContent =
    "Te ustawienia sa stosowane przy zapisie z panelu webowego. FIT w slocie nadal moze byc wlaczany osobno dla pojedynczego zdjecia.";
  form.append(
    note,
    settingsFieldGroup("FIT slotu",
      checkField(
        "auto_content_fit",
        "FIT domyslnie dla kazdego slotu",
        state.settings.auto_content_fit,
        "Nowe i wczytane sloty startuja z wlaczonym FIT, ale pojedynczy slot nadal mozna przelaczyc."
      )
    ),
    settingsFieldGroup("Przetwarzanie uploadu",
      selectField(
        "upload_processing_mode",
        "Kiedy przetwarzac obrazy",
        p.upload_processing_mode || "save",
        [
          ["save", "Host przy zapisie"],
          ["host", "Host przy uploadzie do cache"],
          ["client", "Klient przed uploadem"],
        ]
      )
    ),
    settingsFieldGroup("Zmniejszanie obrazu",
      checkField(
        "resize_enabled",
        "Wlacz zmniejszanie",
        p.resize_enabled,
        "Najdluzszy bok obrazu zostanie ograniczony do podanej liczby pikseli."
      ),
      inputField("max_dim", "Maksymalny bok (px)", p.max_dim || 2000, {
        type: "number",
        min: 64,
        max: 20000,
      })
    ),
    settingsFieldGroup("Kompresja JPG/WEBP",
      checkField(
        "compress_enabled",
        "Wlacz kompresje",
        p.compress_enabled,
        "Uzywa podanej jakosci przy zapisie stratnych formatow."
      ),
      inputField("compress_quality", "Jakosc (%)", p.compress_quality || 85, {
        type: "number",
        min: 1,
        max: 100,
      })
    ),
    settingsFieldGroup("Limit rozmiaru pliku",
      checkField(
        "max_size_enabled",
        "Wlacz limit rozmiaru",
        p.max_size_enabled,
        "Dla JPG/WEBP jakosc jest obnizana stopniowo, az plik miesci sie w limicie."
      ),
      inputField("max_file_kb", "Maksymalny rozmiar (KB)", p.max_file_kb || 500, {
        type: "number",
        min: 1,
        max: 102400,
      })
    ),
    settingsFieldGroup("Konwersja formatu",
      checkField(
        "convert_enabled",
        "Wlacz konwersje",
        p.convert_enabled,
        "Obrazy sa zapisywane w wybranym formacie zamiast w formacie zrodlowym."
      ),
      selectField(
        "target_format",
        "Format docelowy",
        p.target_format || "PNG",
        formats.map((format) => [format, format])
      )
    )
  );
  settingsSaveButton(form, (data) => ({
    app: {
      auto_content_fit: data.has("auto_content_fit"),
    },
    processing: {
      resize_enabled: data.has("resize_enabled"),
      max_dim: data.get("max_dim"),
      compress_enabled: data.has("compress_enabled"),
      compress_quality: data.get("compress_quality"),
      max_size_enabled: data.has("max_size_enabled"),
      max_file_kb: data.get("max_file_kb"),
      convert_enabled: data.has("convert_enabled"),
      target_format: data.get("target_format"),
      upload_processing_mode: data.get("upload_processing_mode"),
    },
  }));
  settingsOutput.appendChild(form);
}

function renderSettingsSecurity() {
  const security = state.settings.security || {};
  const form = document.createElement("form");
  form.className = "settings-form";
  const secretHint = document.createElement("p");
  secretHint.className = "settings-note";
  secretHint.textContent =
    "APP_SECRET sluzy do odczytu zaszyfrowanych hasel z config.json. " +
    "Przy podpinaniu istniejacego katalogu wpisz sekret uzyty przy jego konfiguracji; puste pole niczego nie zmienia.";
  form.append(
    settingsFieldGroup("Sekret aplikacji",
      secretHint,
      credentialField("app_secret", "APP_SECRET", state.settings.app_secret_set, {
        type: "password",
        secretPath: "app_secret",
      })
    ),
    settingsFieldGroup("Limity uploadu",
      inputField("max_upload_mb", "Maksymalny upload (MB)", security.max_upload_mb || 50, {
        type: "number",
        min: 1,
        max: 2048,
        description: "Backend przerwie zapis i usunie czesciowy plik po przekroczeniu limitu.",
      }),
      inputField(
        "max_upload_pixels",
        "Maksymalna liczba pikseli",
        security.max_upload_pixels || 25000000,
        {
          type: "number",
          min: 1,
          max: 400000000,
          step: 100000,
          description: "Dotyczy obrazow z uploadu, cache, rozszerzenia i importu z URL.",
        }
      )
    ),
    settingsFieldGroup("Typy plikow uploadu",
      inputField(
        "allowed_upload_extensions",
        "Akceptowane rozszerzenia",
        extensionListText(security.allowed_upload_extensions),
        {
          textarea: true,
          description:
            "Lista po przecinku. Gdy ma wpisy, wszystko spoza niej jest odrzucane. " +
            "Pusta lista wylacza allow-liste, ale nadal dzialaja blokady ponizej.",
        }
      ),
      inputField(
        "blocked_upload_extensions",
        "Zabronione rozszerzenia",
        extensionListText(security.blocked_upload_extensions),
        {
          textarea: true,
          description: "Lista po przecinku. Te typy sa odrzucane niezaleznie od listy akceptowanych.",
        }
      ),
      checkField(
        "block_executable_uploads",
        "Blokuj pliki wykonywalne",
        security.block_executable_uploads !== false,
        "Odrzuca m.in. exe, bat, cmd, msi, ps1, vbs, js, jar, dll, scr, sh."
      ),
      checkField(
        "antivirus_scan_uploads",
        "Skanuj upload Microsoft Defender",
        Boolean(security.antivirus_scan_uploads),
        "Dotyczy tylko plikow wysylanych przez panel lub rozszerzenie; pliki juz lokalne i pobrane z FTP nie sa ponownie skanowane."
      ),
      checkField(
        "show_active_web_users",
        "Pokaz aktywnych uzytkownikow",
        Boolean(security.show_active_web_users),
        "Uzytkownicy zobacza nazwy kont obecnie aktywnych w panelu WWW."
      )
    )
  );
  settingsSaveButton(form, (data) => ({
    security: {
      app_secret: data.get("app_secret"),
      max_upload_mb: data.get("max_upload_mb"),
      max_upload_pixels: data.get("max_upload_pixels"),
      allowed_upload_extensions: data.get("allowed_upload_extensions"),
      blocked_upload_extensions: data.get("blocked_upload_extensions"),
      block_executable_uploads: data.has("block_executable_uploads"),
      antivirus_scan_uploads: data.has("antivirus_scan_uploads"),
      show_active_web_users: data.has("show_active_web_users"),
    },
  }));
  settingsOutput.appendChild(form);
}

function renderSettingsFtp() {
  const ftp = state.settings.ftp;
  const form = document.createElement("form");
  form.className = "settings-form";
  form.append(
    settingsFieldGroup("Polaczenie FTP",
      checkField(
        "enabled",
        "Aktualizacja FTP",
        ftp.enabled,
        "Po zapisie backend bedzie wysylal przetworzone pliki na FTP."
      ),
      inputField("host", "Host", ftp.host),
      inputField("port", "Port", ftp.port, { type: "number" }),
      inputField("path", "Sciezka", ftp.path),
      actionRow(diagnosticButton("ftp", "Test FTP"))
    ),
    settingsFieldGroup("Dane logowania FTP",
      credentialField("user", "Uzytkownik", ftp.user_set, { secretPath: "ftp.user" }),
      credentialField("password", "Haslo", ftp.password_set, {
        type: "password",
        secretPath: "ftp.password",
      })
    )
  );
  settingsSaveButton(form, (data) => ({
    ftp: {
      enabled: data.has("enabled"),
      host: data.get("host"),
      port: data.get("port"),
      path: data.get("path"),
      user: data.get("user"),
      password: data.get("password"),
    },
  }));
  settingsOutput.appendChild(form);
}

function renderSettingsSql() {
  const db = state.settings.database;
  const form = document.createElement("form");
  const profiles = document.createElement("div");
  const addProfile = document.createElement("button");
  const placeholderItems = [
    ["{ean}", "EAN aktualnego produktu"],
    ["{filename}", "Nazwa wygenerowanego pliku"],
    ["{col}", "Kolumna SQL przypisana do slotu"],
    ["{column}", "Alias dla {col}"],
  ];
  profiles.className = "sql-profile-list wide-field";
  for (const profile of additionalSqlProfiles(db)) {
    profiles.appendChild(sqlProfileRow(profile));
  }
  addProfile.type = "button";
  addProfile.className = "secondary-button";
  addProfile.textContent = "Dodaj profil Pimcore SQL";
  addProfile.addEventListener("click", () => {
    profiles.appendChild(
      sqlProfileRow({
        id: `profile-${Date.now()}`,
        label: "Nowy profil",
        type: "mysql",
        enabled: true,
      })
    );
  });
  form.className = "settings-form";
  form.append(
    settingsFieldGroup("Tryb SQL",
      selectField("type", "Typ bazy", db.type, [["mysql", "MySQL"], ["mssql", "MS SQL"]]),
      checkField(
        "sql_update_enabled",
        "Aktualizacja SQL",
        db.sql_update_enabled,
        "Backend bedzie aktualizowal pola SQL przypisane w zakladce Sloty."
      ),
      inputField("query", "Zapytanie SQL", db.query, { textarea: true }),
      sqlPlaceholderHelp(placeholderItems),
      actionRow(diagnosticButton("sql", "Test SQL")),
      settingsNote("Domyslne polaczenie dla zdjec i slotow."),
      inputField("mssql_server", "MS SQL server", db.mssql.server),
      inputField("mssql_database", "MS SQL database", db.mssql.database),
      credentialField("mssql_user", "MS SQL user", db.mssql.user_set, {
        secretPath: "database.mssql.user",
      }),
      credentialField("mssql_password", "MS SQL haslo", db.mssql.password_set, {
        type: "password",
        secretPath: "database.mssql.password",
      }),
      inputField("mysql_server", "MySQL server", db.mysql.server),
      inputField("mysql_database", "MySQL database", db.mysql.database),
      credentialField("mysql_user", "MySQL user", db.mysql.user_set, {
        secretPath: "database.mysql.user",
      }),
      credentialField("mysql_password", "MySQL haslo", db.mysql.password_set, {
        type: "password",
        secretPath: "database.mysql.password",
      })
    ),
    settingsFieldGroup("Profile dodatkowe SQL",
      settingsNote("Niezalezne profile uzywane tylko po wybraniu w builderze wartosci pola Pimcore."),
      profiles,
      actionRow(addProfile)
    )
  );
  settingsSaveButton(form, (data) => ({
    database: {
      type: data.get("type"),
      sql_update_enabled: data.has("sql_update_enabled"),
      query: data.get("query"),
      mssql: {
        server: data.get("mssql_server"),
        database: data.get("mssql_database"),
        user: data.get("mssql_user"),
        password: data.get("mssql_password"),
      },
      mysql: {
        server: data.get("mysql_server"),
        database: data.get("mysql_database"),
        user: data.get("mysql_user"),
        password: data.get("mysql_password"),
      },
      profiles: collectSqlProfiles(form),
    },
  }));
  settingsOutput.appendChild(form);
}

function renderSettingsPimcore() {
  const pimcore = state.settings.pimcore || {};
  const form = document.createElement("form");
  form.className = "settings-form";
  if (pimcore.setup_complete !== true) {
    form.append(settingsNote("Integracja Pimcore wymaga pierwszej konfiguracji."));
    const start = document.createElement("button");
    start.type = "button";
    start.textContent = "Uruchom kreator";
    start.addEventListener("click", openPimcoreSetupWizard);
    form.appendChild(start);
    settingsOutput.appendChild(form);
    if (state.currentUser?.role === "admin" && !state.pimcoreSetupPrompted) {
      state.pimcoreSetupPrompted = true;
      queueMicrotask(openPimcoreSetupWizard);
    }
    return;
  }
  const fields = pimcoreCompactFields(pimcore);
  const classes = pimcoreCompactClassItems(pimcore);
  const folders = pimcoreCompactFolderItems(pimcore);
  const mappings = document.createElement("div");
  const addMapping = document.createElement("button");
  const refresh = document.createElement("button");
  const advanced = document.createElement("details");
  const advancedSummary = document.createElement("summary");
  const advancedBody = document.createElement("div");
  const configuredMappings = pimcore.field_mappings?.length
    ? pimcore.field_mappings
    : [{ source: "EAN", label: "EAN", pimcore_field: pimcore.existence_fields?.[0] || "EAN", required: true }];
  mappings.className = "pimcore-simple-mapping-list wide-field";
  for (const mapping of configuredMappings) {
    mappings.appendChild(pimcoreSimpleMappingRow(mapping, fields));
  }
  addMapping.type = "button";
  addMapping.className = "secondary-button";
  addMapping.textContent = "Dodaj pole";
  addMapping.addEventListener("click", () => {
    mappings.appendChild(pimcoreSimpleMappingRow({}, fields));
  });
  refresh.type = "button";
  refresh.className = "secondary-button";
  refresh.textContent = "Odswiez klasy i foldery";
  refresh.addEventListener("click", () => {
    refreshCompactPimcoreMetadata(form, refresh);
  });
  advanced.id = "pimcoreAdvancedSettings";
  advanced.className = "pimcore-advanced-settings";
  advanced.open = false;
  advancedSummary.textContent = "Zaawansowane";
  advancedBody.className = "settings-field-group";
  advancedBody.append(
    inputField("timeout_seconds", "Timeout [s]", pimcore.timeout_seconds || 30, {
      type: "number",
      min: "1",
      max: "120",
    }),
    checkField("verify_tls", "Weryfikuj certyfikat TLS", pimcore.verify_tls !== false),
    pimcoreCsvImportButton(mappings, fields),
    settingsNote("Klucz obiektu: {EAN}. Pole wyszukiwania EAN wynika z przypisania EAN."),
    settingsNote("Typ danych wykryty automatycznie na podstawie pola Pimcore.")
  );
  advanced.append(advancedSummary, advancedBody);
  form.append(
    settingsFieldGroup(
      "Polaczenie Pimcore",
      checkField("enabled", "Integracja wlaczona", pimcore.enabled),
      inputField("base_url", "Adres Pimcore", pimcore.base_url || "", {
        placeholder: "http://twoj-adres-pimcore.example",
      }),
      credentialField("api_key", "Klucz API", pimcore.api_key_set, {
        type: "password",
        secretPath: "pimcore.api_key",
      }),
      actionRow(refresh)
    ),
    settingsFieldGroup(
      "Miejsce zapisu",
      pimcoreSetupSelect(
        "class_id",
        "Klasa produktu",
        classes,
        pimcore.class_id,
        "id",
        (item) => `${item.name} (ID ${item.id})`
      ),
      pimcoreSetupSelect(
        "parent_id",
        "Folder docelowy",
        folders,
        pimcore.parent_id,
        "id",
        (item) => `${item.path || item.key} (ID ${item.id})`
      ),
      pimcoreManualCompactLocationFields(pimcore)
    ),
    settingsFieldGroup(
      "Pola produktu",
      settingsNote("Typ danych wykryty automatycznie na podstawie pola Pimcore."),
      mappings,
      actionRow(addMapping)
    ),
    settingsFieldGroup(
      "Testy integracji",
      actionRow(
        pimcoreReadOnlyTestButton(() => collectCompactPimcoreSettings(form)),
        pimcoreOpenWriteTestButton(),
        pimcoreHistoryButton()
      ),
      pimcoreChecklistElement()
    ),
    settingsFieldGroup(
      "Dane lokalne Pimcore",
      actionRow(pimcoreSettingsExportButton(), pimcoreExportLayoutOpenButton())
    ),
    advanced
  );
  settingsSaveButton(form, () => ({ pimcore: collectCompactPimcoreSettings(form) }));
  settingsOutput.appendChild(form);
}

function renderSettingsMail() {
  const email = state.settings.email_notifications || {};
  const form = document.createElement("form");
  const channelGrid = document.createElement("div");
  const entraCard = document.createElement("section");
  const smtpCard = document.createElement("section");
  const entraTitle = document.createElement("h3");
  const smtpTitle = document.createElement("h3");
  const smtpWarning = document.createElement("p");
  const entraExpiryStatus = document.createElement("div");
  const entraExpiryRefreshButton = document.createElement("button");
  const entraTenantId = addMailFieldHelp(
    inputField("email_entra_tenant_id", "Tenant ID", email.entra?.tenant_id || ""),
    "Tenant ID",
    "Pozycja: Identyfikator katalogu (dzierzawy) w widoku Przeglad rejestracji aplikacji Microsoft Entra. Nie jest to Identyfikator obiektu."
  );
  const entraClientId = addMailFieldHelp(
    inputField("email_entra_client_id", "Client ID", email.entra?.client_id || ""),
    "Client ID",
    "Pozycja: Identyfikator aplikacji (klienta) w widoku Przeglad tej rejestracji aplikacji Microsoft Entra. Nie jest to Identyfikator obiektu."
  );
  const entraClientSecret = addMailFieldHelp(
    credentialField(
      "email_entra_client_secret",
      "Client Secret",
      Boolean(email.entra?.client_secret_set),
      { type: "password" }
    ),
    "Client Secret",
    "Pozycja: Wartosc w Certyfikaty i wpisy tajne -> Wpisy tajne klienta dla utworzonego sekretu. Nie wpisuj Identyfikatora wpisu tajnego ani Identyfikatora obiektu. Wartosc jest widoczna w Entra tylko bezposrednio po utworzeniu sekretu."
  );
  const entraFromAddress = addMailFieldHelp(
    inputField("email_entra_from_address", "Adres Od", email.entra?.from_address || "", {
      type: "email",
      placeholder: "powiadomienia@example.com",
    }),
    "Adres Od",
    "Adres skrzynki Microsoft 365, z ktorej odbiorcy zobacza wiadomosci. Aplikacja Entra musi miec prawo wysylania z tej skrzynki."
  );
  const smtpSecurity = selectField(
    "email_smtp_security",
    "Szyfrowanie polaczenia",
    email.smtp?.security || "starttls",
    [
      ["starttls", "STARTTLS"],
      ["tls", "TLS od poczatku polaczenia"],
      ["none", "Brak szyfrowania"],
    ]
  );
  addMailFieldHelp(
    smtpSecurity,
    "Szyfrowanie polaczenia",
    "Sposob zabezpieczenia polaczenia z serwerem SMTP. Wybierz STARTTLS lub TLS, gdy dostawca je udostepnia."
  );
  const smtpSecuritySelect = smtpSecurity.querySelector("select");
  const updateSmtpWarning = () => {
    const security = smtpSecuritySelect.value;
    smtpWarning.hidden = security !== "none";
  };
  form.className = "settings-form mail-settings-form";
  channelGrid.className = "mail-channel-grid wide-field";
  entraCard.className = "mail-channel-card";
  smtpCard.className = "mail-channel-card";
  entraTitle.textContent = "Microsoft Entra / Graph";
  smtpTitle.textContent = "SMTP (dowolny dostawca)";
  smtpWarning.className = "mail-security-warning";
  smtpWarning.setAttribute("role", "alert");
  smtpWarning.textContent =
    "Uwaga: tryb bez TLS. Nie szyfruje polaczenia ani danych logowania. Uzywaj go tylko w zaufanej sieci.";
  entraExpiryStatus.className = "entra-expiry-status";
  entraExpiryStatus.setAttribute("role", "status");
  entraExpiryStatus.setAttribute("aria-live", "polite");
  entraExpiryStatus.textContent = "Pobieranie zapisanego statusu Client Secret...";
  entraExpiryRefreshButton.type = "button";
  entraExpiryRefreshButton.className = "secondary-button entra-expiry-refresh";
  entraExpiryRefreshButton.textContent = "Sprawdz teraz";
  entraExpiryRefreshButton.addEventListener("click", async () => {
    entraExpiryRefreshButton.disabled = true;
    try {
      const status = await requestJson("/api/settings/email/entra-expiry/refresh", {
        method: "POST",
      });
      renderEntraExpiryStatus(entraExpiryStatus, status);
    } catch (_error) {
      renderEntraExpiryRefreshFailure(entraExpiryStatus);
    } finally {
      entraExpiryRefreshButton.disabled = false;
    }
  });
  smtpSecuritySelect.addEventListener("change", updateSmtpWarning);
  updateSmtpWarning();
  entraCard.append(
    entraTitle,
    entraExpiryStatus,
    entraExpiryRefreshButton,
    entraTenantId,
    entraClientId,
    entraClientSecret,
    entraFromAddress
  );
  loadCachedEntraExpiryStatus(entraExpiryStatus);
  smtpCard.append(
    smtpTitle,
    addMailFieldHelp(
      inputField("email_smtp_host", "Host SMTP", email.smtp?.host || ""),
      "Host SMTP",
      "Adres serwera SMTP udostepniony przez dostawce poczty, np. smtp.gmail.com."
    ),
    addMailFieldHelp(
      inputField("email_smtp_port", "Port", email.smtp?.port || 587, {
        type: "number",
        min: 1,
        max: 65535,
      }),
      "Port",
      "Port serwera SMTP wskazany przez dostawce poczty. Dla STARTTLS najczesciej jest to 587."
    ),
    smtpSecurity,
    smtpWarning,
    addMailFieldHelp(
      inputField("email_smtp_username", "Login", email.smtp?.username || ""),
      "Login",
      "Login wymagany przez serwer SMTP; u wielu dostawcow jest to pelny adres e-mail skrzynki."
    ),
    addMailFieldHelp(
      credentialField(
        "email_smtp_password",
        "Haslo",
        Boolean(email.smtp?.password_set),
        { type: "password" }
      ),
      "Haslo",
      "Haslo SMTP lub haslo aplikacji wygenerowane przez dostawce poczty. Nie jest to haslo do panelu PicSyncra."
    ),
    addMailFieldHelp(
      inputField("email_smtp_from_address", "Adres Od", email.smtp?.from_address || "", {
        type: "email",
        placeholder: "powiadomienia@example.com",
      }),
      "Adres Od",
      "Adres skrzynki SMTP, z ktorej odbiorcy zobacza wiadomosci. Zwykle musi odpowiadac skonfigurowanemu loginowi."
    ),
    addMailFieldHelp(
      inputField("email_smtp_from_name", "Nazwa Od", email.smtp?.from_name || "PicSyncra"),
      "Nazwa Od",
      "Czytelna nazwa nadawcy wyswietlana odbiorcom obok adresu skrzynki."
    )
  );
  channelGrid.append(entraCard, smtpCard);

  const rules = email.rules || {};
  const dailySummaryTime = addMailFieldHelp(
    inputField(
      "daily_summary_time",
      "Godzina dziennego podsumowania",
      email.daily_summary_time || "16:00",
      { type: "time" }
    ),
    "Godzina dziennego podsumowania",
    "Godzina wyslania jednego podsumowania zmian dla odbiorcow Informacji. Czas Europe/Warsaw. Raport obejmuje zmiany od poprzedniego poprawnie wyslanego raportu."
  );
  const rulesGrid = document.createElement("div");
  rulesGrid.className = "mail-rule-grid wide-field";
  rulesGrid.append(
    ...MAIL_SEVERITY_RULES.map((definition) =>
      mailRuleCard(definition, rules[definition.severity])
    )
  );

  const testRecipient = inputField(
    "email_test_recipient",
    "Adres odbiorcy testu",
    "",
    { type: "email", placeholder: "admin@example.com" }
  );
  const testChannel = selectField("email_test_channel", "Kanal testu", "primary", [
    ["primary", "Kanal podstawowy"],
    ["entra", "Microsoft Entra"],
    ["smtp", "SMTP"],
  ]);
  const testFallback = checkField(
    "email_test_use_fallback",
    "Uzyj fallbacku, gdy kanal testowy zawiedzie",
    Boolean(email.fallback_enabled)
  );
  const testButton = document.createElement("button");
  const testSuiteButton = document.createElement("button");
  const testStatus = document.createElement("div");
  const testSuiteStatus = document.createElement("div");
  testButton.type = "button";
  testButton.textContent = "Wyslij wiadomosc testowa";
  testSuiteButton.type = "button";
  testSuiteButton.textContent = "Testuj wszystkie typy powiadomien";
  testStatus.className = "mail-test-status";
  testSuiteStatus.className = "mail-test-status";
  testStatus.setAttribute("role", "status");
  testStatus.setAttribute("aria-live", "polite");
  testSuiteStatus.setAttribute("role", "status");
  testSuiteStatus.setAttribute("aria-live", "polite");
  testButton.addEventListener("click", async () => {
    const recipient = testRecipient.querySelector("input").value.trim();
    if (!recipient) {
      testStatus.className = "mail-test-status error-text";
      testStatus.textContent = "Podaj adres odbiorcy testu.";
      return;
    }
    testButton.disabled = true;
    testStatus.className = "mail-test-status";
    testStatus.textContent = "Wysylanie testu...";
    try {
      const result = await requestJson("/api/settings/email/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          recipient,
          channel: testChannel.querySelector("select").value,
          use_fallback: testFallback.querySelector("input").checked,
        }),
        timeoutMs: 60000,
      });
      renderMailTestResult(testStatus, result);
    } catch (error) {
      const result = error.payload || error.detail;
      if (result && typeof result === "object" && Array.isArray(result.attempts)) {
        renderMailTestResult(testStatus, result);
      } else {
        testStatus.className = "mail-test-status error-text";
        testStatus.textContent = "Test wysylki nie powiodl sie. Sprawdz konfiguracje kanalu.";
      }
    } finally {
      testButton.disabled = false;
    }
  });
  testSuiteButton.addEventListener("click", async () => {
    testSuiteButton.disabled = true;
    testSuiteStatus.className = "mail-test-status";
    testSuiteStatus.textContent = "Wysylanie pieciu testowych powiadomien...";
    try {
      const result = await requestJson("/api/settings/email/test-suite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel: testChannel.querySelector("select").value,
          use_fallback: testFallback.querySelector("input").checked,
        }),
        timeoutMs: 180000,
      });
      renderMailTestSuiteResult(testSuiteStatus, result);
    } catch (error) {
      const result = error.payload || error.detail;
      if (result && typeof result === "object" && Array.isArray(result.scenarios)) {
        renderMailTestSuiteResult(testSuiteStatus, result);
      } else {
        testSuiteStatus.className = "mail-test-status error-text";
        testSuiteStatus.textContent = "Test zestawu nie powiodl sie. Sprawdz konfiguracje kanalow.";
      }
    } finally {
      testSuiteButton.disabled = false;
    }
  });

  form.append(
    settingsFieldGroup(
      "Sposob wysylki",
      selectField(
        "email_primary_channel",
        "Kanal podstawowy",
        email.primary_channel || "entra",
        [
          ["entra", "Microsoft Entra"],
          ["smtp", "SMTP"],
        ]
      ),
      checkField(
        "email_fallback_enabled",
        "Wlacz kanal zapasowy",
        Boolean(email.fallback_enabled),
        "Gdy kanal podstawowy zawiedzie, aplikacja wykona jedna probe drugim kanalem."
      ),
      channelGrid
    ),
    settingsFieldGroup(
      "Reguly powiadomien",
      rulesGrid,
      settingsNote("Znaki zapytania wyjasniaja, kto otrzymuje dany typ wiadomosci i kiedy jest wysylany.")
    ),
    settingsFieldGroup(
      "Dzienne podsumowanie informacji",
      dailySummaryTime,
      settingsNote("Jedna wiadomosc tylko wtedy, gdy wystapily zmiany produktow. Strefa czasowa: Europe/Warsaw.")
    ),
    settingsFieldGroup(
      "Wiadomosc testowa",
      testRecipient,
      testChannel,
      testFallback,
      actionRow(testButton, testSuiteButton),
      testStatus,
      testSuiteStatus
    )
  );
  settingsSaveButton(form, (data) => ({
    email_notifications: {
      primary_channel: data.get("email_primary_channel"),
      fallback_enabled: data.has("email_fallback_enabled"),
      daily_summary_time: data.get("daily_summary_time"),
      entra: {
        tenant_id: data.get("email_entra_tenant_id"),
        client_id: data.get("email_entra_client_id"),
        client_secret: data.get("email_entra_client_secret"),
        from_address: data.get("email_entra_from_address"),
      },
      smtp: {
        host: data.get("email_smtp_host"),
        port: data.get("email_smtp_port"),
        security: data.get("email_smtp_security"),
        username: data.get("email_smtp_username"),
        password: data.get("email_smtp_password"),
        from_address: data.get("email_smtp_from_address"),
        from_name: data.get("email_smtp_from_name"),
      },
      rules: Object.fromEntries(
        MAIL_SEVERITY_RULES.map((definition) => [
          definition.severity,
          {
            enabled: data.has(definition.enabledName),
            recipients: splitEmailRecipients(data.get(definition.recipientsName)),
            include_actor: data.has(definition.includeActorName),
          },
        ])
      ),
    },
  }));
  settingsOutput.appendChild(form);
}

function renderSettingsSlots() {
  ensureSqlColumnsDatalist();
  const form = document.createElement("form");
  form.className = "settings-form";
  const note = document.createElement("p");
  note.className = "settings-note wide-field";
  note.textContent =
    "Nazwa w web jest tylko etykieta slotu. ID trafia do EAN_ID, nazwa w pliku jest zapisywana literalnie po usunieciu znakow niedozwolonych, a pole SQL sluzy do aktualizacji bazy.";
  const list = document.createElement("div");
  const addButton = document.createElement("button");
  const similarSettings = state.settings.similar_file_detection || {};
  const similarEnabled = document.createElement("input");
  const similarEnabledRow = document.createElement("label");
  list.className = "slot-settings-list";
  similarEnabled.type = "checkbox";
  similarEnabled.name = "similar_files_enabled";
  similarEnabled.checked = Boolean(similarSettings.enabled);
  similarEnabledRow.className = "check-row";
  similarEnabledRow.append(similarEnabled, document.createTextNode("Wykrywaj pliki z podobnych produktow"));
  const nextPrefix = () => {
    const used = [...list.querySelectorAll('[name="prefix"]')]
      .map((input) => parseInt(input.value, 10))
      .filter((value) => Number.isFinite(value));
    const next = Math.max(0, ...used) + 1;
    return String(next).padStart(2, "0");
  };
  const addSlotRow = (slot = {}) => {
    const row = document.createElement("div");
    const remove = document.createElement("button");
    const similarOption = document.createElement("label");
    const similarInput = document.createElement("input");
    row.className = "slot-settings-row";
    row.dataset.filenameLabelExplicit = slot.filename_label_explicit ? "1" : "0";
    row.dataset.originalLabel = slot.label || "";
    row.dataset.originalFilenameLabel = slot.filename_label || slot.label || "";
    const column = inputField("sql_column", "Pole SQL", slot.sql_column || "");
    column.querySelector("input").setAttribute("list", "sqlColumnsList");
    remove.type = "button";
    remove.className = "secondary-button";
    remove.textContent = "Usun";
    remove.addEventListener("click", () => row.remove());
    similarOption.className = "slot-similar-option";
    similarInput.type = "checkbox";
    similarInput.name = "similar_file_slot_prefixes";
    similarInput.value = slot.prefix || "";
    similarInput.checked = (similarSettings.slot_prefixes || []).includes(slot.prefix);
    similarInput.disabled = !similarEnabled.checked;
    similarOption.append(similarInput, document.createTextNode("Podobne"));
    row.append(
      inputField("label", "Nazwa w web", slot.label),
      inputField("prefix", "ID", slot.prefix),
      inputField("filename_label", "Nazwa w pliku", slot.filename_label || slot.label),
      column,
      similarOption,
      remove
    );
    list.appendChild(row);
  };
  for (const slot of state.settings.slots || []) {
    addSlotRow(slot);
  }
  similarEnabled.addEventListener("change", () => {
    list.querySelectorAll('[name="similar_file_slot_prefixes"]').forEach((input) => {
      input.disabled = !similarEnabled.checked;
    });
  });
  addButton.type = "button";
  addButton.className = "secondary-button";
  addButton.textContent = "Dodaj slot";
  addButton.addEventListener("click", () => {
    const prefix = nextPrefix();
    addSlotRow({
      prefix,
      label: `Slot ${prefix}`,
      filename_label: `Slot ${prefix}`,
      filename_label_explicit: true,
      sql_column: "",
    });
  });
  form.append(
    settingsFieldGroup("Lista slotow", note, similarEnabledRow, list, actionRow(addButton, detectSqlColumnsButton()))
  );
  settingsSaveButton(form, (data) => {
    const slotRows = [...form.querySelectorAll(".slot-settings-row")];
    const slots = slotRows.map((row) => {
      const label = row.querySelector('[name="label"]').value;
      const filenameLabel = row.querySelector('[name="filename_label"]').value;
      const wasExplicit = row.dataset.filenameLabelExplicit === "1";
      const originalLabel = row.dataset.originalLabel || "";
      const originalFilenameLabel = row.dataset.originalFilenameLabel || "";
      const unchangedLegacyFilename =
        !wasExplicit && label === originalLabel && filenameLabel === originalFilenameLabel;
      return {
        prefix: row.querySelector('[name="prefix"]').value,
        label,
        filename_label: unchangedLegacyFilename ? "" : filenameLabel,
        sql_column: row.querySelector('[name="sql_column"]').value,
      };
    });
    return {
      slots,
      "similar_file_detection": {
        enabled: data.has("similar_files_enabled"),
        slot_prefixes: selectedSimilarSlotPrefixes(slotRows),
      },
    };
  });
  settingsOutput.appendChild(form);
}

function renderSettingsUsers() {
  const wrapper = document.createElement("div");
  wrapper.className = "settings-form";
  const addForm = document.createElement("form");
  addForm.className = "user-add-form wide-field";
  const input = document.createElement("input");
  const emailInput = document.createElement("input");
  const password = document.createElement("input");
  const role = document.createElement("select");
  const button = document.createElement("button");
  input.name = "username";
  input.placeholder = "Nowy uzytkownik";
  emailInput.name = "email";
  emailInput.type = "email";
  emailInput.autocomplete = "email";
  emailInput.placeholder = "E-mail opcjonalnie";
  password.name = "password";
  password.type = "password";
  password.placeholder = "Haslo";
  for (const value of ["user", "admin"]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    role.appendChild(option);
  }
  button.textContent = "Dodaj";
  addForm.append(input, emailInput, password, role, button);
  addForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = await requestJson("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: input.value,
        email: emailInput.value,
        password: password.value,
        role: role.value,
      }),
    });
    state.settings.users = payload.users;
    state.currentUser = payload.current_user || state.currentUser;
    updateAdminUi();
    input.value = "";
    emailInput.value = "";
    password.value = "";
    renderSettings();
  });
  const list = document.createElement("div");
  list.className = "user-list";
  for (const user of state.settings.users || []) {
    const row = document.createElement("div");
    row.className = "user-row";
    row.classList.toggle("user-row-locked", Boolean(user.locked));
    const name = document.createElement("div");
    const nameTitle = document.createElement("strong");
    const nameMeta = document.createElement("small");
    const role = document.createElement("select");
    const enabled = document.createElement("input");
    const enabledWrap = document.createElement("div");
    const enabledText = document.createElement("div");
    const enabledTitle = document.createElement("strong");
    const enabledDescription = document.createElement("small");
    const userEmailInput = document.createElement("input");
    const passwordInput = document.createElement("input");
    const actions = document.createElement("div");
    const save = document.createElement("button");
    const unlock = document.createElement("button");
    const revokeSessions = document.createElement("button");
    const revokeExtension = document.createElement("button");
    const isCurrentUser =
      state.currentUser &&
      String(state.currentUser.username || "").toLowerCase() === String(user.username || "").toLowerCase();
    const loginMeta = [];
    name.className = "user-summary";
    nameTitle.textContent = user.username;
    if (user.locked) {
      loginMeta.push(
        user.lock_manual
          ? "Zablokowane do recznego odblokowania"
          : `Zablokowane do ${formatPanelTimestamp(user.lock_expires_ts, { epochUnit: "seconds" })}`
      );
    }
    if (user.failed_login_count) {
      loginMeta.push(`Bledne proby: ${user.failed_login_count}`);
    }
    if (user.last_failed_login_ts) {
      const ip = user.last_failed_login_ip ? `, ${user.last_failed_login_ip}` : "";
      loginMeta.push(
        `Ostatnia bledna: ${formatPanelTimestamp(user.last_failed_login_ts, {
          epochUnit: "seconds",
        })}${ip}`
      );
    }
    loginMeta.push(`Sesje v${Number(user.session_version || 0)}`);
    loginMeta.push(
      `Token rozszerzenia v${Number(user.extension_token_version || 0)}${
        user.extension_token_last_used_ts
          ? `, ostatnio ${formatPanelTimestamp(user.extension_token_last_used_ts, {
              epochUnit: "seconds",
            })}`
          : ""
      }`
    );
    nameMeta.textContent = loginMeta.join(" | ") || "Brak blednych prob logowania.";
    nameMeta.className = user.locked ? "user-lock-warning" : "";
    name.append(nameTitle, nameMeta);
    for (const value of ["user", "admin"]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      option.selected = user.role === value;
      role.appendChild(option);
    }
    enabled.type = "checkbox";
    enabled.checked = Boolean(user.enabled);
    enabled.disabled = Boolean(isCurrentUser);
    enabled.setAttribute("aria-label", `Konto aktywne: ${user.username}`);
    enabledTitle.textContent = "Konto aktywne";
    enabledDescription.textContent = isCurrentUser
      ? "Nie mozna wylaczyc konta aktualnej sesji."
      : "Wylaczenie blokuje logowanie tego uzytkownika.";
    enabledText.append(enabledTitle, enabledDescription);
    enabledWrap.className = "check-row compact-check";
    enabledWrap.append(enabled, enabledText);
    userEmailInput.name = "email";
    userEmailInput.type = "email";
    userEmailInput.autocomplete = "email";
    userEmailInput.placeholder = "E-mail opcjonalnie";
    userEmailInput.value = String(user.email || "");
    passwordInput.type = "password";
    passwordInput.placeholder = user.has_password ? "Nowe haslo opcjonalnie" : "Ustaw haslo";
    save.type = "button";
    save.textContent = "Zapisz";
    unlock.type = "button";
    unlock.textContent = "Odblokuj";
    unlock.hidden = !user.locked && !user.failed_login_count;
    revokeSessions.type = "button";
    revokeSessions.textContent = "Wyloguj sesje";
    revokeExtension.type = "button";
    revokeExtension.textContent = "Uniewaznij token";
    actions.className = "user-actions";
    save.addEventListener("click", async () => {
      const payload = {
        enabled: enabled.checked,
        role: role.value,
        email: userEmailInput.value,
      };
      if (passwordInput.value) {
        payload.password = passwordInput.value;
      }
      const response = await requestJson(`/api/users/${encodeURIComponent(user.username)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.settings.users = response.users;
      state.currentUser = response.current_user || state.currentUser;
      updateAdminUi();
      renderSettings();
    });
    unlock.addEventListener("click", async () => {
      const response = await requestJson(`/api/users/${encodeURIComponent(user.username)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unlock: true }),
      });
      state.settings.users = response.users;
      state.currentUser = response.current_user || state.currentUser;
      if (response.session_invalidated) {
        window.location.href = "/login";
        return;
      }
      updateAdminUi();
      renderSettings();
    });
    revokeSessions.addEventListener("click", async () => {
      const response = await requestJson(`/api/users/${encodeURIComponent(user.username)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revoke_sessions: true }),
      });
      if (response.session_invalidated) {
        window.location.href = "/login";
        return;
      }
      state.settings.users = response.users;
      state.currentUser = response.current_user || state.currentUser;
      updateAdminUi();
      renderSettings();
    });
    revokeExtension.addEventListener("click", async () => {
      const response = await requestJson(`/api/users/${encodeURIComponent(user.username)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revoke_extension_token: true }),
      });
      state.settings.users = response.users;
      state.currentUser = response.current_user || state.currentUser;
      updateAdminUi();
      renderSettings();
    });
    actions.append(save, unlock, revokeSessions, revokeExtension);
    row.append(name, role, userEmailInput, passwordInput, enabledWrap, actions);
    list.appendChild(row);
  }
  wrapper.append(
    settingsFieldGroup("Nowy uzytkownik", addForm),
    settingsFieldGroup("Lista uzytkownikow", list)
  );
  settingsOutput.appendChild(wrapper);
}

function renderSettingsResourceMonitor() {
  const monitor = state.settings.resource_monitor || {};
  const form = document.createElement("form");
  form.className = "settings-form";
  const note = document.createElement("p");
  note.className = "settings-note wide-field";
  note.textContent =
    "Progi dotycza procesu backendu. Alarm jest zatwierdzany po kolejnych probkach, aby ograniczyc falszywe ostrzezenia.";
  const testNote = document.createElement("p");
  testNote.className = "settings-note wide-field";
  testNote.textContent =
    "Bezpieczna symulacja zapisuje trwale zdarzenie testowe; brak zapisu jest wynikiem niepowodzenia. Testy rzeczywiste tworza kontrolowane obciazenie CPU, RAM albo dysku i moga trwac okolo 20 sekund.";
  const testResult = document.createElement("p");
  testResult.id = "resourceMonitorTestResult";
  testResult.className = "resource-monitor-test-result wide-field";
  testResult.setAttribute("role", "status");

  const safeButton = document.createElement("button");
  safeButton.type = "button";
  safeButton.className = "secondary-button";
  safeButton.dataset.resourceMonitorTest = "safe";
  safeButton.textContent = "Bezpieczna symulacja";
  safeButton.addEventListener("click", () => runResourceMonitorTest("safe"));

  const cpuButton = document.createElement("button");
  cpuButton.type = "button";
  cpuButton.className = "secondary-button";
  cpuButton.dataset.resourceMonitorTest = "cpu";
  cpuButton.dataset.resourceMonitorRealTest = "cpu";
  cpuButton.textContent = "Rzeczywisty test CPU";
  cpuButton.addEventListener("click", () => runResourceMonitorTest("cpu"));

  const memoryButton = document.createElement("button");
  memoryButton.type = "button";
  memoryButton.className = "secondary-button";
  memoryButton.dataset.resourceMonitorTest = "memory";
  memoryButton.dataset.resourceMonitorRealTest = "memory";
  memoryButton.textContent = "Rzeczywisty test RAM";
  memoryButton.addEventListener("click", () => runResourceMonitorTest("memory"));

  const diskButton = document.createElement("button");
  diskButton.type = "button";
  diskButton.className = "secondary-button";
  diskButton.dataset.resourceMonitorTest = "disk";
  diskButton.dataset.resourceMonitorRealTest = "disk";
  diskButton.textContent = "Rzeczywisty test dysku";
  diskButton.addEventListener("click", () => runResourceMonitorTest("disk"));

  form.append(
    settingsFieldGroup(
      "Wskaznik zasobow",
      checkField(
        "show_status",
        "Pokazuj status zasobow w naglowku",
        monitor.show_status !== false,
        "Ukrywa tylko wskaznik zasobow; glowny status backendu pozostaje widoczny."
      )
    ),
    settingsFieldGroup(
      "Progi alarmow backendu",
      note,
      inputField(
        "cpu_percent_threshold",
        "CPU (%)",
        monitor.cpu_percent_threshold ?? 25,
        { type: "number", min: 10, max: 90, step: 1 }
      ),
      inputField(
        "memory_percent_threshold",
        "RAM (%)",
        monitor.memory_percent_threshold ?? 20,
        { type: "number", min: 1, max: 90, step: 1 }
      ),
      inputField(
        "io_mib_per_second_threshold",
        "Dysk I/O (MB/s)",
        monitor.io_mib_per_second_threshold ?? 8,
        { type: "number", min: 1, max: 256, step: 1 }
      )
    ),
    settingsFieldGroup(
      "Test monitora",
      testNote,
      actionRow(safeButton, cpuButton, memoryButton, diskButton),
      testResult
    )
  );
  settingsSaveButton(form, (data) => ({
    resource_monitor: {
      show_status: data.has("show_status"),
      cpu_percent_threshold: data.get("cpu_percent_threshold"),
      memory_percent_threshold: data.get("memory_percent_threshold"),
      io_mib_per_second_threshold: data.get("io_mib_per_second_threshold"),
    },
  }));
  settingsOutput.appendChild(form);
  updateResourceMonitorTestUi();
}

function renderSettingsOcr() {
  const form = document.createElement("form");
  form.className = "settings-form";
  const ocrSettings = state.settings?.ocr || {};
  const status = document.createElement("p");
  status.className = "settings-note wide-field";
  status.textContent = "Pobieranie informacji o lokalnym OCR...";
  const engineInfo = document.createElement("div");
  engineInfo.className = "ocr-engine-info wide-field";
  const file = inputField("ocr_test_file", "Obraz testowy", "", {
    type: "file",
    description: "Obraz trafia do tymczasowego cache aplikacji; nie jest zapisywany jako konfiguracja.",
  });
  const fileInput = file.querySelector("input");
  fileInput.accept = "image/*";
  const idleSeconds = inputField("ocr_idle_seconds", "Czas bez aktywnosci (s)", ocrSettings.idle_seconds ?? 5, {
    type: "number",
    min: 0,
    max: 3600,
    step: 1,
    description: "Tyle czasu OCR czeka przed wznowieniem kolejki w tle.",
  });
  const maxCpu = inputField("ocr_max_cpu_percent", "Maksymalne uzycie CPU (%)", ocrSettings.max_cpu_percent ?? 35, {
    type: "number", min: 0, max: 100, step: 1,
    description: "Twardy limit CPU dla procesu OCR. Nie obciaza procesu panelu WWW.",
  });
  const pauseCpu = inputField("ocr_pause_cpu_percent", "Nie uruchamiaj powyzej CPU (%)", ocrSettings.pause_cpu_percent ?? 85, {
    type: "number", min: 0, max: 100, step: 1,
    description: "Przed startem kolejnego zadania OCR sprawdzane jest aktualne uzycie calego systemu.",
  });
  const memoryMode = selectField("ocr_max_memory_mode", "Miekki prog RAM systemu", ocrSettings.max_memory_mode || "percent", [
    ["percent", "Procent calego RAM"],
    ["gigabytes", "GB aktualnego uzycia"],
  ]);
  const maxMemoryPercent = inputField("ocr_max_memory_percent", "Aktualne uzycie RAM (%)", ocrSettings.max_memory_percent ?? 30, {
    type: "range", min: 1, max: 100, step: 1,
    description: "OCR sprawdza uzycie przed kazdym etapem i czeka przed rozpoczeciem kolejnego; nie przerywa etapu, ktory juz trwa.",
  });
  const maxMemoryGb = inputField("ocr_max_memory_gb", "Aktualne uzycie RAM (GB)", ocrSettings.max_memory_gb ?? 4, {
    type: "number", min: 0.1, max: 1024, step: 0.1,
    description: "Alternatywa dla procentu; dotyczy uzycia, nie pojemnosci dysku.",
  });
  const maxDiskBusy = inputField("ocr_max_disk_busy_percent", "Aktualna aktywnosc dysku (%)", ocrSettings.max_disk_busy_percent ?? 80, {
    type: "range", min: 0, max: 100, step: 1,
    description: "Przy wysokiej aktywnosci dysku OCR zwalnia miedzy etapami zamiast przerywac odczyt.",
  });
  const accurateThreshold = document.createElement("label");
  accurateThreshold.className = "ocr-accurate-threshold";
  accurateThreshold.appendChild(document.createTextNode("Skanuj dokladnym modelem przy pewnosci szybkiego do (%)"));
  const accurateThresholdControls = document.createElement("span");
  accurateThresholdControls.className = "ocr-accurate-threshold-controls";
  const accurateThresholdRange = document.createElement("input");
  accurateThresholdRange.type = "range";
  accurateThresholdRange.name = "ocr_accurate_confidence_threshold_range";
  accurateThresholdRange.min = "0";
  accurateThresholdRange.max = "100";
  accurateThresholdRange.step = "1";
  const accurateThresholdNumber = document.createElement("input");
  accurateThresholdNumber.type = "number";
  accurateThresholdNumber.name = "ocr_accurate_confidence_threshold";
  accurateThresholdNumber.min = "0";
  accurateThresholdNumber.max = "100";
  accurateThresholdNumber.step = "1";
  const initialAccurateThreshold = Math.round(Math.max(0, Math.min(100, Number(ocrSettings.accurate_confidence_threshold ?? 99) || 0)));
  accurateThresholdRange.value = String(initialAccurateThreshold);
  accurateThresholdNumber.value = String(initialAccurateThreshold);
  const synchronizeAccurateThreshold = (source, target) => {
    const value = Math.round(Math.max(0, Math.min(100, Number(source.value) || 0)));
    source.value = String(value);
    target.value = String(value);
  };
  accurateThresholdRange.addEventListener("input", () => synchronizeAccurateThreshold(accurateThresholdRange, accurateThresholdNumber));
  accurateThresholdNumber.addEventListener("input", () => synchronizeAccurateThreshold(accurateThresholdNumber, accurateThresholdRange));
  accurateThresholdControls.append(accurateThresholdRange, accurateThresholdNumber);
  accurateThreshold.append(
    accurateThresholdControls,
    document.createTextNode(" Przy 100% dokladny model skanuje kazdy wykryty wycinek; przy 50% tylko odczyty do 50% pewnosci.")
  );
  const updateMemoryMode = () => {
    const useGb = memoryMode.querySelector("select")?.value === "gigabytes";
    maxMemoryPercent.hidden = useGb;
    maxMemoryGb.hidden = !useGb;
  };
  memoryMode.querySelector("select")?.addEventListener("change", updateMemoryMode);
  updateMemoryMode();
  const background = checkField(
    "ocr_background_enabled",
    "Wlacz kolejke dopracowywania OCR w tle",
    Boolean(ocrSettings.background_enabled),
    "Kolejka dziala dopiero po okresie bez aktywnosci uzytkownika."
  );
  const queueVisibility = checkField(
    "ocr_background_queue_visible_to_users",
    "Pokaz kolejke dopracowywania OCR uzytkownikom",
    Boolean(ocrSettings.background_queue_visible_to_users),
    "Administrator widzi kolejke zawsze; zwykli uzytkownicy tylko po wlaczeniu tej opcji."
  );
  const profiles = document.createElement("div");
  profiles.className = "ocr-profile-options wide-field";
  const profileHeading = document.createElement("div");
  const profileTitle = document.createElement("strong");
  const profileHelp = document.createElement("span");
  profileTitle.textContent = "Mechanizm OCR";
  profileHelp.textContent = "Wybierz szybszy, dokladniejszy albo oba lokalnie dostepne profile. Aplikacja niczego nie pobiera podczas pracy.";
  profileHeading.className = "ocr-profile-options-heading";
  profileHeading.append(profileTitle, profileHelp);
  profiles.appendChild(profileHeading);
  const selectedProfiles = new Set((ocrSettings.model_profiles || ["fast"]).map(String));
  const profileDefinitions = [
    { id: "fast", title: "Szybki", description: "PP-OCRv5 Mobile — najszybszy odczyt." },
    { id: "accurate", title: "Dokladny", description: "PP-OCRv5 Server — wolniejszy, z wieksza szansa na trudny odczyt." },
  ];
  const profileCards = new Map();
  for (const profile of profileDefinitions) {
    const card = document.createElement("label");
    const input = document.createElement("input");
    const details = document.createElement("span");
    const title = document.createElement("strong");
    const description = document.createElement("small");
    const availability = document.createElement("em");
    card.className = "ocr-profile-card";
    input.type = "checkbox";
    input.name = "ocr_model_profile";
    input.value = profile.id;
    input.checked = selectedProfiles.has(profile.id);
    title.textContent = profile.title;
    description.textContent = profile.description;
    availability.textContent = "Sprawdzanie dostepnosci...";
    details.append(title, description, availability);
    card.append(input, details);
    profiles.appendChild(card);
    profileCards.set(profile.id, { card, input, availability });
  }
  const slotsHeading = document.createElement("div");
  const slotsTitle = document.createElement("strong");
  const slotsCount = document.createElement("span");
  slotsHeading.className = "ocr-slot-list-heading wide-field";
  slotsTitle.textContent = "Sloty objete kolejka";
  slotsHeading.append(slotsTitle, slotsCount);
  const slots = document.createElement("div");
  slots.className = "settings-slot-list ocr-slot-grid wide-field";
  const enabledSlots = new Set((ocrSettings.enabled_slots || []).map(String));
  const updateSelectedSlotCount = () => {
    const selected = slots.querySelectorAll('input[name="ocr_enabled_slot"]:checked').length;
    slotsCount.textContent = `${selected} z ${(state.settings?.slots || []).length} zaznaczonych`;
  };
  for (const slot of state.settings?.slots || []) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "ocr_enabled_slot";
    input.value = String(slot.prefix || "");
    input.checked = enabledSlots.has(input.value);
    input.addEventListener("change", updateSelectedSlotCount);
    label.append(input, document.createTextNode(` ${slot.label || "Slot"}`));
    const code = document.createElement("small");
    code.textContent = input.value;
    label.appendChild(code);
    slots.appendChild(label);
  }
  updateSelectedSlotCount();
  const analyze = document.createElement("button");
  analyze.type = "button";
  analyze.className = "secondary-button";
  analyze.textContent = "Przetestuj OCR";
  const cancelAnalyze = document.createElement("button");
  cancelAnalyze.type = "button";
  cancelAnalyze.className = "secondary-button";
  cancelAnalyze.textContent = "Zatrzymaj po etapie";
  cancelAnalyze.hidden = true;
  const results = document.createElement("div");
  results.className = "wide-field";
  const collection = settingsFieldGroup(
    "Zbieranie wartosci OCR",
    background,
    queueVisibility,
    idleSeconds,
    maxCpu,
    pauseCpu,
    memoryMode,
    maxMemoryPercent,
    maxMemoryGb,
    maxDiskBusy,
    profiles,
    accurateThreshold,
    slotsHeading,
    slots
  );
  collection.classList.add("ocr-collection-settings");
  form.append(
    collection,
    settingsFieldGroup("Tester OCR", status, engineInfo, file, actionRow(analyze, cancelAnalyze), results)
  );
  analyze.addEventListener("click", async () => {
    const selected = fileInput.files?.[0];
    if (!selected) {
      status.textContent = "Wybierz obraz do analizy.";
      return;
    }
    analyze.disabled = true;
    results.textContent = "";
    let livePreview = null;
    let activeRunId = "";
    let cancelled = false;
    cancelAnalyze.hidden = false;
    cancelAnalyze.onclick = async () => {
      if (!activeRunId || cancelled) return;
      cancelled = true;
      cancelAnalyze.disabled = true;
      try {
        await requestJson(`/api/settings/ocr/runs/${encodeURIComponent(activeRunId)}/cancel`, { method: "POST" });
        status.textContent = "Anulowanie zostanie wykonane po biezacym etapie OCR.";
      } catch (error) {
        status.textContent = error.message || "Nie udalo sie anulowac OCR.";
      }
    };
    status.textContent = "Wysylanie obrazu do lokalnego testu OCR...";
    try {
      const upload = new FormData();
      upload.set("prefix", "ocr-test");
      upload.set("file", selected, selected.name || "ocr-test-image");
      const cached = await requestJson("/api/upload-cache", { method: "POST", body: upload, timeoutMs: 120000 });
      if (!cached.token) throw new Error("Backend nie zwrocil tokenu obrazu testowego.");
      livePreview = await renderOcrLivePreview(selected);
      results.appendChild(livePreview.element);
      livePreview.setStatus("Wysylanie zadania do procesu OCR...");
      status.textContent = "Analiza OCR trwa — sektory i wycinki beda pokazywane na zywo.";
      const started = await requestJson("/api/settings/ocr/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: cached.token }),
        timeoutMs: 30000,
      });
      activeRunId = String(started.run_id || "");
      if (!activeRunId) throw new Error("Backend nie zwrocil identyfikatora testu OCR.");
      livePreview.setStatus("Zadanie przekazane do procesu OCR; oczekiwanie na rozpoczecie etapu.");
      let sequence = 0;
      let finalSnapshot = null;
      while (!finalSnapshot) {
        const snapshot = await requestJson(`/api/settings/ocr/runs/${encodeURIComponent(activeRunId)}?after_sequence=${sequence}`, { timeoutMs: 30000 });
        sequence = Math.max(sequence, Number(snapshot.latest_sequence) || 0);
        for (const event of Array.isArray(snapshot.events) ? snapshot.events : []) {
          livePreview.showEvent(event);
        }
        if (["completed", "error", "cancelled", "paused"].includes(String(snapshot.state || ""))) {
          finalSnapshot = snapshot;
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 600));
      }
      livePreview.dispose();
      results.textContent = "";
      const result = { ...(finalSnapshot.result || {}), image_url: URL.createObjectURL(selected) };
      results.appendChild(renderOcrDiagnostics(result));
      status.textContent = finalSnapshot.state === "paused"
        ? "Test OCR wstrzymany przez prog uruchomienia zasobow."
        : result.available
        ? "Analiza OCR zakonczona."
        : String(result.message || finalSnapshot.error || "Lokalny OCR nie jest dostepny.");
    } catch (error) {
      status.textContent = error.message || "Nie udalo sie wykonac analizy OCR.";
    } finally {
      livePreview?.dispose();
      analyze.disabled = false;
      cancelAnalyze.hidden = true;
      cancelAnalyze.disabled = false;
    }
  });
  settingsSaveButton(form, (data) => ({
    ocr: {
      enabled_slots: [...form.querySelectorAll('[name="ocr_enabled_slot"]:checked')].map((input) => input.value),
      model_profiles: [...form.querySelectorAll('[name="ocr_model_profile"]:checked')].map((input) => input.value),
      background_enabled: data.has("ocr_background_enabled"),
      background_queue_visible_to_users: data.has("ocr_background_queue_visible_to_users"),
      idle_seconds: data.get("ocr_idle_seconds"),
      max_cpu_percent: data.get("ocr_max_cpu_percent"),
      pause_cpu_percent: data.get("ocr_pause_cpu_percent"),
      max_memory_mode: data.get("ocr_max_memory_mode"),
      max_memory_percent: data.get("ocr_max_memory_percent"),
      max_memory_gb: data.get("ocr_max_memory_gb"),
      max_disk_busy_percent: data.get("ocr_max_disk_busy_percent"),
      accurate_confidence_threshold: data.get("ocr_accurate_confidence_threshold"),
    },
  }));
  settingsOutput.appendChild(form);
  requestJson("/api/settings/ocr/status")
    .then((info) => {
      const engine = info.engine || {};
      const runtime = info.runtime || {};
      const models = Array.isArray(info.models) ? info.models : [];
      const modelStatuses = new Map(models.map((model) => [String(model.id || ""), model]));
      for (const profile of profileDefinitions) {
        const controls = profileCards.get(profile.id);
        const model = modelStatuses.get(profile.id);
        if (!controls) continue;
        const available = model?.status === "ready";
        controls.input.disabled = !available;
        if (!available) controls.input.checked = false;
        controls.card.classList.toggle("unavailable", !available);
        controls.availability.textContent = available
          ? "Dostepny lokalnie"
          : "Niedostepny lokalnie";
      }
      engineInfo.textContent = "";
      const title = document.createElement("strong");
      title.textContent = `${engine.name || "OCR"} ${engine.version || ""}`.trim();
      const runtimeLine = document.createElement("span");
      runtimeLine.textContent = `${runtime.name || "Runtime"}: ${runtime.version || "brak"}`;
      const modelList = document.createElement("ul");
      for (const model of models) {
        const item = document.createElement("li");
        item.textContent = `${model.name || "Model"} ${model.version ? `(${model.version})` : ""} — ${model.status || "unknown"}`;
        modelList.appendChild(item);
      }
      const link = document.createElement("a");
      link.href = String(info.github_url || "https://github.com/PaddlePaddle/PaddleOCR");
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = "Oficjalny projekt OCR na GitHub";
      engineInfo.append(title, runtimeLine, modelList, link);
      const modelReady = models.some((model) => model.status === "ready");
      status.textContent = !info.available
        ? "Silnik OCR nie jest dostepny w tej instalacji."
        : modelReady
          ? "Silnik OCR i model sa gotowe do testu."
          : "Silnik OCR jest zainstalowany, ale wybrany profil nie jest dostepny lokalnie.";
    })
    .catch((error) => {
      status.textContent = error.message || "Nie udalo sie odczytac statusu OCR.";
    });
}

function renderSettingsModuleStatus() {
  const utilities = moduleBuildStatusUtilities();
  const panel = document.createElement("section");
  const heading = document.createElement("div");
  const title = document.createElement("h2");
  const refresh = document.createElement("button");
  const description = document.createElement("p");

  panel.className = "settings-block module-build-status";
  heading.className = "module-build-status-heading";
  title.textContent = "Wersje modulow";
  refresh.type = "button";
  refresh.className = "secondary-button";
  refresh.textContent = "Odswiez porownanie";
  refresh.disabled = state.moduleBuildStatusLoading;
  refresh.addEventListener("click", () => {
    loadModuleBuildStatus(true)
      .catch(() => {})
      .finally(() => renderSettings());
  });
  description.className = "settings-note";
  description.textContent = "Porownanie odczytuje aktualny stan gałęzi źródłowej z GitHub. Nie wysyla danych ani nie uruchamia builda.";
  heading.append(title, refresh);
  panel.append(heading, description);

  if (state.moduleBuildStatusLoading) {
    const loading = document.createElement("p");
    loading.className = "settings-note";
    loading.textContent = "Odczytywanie wersji modulow...";
    panel.appendChild(loading);
  } else if (state.moduleBuildStatusError) {
    const error = document.createElement("p");
    error.className = "error-text";
    error.textContent = state.moduleBuildStatusError;
    panel.appendChild(error);
  } else if (!state.moduleBuildStatus) {
    const loading = document.createElement("p");
    loading.className = "settings-note";
    loading.textContent = "Przygotowywanie porownania...";
    panel.appendChild(loading);
  } else if (!utilities) {
    const error = document.createElement("p");
    error.className = "error-text";
    error.textContent = "Nie zaladowano modulu statusu buildu.";
    panel.appendChild(error);
  } else {
    const snapshot = utilities.normalizeSnapshot(state.moduleBuildStatus);
    const build = snapshot.build;
    const summary = document.createElement("div");
    summary.className = "module-build-status-summary";
    if (build) {
      for (const [label, value] of [
        ["Wariant", build.build_variant],
        ["Build", build.generated_at],
        ["Commit repozytorium", build.repository_commit],
        ["Galeź źródłowa", build.source_ref],
        [
          "Python buildu",
          build.python.version
            ? `${build.python.version}${build.python.implementation ? ` (${build.python.implementation})` : ""}`
            : "",
        ],
      ]) {
        const item = document.createElement("div");
        const itemLabel = document.createElement("span");
        const itemValue = document.createElement("strong");
        itemLabel.textContent = label;
        if (label === "Commit repozytorium") {
          itemValue.appendChild(moduleBuildStatusCommitNode(value, utilities));
        } else {
          itemValue.textContent = moduleBuildStatusValue(value);
        }
        item.append(itemLabel, itemValue);
        summary.appendChild(item);
      }
    } else {
      summary.textContent = "Brak wbudowanych danych buildu. Ten program wymaga ponownego zbudowania.";
    }
    panel.appendChild(summary);

    if (snapshot.repository_status !== "github_available") {
      const note = document.createElement("p");
      note.className = "settings-note";
      note.textContent = snapshot.repository_status === "source_ref_missing"
        ? "Ten starszy build nie zawiera nazwy gałęzi źródłowej. Zbuduj go ponownie, aby porównać z GitHub."
        : "Nie udało się odczytać aktualnego stanu GitHub. Sprawdź połączenie, dostęp do repozytorium i spróbuj ponownie.";
      panel.appendChild(note);
    }

    if (build) {
      appendModuleBuildDependencies(panel, build.dependencies);
    }

    const tableWrapper = document.createElement("div");
    const table = document.createElement("table");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    const body = document.createElement("tbody");
    tableWrapper.className = "module-build-status-table-wrapper";
    table.className = "module-build-status-table";
    for (const label of [
      "Modul",
      "Ostatnia zmiana w buildzie",
      "Ostatnia zmiana na GitHub",
      "Status",
    ]) {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = label;
      headRow.appendChild(cell);
    }
    head.appendChild(headRow);
    for (const module of snapshot.modules) {
      appendModuleBuildStatusRow(
        body,
        module,
        utilities.statusLabel(module.status),
        utilities,
      );
    }
    if (!snapshot.modules.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 4;
      cell.textContent = "Brak danych o modulach w tym buildzie.";
      row.appendChild(cell);
      body.appendChild(row);
    }
    table.append(head, body);
    tableWrapper.appendChild(table);
    panel.appendChild(tableWrapper);
  }

  settingsOutput.appendChild(panel);
  renderInstalledUpdateControls(panel);
  if (!state.moduleBuildStatus && !state.moduleBuildStatusLoading && !state.moduleBuildStatusError) {
    loadModuleBuildStatus()
      .catch(() => {})
      .finally(() => {
        if (state.activeSettingsTab === "module-status") renderSettings();
      });
  }
}

function renderSettings() {
  if (!state.settings) {
    return;
  }
  settingsOutput.textContent = "";
  document.querySelectorAll(".settings-tab").forEach((button) => {
    const isOcrTab = button.dataset.settingsTab === "ocr";
    button.hidden = isOcrTab && state.settings.ocr_available === false;
    button.classList.toggle("active", button.dataset.settingsTab === state.activeSettingsTab);
  });
  if (state.settings.ocr_available === false && state.activeSettingsTab === "ocr") {
    state.activeSettingsTab = "app";
  }
  settingsStatus.textContent = state.settings.windows_admin
    ? "Proces backendu ma uprawnienia administratora Windows. Rola web admin jest niezalezna."
    : "Proces backendu dziala bez uprawnien administratora Windows. Rola web admin jest niezalezna.";
  if (state.activeSettingsTab === "app") renderSettingsApp();
  if (state.activeSettingsTab === "module-status") renderSettingsModuleStatus();
  if (state.activeSettingsTab === "processing") renderSettingsProcessing();
  if (state.activeSettingsTab === "security") renderSettingsSecurity();
  if (state.activeSettingsTab === "ftp") renderSettingsFtp();
  if (state.activeSettingsTab === "sql") renderSettingsSql();
  if (state.activeSettingsTab === "pimcore") renderSettingsPimcore();
  if (state.activeSettingsTab === "ocr") renderSettingsOcr();
  if (state.activeSettingsTab === "mail") renderSettingsMail();
  if (state.activeSettingsTab === "monitor") renderSettingsResourceMonitor();
  if (state.activeSettingsTab === "slots") renderSettingsSlots();
  if (state.activeSettingsTab === "users") renderSettingsUsers();
}
