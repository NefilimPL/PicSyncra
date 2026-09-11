"""Web panel manager entry point."""

import multiprocessing


if __name__ == "__main__":
    multiprocessing.freeze_support()


from picsyncra.web_manager import main


if __name__ == "__main__":
    main()
