"""Shared constants, imports and helper utilities for PicSyncra."""

from .pimcore_config import PIMCORE_SETTINGS_KEY, default_pimcore_settings
from .product_fields import PRODUCT_FIELDS_KEY, default_product_fields
from .email_settings import EMAIL_SETTINGS_KEY, default_email_settings
from .ocr_settings import OCR_SETTINGS_KEY, default_ocr_settings

################################ Aktualne ustawienia startowe aplikacji ################################
# --- Konfigurowalne ustawienia ---
# Katalog roboczy aplikacji jest odczytywany z pliku `local_settings.json`.
# Poniższa wartość służy jedynie do wstępnego uzupełnienia pliku przy pierwszym
# uruchomieniu (wpis w `local_settings.json` zawsze ma pierwszeństwo).
BASE_DIR_OVERRIDE = r""
# Nazwa lokalnego pliku konfiguracyjnego z ustawieniami katalogu bazowego.
BASE_DIR_SETTINGS_FILE = "local_settings.json"
# Klucz przechowujący preferowany język interfejsu użytkownika.
LANGUAGE_PREF_KEY = "language"
# Wartość domyślna dla ustawień językowych (automatyczny wybór).
LANGUAGE_PREF_DEFAULT = "auto"
# Domyślna struktura wspomnianego pliku.
BASE_DIR_SETTINGS_TEMPLATE = {
    "base_dir_override": BASE_DIR_OVERRIDE,
    LANGUAGE_PREF_KEY: LANGUAGE_PREF_DEFAULT,
}

# Klucz używany do prostego szyfrowania danych konfiguracyjnych.
APP_SECRET = "secret_v1"
# Klucz ustawień przechowujący sekret aplikacji.
APP_SECRET_KEY = "app_secret"
BASE_DIR_SETTINGS_TEMPLATE[APP_SECRET_KEY] = APP_SECRET

# Domyślny port serwera FTP.
PORT = 21

# Zapytanie SQL aktualizujące ścieżkę do obrazu.
SQL_UPDATE_TEMPLATE = ""

# Domyślne dane konfiguracyjne wykorzystywane przy pierwszym uruchomieniu.
DEFAULT_CONFIG = {
    "ftp": {
        "host": r"",
        "port": PORT,
        "user": r"",
        "pass": r"",
        "path": r"/PHOTOS/",
    },
    "sql": {
        "server": r"",
        "database": r"",
        "user": r"",
        "pass": r"",
    },
    "mysql": {
        "server": r"",
        "database": r"",
        "user": r"",
        "pass": r"",
    },
    "db_type": r"mysql",
    "sql_query": SQL_UPDATE_TEMPLATE,
    "enable_ftp_update": True,
    "enable_sql_update": True,
}
# --- Koniec konfiguracji ---

# Komunikaty dla użytkownika
PROCESSING_MSG = "Trwa przetwarzanie. Poczekaj na zakończenie bieżącej operacji."
OPERATION_TITLE = "Operacja w toku"

# Podstawowe ustawienia
A_ = "1.0"
Az = "normal"
Ay = False
Ax = range
Al = True
Ak = "disabled"
Aj = getattr
AQ = None

# Komunikaty o błędach
NETWORK_ERROR_MSG = "Błąd sieciowy lub brak internetu"
PATH_NOT_FOUND_MSG = "Nie znaleziono ścieżki na serwerze"
NO_SUCH_FILE_MSG = "No such file"
LOGIN_DATA_ERROR_MSG = "Błędne dane logowania"
LOGIN_INCORRECT_MSG = "Login incorrect"
FTP_GENERIC_ERROR_MSG = "Błąd FTP: {error}"
OTHER_ERROR_MSG = "Inny błąd: {error}"
NO_DATA_MSG = "Brak danych"
MISSING_FIELDS_MSG = "Uzupełnij wszystkie wymagane pola przed dodaniem pliku."
INCOMPLETE_DATA_MSG = "Niekompletne dane"

