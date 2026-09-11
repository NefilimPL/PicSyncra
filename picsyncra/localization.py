"""Localization handling and translated UI strings."""

from .common import *  # noqa: F401,F403 - reuse legacy globals
from . import config, settings

LANG_CFG = "language.json"
LOCAL_SETTINGS_PATH = settings.BASE_DIR_SETTINGS_PATH
LANGUAGE_KEY = LANGUAGE_PREF_KEY
LANGUAGE_DEFAULT = LANGUAGE_PREF_DEFAULT
LC = settings.LC


def load_language_pref():
    """Read the saved language preference from ``local_settings.json``."""

    try:
        with x(LOCAL_SETTINGS_PATH, "r", encoding=k) as handle:
            data = Ar.load(handle)
        if Aq(data, dict):
            value = data.get(LANGUAGE_KEY, LANGUAGE_DEFAULT)
            if Aq(value, str):
                value = value.strip() or LANGUAGE_DEFAULT
                if value:
                    return value
    except E:
        pass
    legacy_path = A.path.join(LC, LANG_CFG)
    try:
        with x(legacy_path, "r", encoding=k) as handle:
            legacy_data = Ar.load(handle)
        if Aq(legacy_data, dict):
            value = legacy_data.get(LANGUAGE_KEY, LANGUAGE_DEFAULT)
            if Aq(value, str):
                value = value.strip() or LANGUAGE_DEFAULT
                if value:
                    return value
    except E:
        pass
    return LANGUAGE_DEFAULT


def save_language_pref(lang):
    """Persist the user's language preference to ``local_settings.json``."""

    value = lang.strip() if Aq(lang, str) else LANGUAGE_DEFAULT
    if not value:
        value = LANGUAGE_DEFAULT
    data = dict(BASE_DIR_SETTINGS_TEMPLATE)
    try:
        with x(LOCAL_SETTINGS_PATH, "r", encoding=k) as handle:
            existing = Ar.load(handle)
        if Aq(existing, dict):
            data.update(existing)
    except E:
        pass
    data[LANGUAGE_KEY] = value
    try:
        A.makedirs(A.path.dirname(LOCAL_SETTINGS_PATH) or ".", exist_ok=J)
    except E:
        pass
    try:
        with x(LOCAL_SETTINGS_PATH, T, encoding=k) as handle:
            Ar.dump(data, handle, indent=4)
    except E:
        pass


def load_localization(language=I):
    """Load translation strings for the requested language code."""

    lang_code = language
    if not lang_code or lang_code == "auto":
        try:
            BO.setlocale(BO.LC_ALL, "")
            lang_code = (BO.getlocale()[0] or "en").split("_")[0]
        except E:
            lang_code = "en"
    mapping = {"pl": "pl.json", "ua": "ua.json", "en": "eng.json"}
    filename = mapping.get(lang_code.lower(), "eng.json")
    module_dir = A.path.dirname(A.path.abspath(__file__))
    search_roots = []
    for root in [LC] + settings.get_localization_search_paths():
        if root and root not in search_roots:
            search_roots.append(root)
    fallback_root = A.path.join(module_dir, "Localization")
    if fallback_root not in search_roots:
        search_roots.append(fallback_root)
    for root in search_roots:
        candidate = A.path.join(root, filename)
        if A.path.exists(candidate):
            try:
                with x(candidate, "r", encoding=k) as handle:
                    payload = Ar.load(handle)
                if Aq(payload, dict):
                    return payload
            except E:
                pass
    return {}


LC = LC or settings.LC_DEFAULT
LANG_PREF = load_language_pref()
LANG = load_localization(LANG_PREF)
LANG_EN = load_localization("en")

settings.LC = LC

