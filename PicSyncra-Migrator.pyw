"""Standalone GUI entry point for one legacy SQLite migration."""

import multiprocessing


if __name__ == "__main__":
    multiprocessing.freeze_support()

    from picsyncra.offline_migrator_gui import main

    main()