BASE_DIR_PROMPT_TITLE = "Wybierz katalog roboczy"
BASE_DIR_PROMPT_REQUIRED_MSG = (
    "Nie wskazano katalogu roboczego. Aplikacja zostanie zamknięta."
)
BASE_DIR_INVALID_SELECTION_MSG = (
    "Nie udało się uzyskać dostępu do wskazanego katalogu. Wybierz inną lokalizację."
)
BASE_DIR_PROMPT_REASON_MSG = (
    "W pliku \"local_settings.json\" nie zapisano katalogu bazowego lub wskazana "
    "ścieżka jest niedostępna. Wskaż folder, w którym mają być zapisywane i "
    "odczytywane dane."
)
BASE_DIR_OVERRIDE_INVALID_MSG = (
    "Nie można uzyskać dostępu do katalogu wskazanego w pliku \"local_settings.json\":\n"
    "{path}\n\n"
    "{reason}"
)
CONFIG_DIR_PROMPT_TITLE = "Wskaż folder z plikiem konfiguracyjnym"
EXCEL_LOCKED_TITLE = "Plik zablokowany"
EXCEL_LOCK_OTHER_PROCESS = "przez inny proces"
EXCEL_LOCKED_BY_USER = "przez użytkownika '{user}'"

# Oznaczenia interfejsu
CANCEL_LABEL = "Anuluj"
SETTINGS_LABEL = "Ustawienia"
EDIT_LISTS_LABEL = "Edytuj listy"
LIST_TAB_NAMES_LABEL = "Nazwy"
LIST_TAB_TYPES_LABEL = "Typy"
LIST_TAB_MODELS_LABEL = "Modele"
LIST_TAB_COLORS_LABEL = "Kolory"
LIST_TAB_EXTRAS_LABEL = "Dodatki"
LIST_ADD_BUTTON_LABEL = "Dodaj"
LIST_REMOVE_BUTTON_LABEL = "Usuń"
LIST_ADD_DIALOG_TITLE = "Dodaj"
LIST_REMOVE_DIALOG_TITLE = "Usuń"
LIST_ADD_PROMPT_MSG = "Nowa wartość do listy {list}:"
LIST_REMOVE_PROMPT_MSG = "Czy usunąć '{value}' z listy {list}?"
LIST_VALUE_EXISTS_MSG = "Wartość '{value}' już istnieje na liście {list}."
LIST_VALUE_EMPTY_MSG = "Wartość nie może być pusta."
LIGHT_GREEN = "lightgreen"
OPEN_FURNITURE = "open_furniture"
NON_PIC = "non_pic"
ELEMENT_PIC = "element_pic"
DEFAULT_SLOT_DEFS = [
    {"prefix": "01", "label": "Assembly_instruction"},
    {"prefix": "02", "label": "Assembly_instruction1"},
    {"prefix": "03", "label": "DETAIL_pic"},
    {"prefix": "04", "label": "DETAIL_pic1"},
    {"prefix": "05", "label": "element_pic1"},
    {"prefix": "06", "label": ELEMENT_PIC},
    {"prefix": "07", "label": "LED_Assembly_instruction"},
    {"prefix": "08", "label": "MOOD_pic"},
    {"prefix": "09", "label": "MOOD_pic1"},
    {"prefix": "10", "label": "MOOD_pic2"},
    {"prefix": "11", "label": "MOOD_pic3"},
    {"prefix": "12", "label": "MOOD_pic4"},
    {"prefix": "13", "label": "MOOD_pic5"},
    {"prefix": "14", "label": NON_PIC},
    {"prefix": "15", "label": OPEN_FURNITURE},
    {"prefix": "16", "label": "open_furniture1"},
    {"prefix": "17", "label": "open_furniture2"},
    {"prefix": "18", "label": "NO_EAN"},
    {"prefix": "19", "label": "Technical_drawing"},
    {"prefix": "20", "label": "Technical_drawing1"},
    {"prefix": "21", "label": "Technical_drawing2"},
    {"prefix": "22", "label": "WB_pic"},
    {"prefix": "23", "label": "WB_pic1"},
    {"prefix": "24", "label": "WB_pic2"},
    {"prefix": "25", "label": "WB_pic3"},
    {"prefix": "26", "label": "WB_pic4"},
]

