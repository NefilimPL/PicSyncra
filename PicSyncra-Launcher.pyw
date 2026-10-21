"""Stable installed launcher, intentionally independent of application modules."""
if __name__ == '__main__':
    from picsyncra.installation.module_launcher import main
    raise SystemExit(main())
