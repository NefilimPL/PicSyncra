import multiprocessing
from picsyncra.installation.installed_entry import main

if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