# Klasy wyjątków
timeout_error = TimeoutError
connection_refused_error = ConnectionRefusedError
TIMEOUT_ERROR = timeout_error
CONNECTION_REFUSED_ERROR = connection_refused_error
As = "550"
Am = "left"
An = "vertical"
At = "PNG"
Ao = "Plik zablokowany"
Ap = "przez inny proces"
Aq = isinstance
Au = OSError
AR = "blue"
AS = "frame"
Aa = "prefix"
Ab = "red"
AT = "white"
NO_FILE_FALLBACK = "Brak pliku"
AV = "right"
Ac = "Błąd zapisu"
AW = "KOLOR3"
AX = "KOLOR2"
AY = "KOLOR1"
AZ = "MODEL"
Ad = "TYP"
Ae = "NAZWA"
AI = ", "
AJ = "Brak na liście"
AK = "Błąd"
A6 = "%Y-%m-%d %H:%M:%S"
A7 = "x_lbl"
A8 = "#aaa"
A4 = "green"
A2 = "<<ComboboxSelected>>"
y = "img_lbl"
z = "both"
A0 = enumerate
x = open
ft = "enable_ftp_update"
u = "enable_sql_update"
v = "host"
w = "sql_query"
SLOT_DEFS_KEY = "slot_definitions"
SIMILAR_FILE_DETECTION_KEY = "similar_file_detection"
SQL_COLUMN_MAP_KEY = "sql_column_map"
SQL_AVAILABLE_COLUMNS_KEY = "sql_available_columns"
SQL_PROFILES_KEY = "sql_profiles"
LOCAL_FILE_INDEX_KEY = "enable_local_file_index"
AUTO_CONTENT_FIT_KEY = "auto_content_fit"
PROCESSING_SETTINGS_KEY = "processing"
RESOURCE_MONITOR_SETTINGS_KEY = "resource_monitor"
SECURITY_SETTINGS_KEY = "security"
WEB_DISPLAY_SETTINGS_KEY = "web_display"
COLOR_FIELD_LABELS_KEY = "color_field_labels"
TRANSLATION_SETTINGS_KEY = "translation"
TRANSLATION_PROVIDER_KEY = "provider"
TRANSLATION_API_KEY = "api_key"
TRANSLATION_API_URL = "api_url"
TRANSLATION_PROVIDER_GOOGLE = "google"
TRANSLATION_PROVIDER_MYMEMORY = "mymemory"
TRANSLATION_PROVIDER_DEEPL = "deepl"
TRANSLATION_PROVIDER_DEFAULT = TRANSLATION_PROVIDER_GOOGLE
p = "db_type"
q = "BRAK-EAN"
r = "port"
s = "MODELE"
t = "TYPY"
m = "path"
k = "utf-8"
n = "NAZWY"
j = "TCombobox"
f = "filepath"
B0 = "mark"
g = "-"
a = "_"
h = Ay
b = "database"
c = "server"
d = "DODATKI"
Z = "Existing.TCombobox"
Y = "KOLORY"
W = "ENTRIES"
R = "e"
T = "w"
S = "values"
V = Ak
Q = len
P = "sql"
X = Az
M = "pass"
N = "user"
L = "NO-LED"
K = "mysql"
J = Al
I = AQ
H = "ftp"
E = Exception
G = str
B = ""

