"""Database connectivity helpers."""

from .common import *  # noqa: F401,F403
from .settings import BW
from . import config


def connect_db():
    """Establish a database connection based on the configured backend."""

    # The user can toggle between MySQL and MSSQL, so detect the current
    # preference and build an appropriate connection object.
    db_type = config.CONFIG.get(p, K).lower()
    if db_type == K:
        mysql_cfg = config.CONFIG[K]
        return mysql.connector.connect(
            host=mysql_cfg[c],
            user=mysql_cfg[N],
            password=mysql_cfg[M],
            database=mysql_cfg[b],
            connection_timeout=5,
            use_pure=True,
        )
    sql_cfg = config.CONFIG[P]
    server = sql_cfg.get(c)
    database = sql_cfg.get(b)
    user = sql_cfg.get(N)
    password = sql_cfg.get(M)
    last_exc = None
    extra = "Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=5"
    try:
        drivers_seen = pyodbc.drivers()
    except E:
        drivers_seen = []
    for driver in BW:
        # Iterate through known driver names until one successfully connects.
        try:
            conn_str = (
                f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};"
                f"UID={user};PWD={password};{extra}"
            )
            return pyodbc.connect(conn_str)
        except E as exc:
            last_exc = exc
            continue
    import struct

    arch = f"{struct.calcsize('P') * 8}-bit EXE on {BR.platform()}"
    msg = (
        "Brak działającego sterownika ODBC do MSSQL.\n"
        f"Próbowano: {', '.join(BW)}\n"
        f"System widzi sterowniki: {', '.join(drivers_seen) or '(brak)'}\n"
        f"Architektura: {arch}\n"
        f"Ostatni błąd: {last_exc}"
    )
    # Raising an exception bubbles the detailed message up to the UI and
    # logging layer for troubleshooting.
    raise E(msg)