NO_FILE_LABEL = LANG.get("no_file", NO_FILE_FALLBACK)
LANGUAGE_TAB_LABEL = LANG.get("language_tab", "Język")
LANGUAGE_LABEL = LANG.get("language_label", "Język:")
TRANSLATION_SECTION_LABEL = LANG.get(
    "translation_section_label", "Tłumaczenia pól"
)
TRANSLATION_PROVIDER_LABEL = LANG.get(
    "translation_provider_label", "Dostawca tłumaczeń:"
)
TRANSLATION_PROVIDER_GOOGLE_LABEL = LANG.get(
    "translation_provider_google", "Google (bez API)"
)
TRANSLATION_PROVIDER_MYMEMORY_LABEL = LANG.get(
    "translation_provider_mymemory", "MyMemory (bez API)"
)
TRANSLATION_PROVIDER_DEEPL_LABEL = LANG.get(
    "translation_provider_deepl", "DeepL (API)"
)
TRANSLATION_API_KEY_LABEL = LANG.get(
    "translation_api_key_label", "Klucz API:"
)
TRANSLATION_API_URL_LABEL = LANG.get(
    "translation_api_url_label", "URL API (opcjonalnie):"
)
BASE_DIR_PROMPT_TITLE = LANG.get("base_dir_prompt_title", BASE_DIR_PROMPT_TITLE)
BASE_DIR_PROMPT_REQUIRED_MSG = LANG.get(
    "base_dir_prompt_required", BASE_DIR_PROMPT_REQUIRED_MSG
)
BASE_DIR_INVALID_SELECTION_MSG = LANG.get(
    "base_dir_invalid_selection", BASE_DIR_INVALID_SELECTION_MSG
)
BASE_DIR_PROMPT_REASON_MSG = LANG.get(
    "base_dir_prompt_reason", BASE_DIR_PROMPT_REASON_MSG
)
BASE_DIR_OVERRIDE_INVALID_MSG = LANG.get(
    "base_dir_override_invalid", BASE_DIR_OVERRIDE_INVALID_MSG
)
CONFIG_DIR_PROMPT_TITLE = LANG.get(
    "config_dir_prompt_title", CONFIG_DIR_PROMPT_TITLE
)
PROCESSING_MSG = LANG.get("processing", PROCESSING_MSG)
PROCESSING_UI_MSG = LANG.get(
    "processing_ui", ">>> Processing, please wait..."
)
OPERATION_TITLE = LANG.get("operation_title", OPERATION_TITLE)
NETWORK_ERROR_MSG = LANG.get("network_error", NETWORK_ERROR_MSG)
PATH_NOT_FOUND_MSG = LANG.get("path_not_found", PATH_NOT_FOUND_MSG)
LOGIN_DATA_ERROR_MSG = LANG.get("login_data_error", LOGIN_DATA_ERROR_MSG)
MISSING_FIELDS_MSG = LANG.get("missing_fields", MISSING_FIELDS_MSG)
INCOMPLETE_DATA_MSG = LANG.get("incomplete_data", INCOMPLETE_DATA_MSG)
NO_DATA_MSG = LANG.get("no_data", NO_DATA_MSG)
CANCEL_LABEL = LANG.get("cancel", CANCEL_LABEL)
SETTINGS_LABEL = LANG.get("settings", SETTINGS_LABEL)
EDIT_LISTS_LABEL = LANG.get("edit_lists", EDIT_LISTS_LABEL)
LIST_TAB_NAMES_LABEL = LANG.get("list_tab_names", LIST_TAB_NAMES_LABEL)
LIST_TAB_TYPES_LABEL = LANG.get("list_tab_types", LIST_TAB_TYPES_LABEL)
LIST_TAB_MODELS_LABEL = LANG.get("list_tab_models", LIST_TAB_MODELS_LABEL)
LIST_TAB_COLORS_LABEL = LANG.get("list_tab_colors", LIST_TAB_COLORS_LABEL)
LIST_TAB_EXTRAS_LABEL = LANG.get("list_tab_extras", LIST_TAB_EXTRAS_LABEL)
LIST_ADD_BUTTON_LABEL = LANG.get("list_add_button", LIST_ADD_BUTTON_LABEL)
LIST_REMOVE_BUTTON_LABEL = LANG.get("list_remove_button", LIST_REMOVE_BUTTON_LABEL)
LIST_ADD_DIALOG_TITLE = LANG.get("list_add_title", LIST_ADD_DIALOG_TITLE)
LIST_REMOVE_DIALOG_TITLE = LANG.get("list_remove_title", LIST_REMOVE_DIALOG_TITLE)
LIST_ADD_PROMPT_MSG = LANG.get("list_add_prompt", LIST_ADD_PROMPT_MSG)
LIST_REMOVE_PROMPT_MSG = LANG.get("list_remove_prompt", LIST_REMOVE_PROMPT_MSG)
LIST_VALUE_EXISTS_MSG = LANG.get("list_value_exists", LIST_VALUE_EXISTS_MSG)
LIST_VALUE_EMPTY_MSG = LANG.get("list_value_empty", LIST_VALUE_EMPTY_MSG)
VALUE_NOT_EXISTS_QUESTION = LANG.get(
    "value_not_exists_add_question",
    "Wartość '{value}' nie istnieje na liście dodatków. Dodać do listy?",
)
NAME_NOT_IN_LIST_QUESTION = LANG.get(
    "name_not_in_list_add_question",
    "Nazwa '{value}' nie istnieje na liście. Czy dodać ją do listy?",
)
TYPE_NOT_IN_LIST_QUESTION = LANG.get(
    "type_not_in_list_add_question",
    "Typ '{value}' nie istnieje na liście. Czy dodać go do listy?",
)
MODEL_NOT_IN_LIST_QUESTION = LANG.get(
    "model_not_in_list_add_question",
    "Model '{value}' nie istnieje na liście. Czy chcesz dodać go do listy?",
)
COLOR_NOT_IN_LIST_SINGLE_QUESTION = LANG.get(
    "color_not_in_list_single_question",
    "Kolor '{value}' nie istnieje na liście. Czy dodać nowy wpis?",
)
COLOR_NOT_IN_LIST_PLURAL_QUESTION = LANG.get(
    "color_not_in_list_plural_question",
    "Kolory '{values}' nie istnieją na liście. Czy dodać nowe wpisy?",
)
EXCEL_LOCKED_TITLE = LANG.get("excel_locked_title", EXCEL_LOCKED_TITLE)
EXCEL_LOCK_OTHER_PROCESS = LANG.get(
    "excel_lock_other_process", EXCEL_LOCK_OTHER_PROCESS
)
EXCEL_LOCKED_BY_USER = LANG.get(
    "excel_locked_by_user", EXCEL_LOCKED_BY_USER
)
LIST_EDITOR_TAB_LABELS = {
    n: LIST_TAB_NAMES_LABEL,
    t: LIST_TAB_TYPES_LABEL,
    s: LIST_TAB_MODELS_LABEL,
    Y: LIST_TAB_COLORS_LABEL,
    d: LIST_TAB_EXTRAS_LABEL,
}
Ac = LANG.get("save_error", Ac)
AJ = LANG.get("not_in_list", AJ)
AK = LANG.get("error", AK)
CHANGE_LANGUAGE_LABEL = LANG.get("change_language", "Zmień język")
LANGUAGE_PROMPT = LANG.get("language_prompt", "Kod języka (pl, ua, eng):")
RESTART_TO_APPLY_LABEL = LANG.get(
    "restart_to_apply", "Uruchom ponownie aplikację, aby zastosować zmiany"
)
SLOT_TITLE_FORMAT = LANG.get("slot_title_format", "{index} {label}")
LOCAL_ICON_LABEL = LANG.get("slot_icon_local", "LOCAL")
FTP_ICON_LABEL = LANG.get("slot_icon_ftp", "FTP")
SQL_ICON_LABEL = LANG.get("slot_icon_sql", "SQL")
UNIT_PERCENT_LABEL = LANG.get("unit_percent", "%")
UNIT_KB_LABEL = LANG.get("unit_kb", "KB")
FILETYPE_IMAGES_LABEL = LANG.get("filetype_images", "Obrazy/PDF/DOC")
FILETYPE_ALL_LABEL = LANG.get("filetype_all", "Wszystkie pliki")
SQL_TEST_ERROR_MSG = LANG.get("sql_test_error", "Błąd: {error}")
CONFIG_SAVE_FAILED_MSG = LANG.get(
    "config_save_failed",
    config.CONFIG_SAVE_FAILED_MSG,
)
config.CONFIG_SAVE_FAILED_MSG = CONFIG_SAVE_FAILED_MSG
LIST_CREATE_FAILED_MSG = LANG.get(
    "list_create_failed",
    "Nie udało się utworzyć pliku list.xlsx:\n{error}",
)
LIST_SAVE_FAILED_MSG = LANG.get(
    "list_save_failed",
    "Nie udało się zapisać pliku list.xlsx:\n{error}",
)
LIST_DATA_SAVE_FAILED_MSG = LANG.get(
    "list_data_save_failed",
    "Nie udało się zapisać danych do pliku list.xlsx:\n{error}",
)
FOLDER_OPEN_FAILED_MSG = LANG.get(
    "folder_open_failed",
    "Nie udało się otworzyć folderu:\n{error}",
)
OPERATION_ERRORS_MSG = LANG.get(
    "operation_errors",
    "Operacja zakończyła się z błędami. Sprawdź logi oraz folder kopii zapasowej: {backup}",
)
FTP_SEND_FAILED_MSG = LANG.get(
    "ftp_send_failed",
    "Dane lokalne zostały zapisane, jednak wysyłanie plików na serwer FTP nie powiodło się.\nPowód: {reason}",
)
FTP_SKIPPED_NO_EAN_MSG = LANG.get(
    "ftp_skipped_no_ean",
    "Dane lokalne zostały zapisane, jednak nie wysłano zdjęć na FTP z powodu braku prawidłowego kodu EAN-13.",
)
SQL_UPDATE_FAILED_MSG = LANG.get(
    "sql_update_failed",
    "Dane lokalne oraz FTP zostały zaktualizowane, jednak wystąpił błąd podczas aktualizacji bazy danych.\nPowód: {reason}",
)
SAVED_LABEL = LANG.get("saved", "Zapisano")
UPDATE_SUCCESS_MSG = LANG.get(
    "update_success", "Zaktualizowano dane dla EAN {ean}."
)
NO_EAN_LABEL = LANG.get("no_ean", "Brak EAN")
ENTER_EAN_TO_LOAD_MSG = LANG.get(
    "enter_ean_to_load", "Wprowadź kod EAN, aby wczytać dane."
)
CANNOT_SEARCH_NO_EAN_MSG = LANG.get(
    "cannot_search_no_ean", "Nie można wyszukać danych dla 'BRAK-EAN'."
)
NOT_FOUND_LABEL = LANG.get("not_found", "Nie znaleziono")
NO_SAVED_DATA_FOR_EAN_MSG = LANG.get(
    "no_saved_data_for_ean", "Brak zapisanych danych dla EAN {ean}."
)
FILL_REQUIRED_BEFORE_OPEN_MSG = LANG.get(
    "fill_required_before_open",
    "Uzupełnij wszystkie wymagane pola (nazwa, typ, model, kolor 1) przed otwarciem folderu.",
)
CHANGE_DATA_ADMIN_LABEL = LANG.get(
    "change_data_admin", "Zmień dane (Administrator)"
)
DATABASE_LABEL = LANG.get("database_label", "Baza danych:")
SERVER_LABEL = LANG.get("server_label", "Serwer:")
MSSQL_SERVER_LABEL = LANG.get("mssql_server", "MS SQL Server")
TEST_BUTTON_LABEL = LANG.get("test_button", "Testuj")
CONNECTED_LABEL = LANG.get("connected", "Połączono")
PASSWORD_LABEL = LANG.get("password_label", "Hasło:")
USER_LABEL = LANG.get("user_label", "Użytkownik:")
MYSQL_LABEL = LANG.get("mysql_label", "MySQL")
SAVE_LABEL = LANG.get("save", "Zapisz")
NO_PERMISSIONS_LABEL = LANG.get("no_permissions", "Brak uprawnień")
RUN_AS_ADMIN_MSG = LANG.get(
    "run_as_admin",
    "Uruchom operację z uprawnieniami administratora, aby edytować te ustawienia.",
)
APP_SETTINGS_LABEL = LANG.get(
    "app_settings_label", "Ustawienia aplikacji"
)
APP_SECRET_LABEL = LANG.get("app_secret_label", "APP_SECRET:")
BASE_DIR_OVERRIDE_LABEL = LANG.get(
    "base_dir_override_label", "Katalog bazowy:"
)
APP_SETTINGS_HINT = LANG.get(
    "app_settings_hint",
    "Zmiana katalogu bazowego wymaga ponownego uruchomienia aplikacji.",
)
APP_SECRET_REQUIRED_MSG = LANG.get(
    "app_secret_required", "APP_SECRET nie może być pusty."
)
APP_SETTINGS_RESTART_MSG = LANG.get(
    "app_settings_restart",
    "Zmiana katalogu bazowego zostanie zastosowana po ponownym uruchomieniu aplikacji.",
)
LOCAL_SETTINGS_SAVE_FAILED_MSG = LANG.get(
    "local_settings_save_failed",
    "Nie udało się zapisać local_settings.json:\n{error}",
)
IMAGE_SETTINGS_LABEL = LANG.get(
    "image_settings", "Ustawienia przetwarzania obrazów:"
)
RESIZE_LABEL = LANG.get(
    "resize_label", "Zmniejszaj obrazy większe niż"
)
PX_MAX_LABEL = LANG.get("px_max_label", "px (max wymiar)")
COMPRESS_LABEL = LANG.get(
    "compress_label", "Kompresuj JPEG (jakość)"
)
LIMIT_SIZE_LABEL = LANG.get(
    "limit_size_label", "Ogranicz rozmiar pliku do"
)
CONVERT_TIF_LABEL = LANG.get(
    "convert_tif_label", "Konwertuj .tif na"
)
FTP_SERVER_LABEL = LANG.get("ftp_server_label", "Serwer FTP:")
PORT_LABEL = LANG.get("port_label", "Port:")
FTP_PATH_LABEL = LANG.get(
    "ftp_path_label", "Ścieżka (katalog) na serwerze:"
)
FTP_TEST_LABEL = LANG.get(
    "ftp_test_label", "Test połączenia FTP:"
)
FTP_UPDATE_LABEL = LANG.get(
    "ftp_update_label", "Aktualizuj pliki na FTP:"
)
DB_TYPE_LABEL = LANG.get("db_type_label", "Typ bazy danych:")
SQL_UPDATE_LABEL = LANG.get(
    "sql_update_label", "Aktualizuj bazę przy zapisie:"
)
SQL_QUERY_LABEL = LANG.get("sql_query_label", "Zapytanie SQL:")
SQL_TEST_LABEL = LANG.get("sql_test_label", "Test połączenia SQL:")
SQL_MAPPING_LABEL = LANG.get("sql_mapping_label", "Przypisanie kolumn SQL")
SQL_DETECT_COLUMNS_LABEL = LANG.get("sql_detect_columns", "Wykryj kolumny")
SQL_COLUMNS_LABEL = LANG.get("sql_columns_label", "Dostępne kolumny")
SQL_COLUMNS_QUERY_LABEL = LANG.get(
    "sql_columns_query_label", "Zapytanie wykrywania kolumn:"
)
SQL_COLUMNS_DETECTED_MSG = LANG.get(
    "sql_columns_detected_msg",
    "Wykryto {count} kolumn w tabeli {table}.",
)
SQL_COLUMNS_DETECT_FAILED_MSG = LANG.get(
    "sql_columns_detect_failed_msg",
    "Nie udało się wykryć kolumn: {error}",
)
SQL_COLUMNS_PARSE_FAILED_MSG = LANG.get(
    "sql_columns_parse_failed_msg",
    "Nie udało się odczytać nazwy tabeli z zapytania SQL.",
)
SQL_COLUMNS_QUERY_UNAVAILABLE_MSG = LANG.get(
    "sql_columns_query_unavailable",
    "Podgląd zapytania pojawi się po wpisaniu poprawnego zapytania UPDATE.",
)
SQL_MAPPING_FIELD_LABEL = LANG.get("sql_mapping_field_label", "Pole")
SQL_MAPPING_COLUMN_LABEL = LANG.get("sql_mapping_column_label", "Kolumna SQL")
SQL_MAPPING_HINT = LANG.get(
    "sql_mapping_hint",
    "Przeciągnij kolumnę na pole lub wpisz nazwę ręcznie.",
)
SQL_MAPPING_EMPTY_LABEL = LANG.get(
    "sql_mapping_empty_label", "SQL: (brak)"
)
NAME_LABEL = LANG.get("name_label", "Nazwa mebla*:")
TYPE_LABEL = LANG.get("type_label", "Typ mebla*:")
MODEL_LABEL = LANG.get("model_label", "Model mebla*:")
COLOR1_LABEL = LANG.get("color1_label", "Kolor 1*:")
COLOR2_LABEL = LANG.get("color2_label", "Kolor 2:")
COLOR3_LABEL = LANG.get("color3_label", "Kolor 3:")
EXTRA_LABEL = LANG.get("extra_label", "Dodatkowe:")
EAN_OPTIONAL_LABEL = LANG.get(
    "ean_optional_label", "EAN (opcjonalnie):"
)
LOAD_LABEL = LANG.get("load_label", "Wczytaj")
OPEN_FOLDER_LABEL = LANG.get(
    "open_folder", LANG_EN.get("open_folder", "Open folder")
)
CLEAR_LOG_LABEL = LANG.get("clear_log", LANG_EN.get("clear_log", "Clear log"))
UPDATE_LABEL = LANG.get("update_label", "Aktualizuj")
CHOOSE_LABEL = LANG.get("choose_label", "Wybierz")
NEW_COMBINATION_LABEL = LANG.get("new_combination_label", "Nowa kombinacja")
FTP_ERROR_LABEL = LANG.get("ftp_error", "Błąd FTP")
SQL_ERROR_LABEL = LANG.get("sql_error", "Błąd SQL")
IMAGES_TAB_LABEL = LANG.get("images_tab", "Obrazy")
FTP_TAB_LABEL = LANG.get("ftp_tab", "FTP")
SQL_TAB_LABEL = LANG.get("sql_tab", "SQL")
FIELDS_TAB_LABEL = LANG.get("fields_tab", "Pola zdjęć")
APP_TAB_LABEL = LANG.get("app_tab", "Aplikacja")
FIELDS_MANAGE_LABEL = LANG.get(
    "fields_manage_label", "Pola na zdjęcia"
)
FIELD_ADD_LABEL = LANG.get("field_add_label", "+ (DODAJ POLE)")
FIELD_ADD_TITLE = LANG.get("field_add_title", "Dodaj pole")
FIELD_EDIT_TITLE = LANG.get("field_edit_title", "Edytuj pole")
FIELD_NAME_LABEL = LANG.get("field_name_label", "Nazwa pola:")
FIELD_NAME_PROMPT = LANG.get(
    "field_name_prompt", "Podaj nazwę pola:"
)
FIELD_NAME_REQUIRED_MSG = LANG.get(
    "field_name_required", "Podaj nazwę pola."
)
FIELD_NAME_DUPLICATE_MSG = LANG.get(
    "field_name_duplicate", "Pole '{label}' już istnieje."
)
FIELD_ID_LABEL = LANG.get("field_id_label", "ID w nazwie pliku:")
FIELD_ID_REQUIRED_MSG = LANG.get(
    "field_id_required", "Podaj ID pola."
)
FIELD_ID_INVALID_MSG = LANG.get(
    "field_id_invalid", "ID pola musi być liczbą większą od 0."
)
FIELD_ID_DUPLICATE_MSG = LANG.get(
    "field_id_duplicate",
    "ID '{prefix}' jest już zajęte przez pole '{label}'.",
)
FIELD_DELETE_LABEL = LANG.get("field_delete_label", "Usuń")
FIELD_DELETE_CONFIRM_MSG = LANG.get(
    "field_delete_confirm", "Czy usunąć pole '{label}'?"
)
FIELD_TRANSLATE_LABEL = LANG.get(
    "field_translate_label", "Propozycje tłumaczeń"
)
FIELD_TRANSLATE_TITLE = LANG.get(
    "field_translate_title", "Propozycje tłumaczeń"
)
FIELD_TRANSLATE_NO_FILES_MSG = LANG.get(
    "field_translate_no_files",
    "Brak dostępnych plików lokalizacji.",
)
FIELD_TRANSLATE_SAVE_FAILED_MSG = LANG.get(
    "field_translate_save_failed",
    "Nie udało się zapisać tłumaczeń: {error}",
)
FIELD_TRANSLATE_FETCH_FAILED_MSG = LANG.get(
    "field_translate_fetch_failed",
    "Nie udało się pobrać tłumaczeń. Sprawdź połączenie z internetem.",
)
FIELD_TRANSLATE_FETCH_FAILED_DETAIL_MSG = LANG.get(
    "field_translate_fetch_failed_detail",
    "Nie udało się pobrać tłumaczeń ({provider}): {error}",
)
FIELD_TRANSLATE_ENTRY_ERROR_MSG = LANG.get(
    "field_translate_entry_error",
    "Błąd tłumaczenia ({provider}): {error}",
)
FIELD_TRANSLATE_MISSING_API_KEY_MSG = LANG.get(
    "field_translate_missing_api_key",
    "Brak klucza API tłumaczeń. Uzupełnij go w ustawieniach.",
)
SLOT_DEFS_REBUILD_PROMPT = LANG.get(
    "slot_defs_rebuild_prompt",
    "Zmiana pól zdjęć wyczyści bieżące dane w oknach. Kontynuować?",
)
WARNING_LABEL = LANG.get("warning", "Uwaga")
SELECT_COMBINATION_TITLE = LANG.get(
    "select_combination_title", "Wybierz istniejącą kombinację"
)
SELECT_COMBINATION_PROMPT = LANG.get(
    "select_combination_prompt",
    "Wybierz istniejącą kombinację kolorów:",
)
SELECT_FILE_TITLE = LANG.get("select_file_title", "Wybierz plik")
OTHER_ERROR_MSG = LANG.get("other_error", "Inny błąd: {error}")
FTP_UPLOAD_ERROR_MSG = LANG.get(
    "ftp_upload_error_summary",
    "Błąd wysyłania pliku {file}: {error}",
)
FTP_DELETE_FAILED_MSG = LANG.get(
    "ftp_delete_failed_list",
    "Nie udało się usunąć niektórych plików na FTP: {files}",
)
FTP_DELETE_FAILED_APPEND_MSG = LANG.get(
    "ftp_delete_failed_append",
    ". Nie udało się usunąć plików: {files}",
)
SQL_FORMAT_ERROR_MSG = LANG.get(
    "sql_format_error",
    "Błąd formatowania zapytania SQL: {error}",
)
FTP_GENERIC_ERROR_MSG = LANG.get("ftp_generic_error", "Błąd FTP: {error}")
FILL_REQUIRED_BEFORE_SUBMIT_MSG = LANG.get(
    "fill_required_before_submit",
    "Uzupełnij wszystkie wymagane pola oznaczone * przed zatwierdzeniem.",
)
EAN_PROMPT_TITLE = LANG.get("ean_prompt_title", "EAN")
EAN_MISSING_PROMPT = LANG.get(
    "ean_missing_prompt",
    "Nie podano EAN.\nWprowadź kod EAN (13 cyfr) lub pozostaw puste aby użyć 'BRAK-EAN':",
)
APP_TITLE = LANG.get("app_title", "Katalogowanie zdjęć mebli")


def get_slot_label(label):
    """Return a localized slot label name when available."""

    if not label:
        return label
    key = f"slot_label_{label.lower()}"
    return LANG.get(key, label)