DEFAULT_CONFIG.setdefault(SLOT_DEFS_KEY, DEFAULT_SLOT_DEFS)
DEFAULT_CONFIG.setdefault(
    SIMILAR_FILE_DETECTION_KEY,
    {"enabled": False, "slot_prefixes": []},
)
DEFAULT_CONFIG.setdefault(
    SQL_COLUMN_MAP_KEY,
    {slot["prefix"]: slot["label"] for slot in DEFAULT_SLOT_DEFS},
)
DEFAULT_CONFIG.setdefault(SQL_AVAILABLE_COLUMNS_KEY, [])
DEFAULT_CONFIG.setdefault(SQL_PROFILES_KEY, [])
DEFAULT_CONFIG.setdefault(LOCAL_FILE_INDEX_KEY, True)
DEFAULT_CONFIG.setdefault(AUTO_CONTENT_FIT_KEY, False)
DEFAULT_CONFIG.setdefault(WEB_DISPLAY_SETTINGS_KEY, {"time_zone": "UTC"})
DEFAULT_CONFIG.setdefault(
    PROCESSING_SETTINGS_KEY,
    {
        "resize_enabled": True,
        "max_dim": 2000,
        "compress_enabled": False,
        "compress_quality": 85,
        "max_size_enabled": False,
        "max_file_kb": 500,
        "convert_enabled": False,
        "target_format": "PNG",
        "upload_processing_mode": "save",
        "show_timing_details": False,
    },
)
DEFAULT_CONFIG.setdefault(
    RESOURCE_MONITOR_SETTINGS_KEY,
    {
        "show_status": True,
        "cpu_percent_threshold": 25,
        "memory_percent_threshold": 20,
        "io_mib_per_second_threshold": 8,
    },
)
DEFAULT_CONFIG.setdefault(
    SECURITY_SETTINGS_KEY,
    {
        "max_upload_mb": 50,
        "max_upload_pixels": 25_000_000,
        "allowed_upload_extensions": [
            "jpg",
            "jpeg",
            "jfif",
            "jpe",
            "peg",
            "png",
            "apng",
            "webp",
            "gif",
            "bmp",
            "dib",
            "tif",
            "tiff",
            "avif",
            "avifs",
            "heic",
            "heif",
            "hif",
            "jp2",
            "j2k",
            "jpc",
            "jpx",
            "ico",
            "cur",
            "tga",
            "ppm",
            "pgm",
            "pbm",
            "pnm",
            "pcx",
            "pdf",
            "eps",
            "psd",
            "ai",
        ],
        "blocked_upload_extensions": [
            "exe",
            "bat",
            "cmd",
            "com",
            "msi",
            "ps1",
            "vbs",
            "js",
            "jar",
            "dll",
            "scr",
            "pif",
            "sh",
        ],
        "block_executable_uploads": True,
        "antivirus_scan_uploads": False,
        "show_active_web_users": False,
    },
)
DEFAULT_CONFIG.setdefault(COLOR_FIELD_LABELS_KEY, {})
DEFAULT_CONFIG.setdefault(PRODUCT_FIELDS_KEY, default_product_fields())
DEFAULT_CONFIG.setdefault(
    TRANSLATION_SETTINGS_KEY,
    {
        TRANSLATION_PROVIDER_KEY: TRANSLATION_PROVIDER_DEFAULT,
        TRANSLATION_API_KEY: "",
        TRANSLATION_API_URL: "",
    },
)
DEFAULT_CONFIG.setdefault(PIMCORE_SETTINGS_KEY, default_pimcore_settings())
DEFAULT_CONFIG.setdefault(EMAIL_SETTINGS_KEY, default_email_settings())
DEFAULT_CONFIG.setdefault(OCR_SETTINGS_KEY, default_ocr_settings())

import sys
import os as A
import shutil as Af
import getpass
import platform as BR
import locale as BO
from datetime import datetime as A9
import time as Ag
import tempfile
import uuid
import threading
import urllib.request as BN
import urllib.parse as BP
import json as Ar
import base64 as BL
import ssl as _ssl

try:
    import certifi as _certifi
except Exception:  # pragma: no cover - optional runtime dependency
    _certifi = None

AO = getpass.getuser()
AF = BR.node()
OLD_HOST_KEY = (AF or B) + "secret_OLD"
RUNTIME_IMPORT_ERRORS = {}


def _remember_import_error(name, exc):
    """Store optional runtime import failures for later diagnostics."""

    RUNTIME_IMPORT_ERRORS[name] = exc
    return exc


def get_runtime_import_errors():
    """Return a copy of optional runtime import failures."""

    return dict(RUNTIME_IMPORT_ERRORS)


def require_runtime_modules(*module_names):
    """Raise a helpful error when an optional runtime module is unavailable."""

    missing = [name for name in module_names if name in RUNTIME_IMPORT_ERRORS]
    if not missing:
        return
    details = "; ".join(f"{name}: {RUNTIME_IMPORT_ERRORS[name]}" for name in missing)
    raise ModuleNotFoundError(details)


try:
    import tkinter as F
    from tkinter import ttk as C, filedialog as BT, messagebox as O, simpledialog as BI
    from tkinter import scrolledtext as BS
except Exception as exc:  # pragma: no cover - optional runtime dependency
    _remember_import_error("tkinter", exc)
    F = I
    C = I
    BT = I
    O = I
    BI = I
    BS = I

try:
    from tkinterdnd2 import TkinterDnD as BU, DND_ALL, DND_FILES as BJ, DND_TEXT
except Exception as exc:  # pragma: no cover - optional runtime dependency
    _remember_import_error("tkinterdnd2", exc)

    class _MissingTkinterDnD:
        class Tk:
            def __init__(self, *_args, **_kwargs):
                require_runtime_modules("tkinter", "tkinterdnd2")

    BU = _MissingTkinterDnD
    DND_ALL = B
    BJ = B
    DND_TEXT = B

try:
    from PIL import Image as AA, ImageTk
except Exception as exc:  # pragma: no cover - optional runtime dependency
    _remember_import_error("PIL", exc)

    class _MissingImageModule:
        SAVE = set()

        class Resampling:
            LANCZOS = 3

        @staticmethod
        def registered_extensions():
            return {}

        @staticmethod
        def open(*_args, **_kwargs):
            require_runtime_modules("PIL")

    class _MissingImageTk:
        @staticmethod
        def PhotoImage(*_args, **_kwargs):
            require_runtime_modules("PIL")

    AA = _MissingImageModule()
    ImageTk = _MissingImageTk()

try:
    from openpyxl import Workbook as BV, load_workbook as Ah
except Exception as exc:  # pragma: no cover - optional runtime dependency
    _remember_import_error("openpyxl", exc)

    def BV(*_args, **_kwargs):
        require_runtime_modules("openpyxl")

    def Ah(*_args, **_kwargs):
        require_runtime_modules("openpyxl")

import ftplib as AB
import socket as BK

try:
    import pyodbc
except Exception as exc:  # pragma: no cover - optional runtime dependency
    _remember_import_error("pyodbc", exc)
    pyodbc = I

try:
    import mysql.connector
except Exception as exc:  # pragma: no cover - optional runtime dependency
    _remember_import_error("mysql.connector", exc)

    class _MissingMySQLConnector:
        @staticmethod
        def connect(*_args, **_kwargs):
            require_runtime_modules("mysql.connector")

    class _MissingMySQLModule:
        connector = _MissingMySQLConnector()

    mysql = _MissingMySQLModule()
else:
    import mysql

import ctypes

APP_SECRET_PREFIX = "enc:"


def _build_ssl_context():
    """Return an SSL context with bundled CA certificates when available."""
    try:
        cafile = _certifi.where()
    except Exception:
        cafile = None
    try:
        if cafile:
            return _ssl.create_default_context(cafile=cafile)
        return _ssl.create_default_context()
    except Exception:
        return None


SSL_CONTEXT = _build_ssl_context()


def _xor_text(value, key):
    """Return XOR-obfuscated text using ``key``."""

    if not value:
        return B
    key_len = len(key)
    if not key_len:
        return value
    return B.join(chr(ord(ch) ^ ord(key[i % key_len])) for (i, ch) in A0(value))


def _encode_local_secret(value):
    """Encode a secret for storage inside local_settings.json."""

    if not value or not Aq(value, str):
        return B
    stripped = value.strip()
    if not stripped:
        return B
    if stripped.startswith(APP_SECRET_PREFIX):
        return stripped
    raw = _xor_text(stripped, OLD_HOST_KEY)
    return f"{APP_SECRET_PREFIX}{BL.b64encode(raw.encode(k)).decode(k)}"


def _decode_local_secret(value, fallback):
    """Decode a secret stored in local_settings.json."""

    if not value or not Aq(value, str):
        return fallback
    stripped = value.strip()
    if not stripped:
        return fallback
    if not stripped.startswith(APP_SECRET_PREFIX):
        return stripped
    payload = stripped[len(APP_SECRET_PREFIX) :]
    try:
        raw = BL.b64decode(payload.encode(k)).decode(k)
    except E:
        return fallback
    decoded = _xor_text(raw, OLD_HOST_KEY)
    return decoded or fallback

def _resolve_settings_root_for_common():
    """Return the folder that should host ``local_settings.json``."""

    if getattr(sys, "frozen", False):
        base_path = A.path.dirname(sys.executable)
        return base_path or A.getcwd()
    module_dir = A.path.dirname(A.path.abspath(__file__))
    project_root = A.path.abspath(A.path.join(module_dir, A.pardir))
    root_settings = A.path.join(project_root, BASE_DIR_SETTINGS_FILE)
    root_marker = A.path.join(project_root, "PicSyncra.pyw")
    if A.path.exists(root_settings) or A.path.exists(root_marker):
        base_path = project_root
    else:
        base_path = module_dir
    return base_path or A.getcwd()


def _load_app_secret(fallback):
    """Return an override secret from local_settings.json when available."""

    settings_path = A.path.join(
        _resolve_settings_root_for_common(), BASE_DIR_SETTINGS_FILE
    )
    try:
        if A.path.exists(settings_path):
            with x(settings_path, "r", encoding=k) as settings_file:
                data = Ar.load(settings_file)
            if Aq(data, dict):
                value = data.get(APP_SECRET_KEY, fallback)
                decoded = _decode_local_secret(value, fallback)
                if decoded:
                    return decoded
    except E:
        pass
    return fallback


APP_SECRET = _load_app_secret(APP_SECRET)
BASE_DIR_SETTINGS_TEMPLATE[APP_SECRET_KEY] = _encode_local_secret(APP_SECRET)

Ai = OLD_HOST_KEY
