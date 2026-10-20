"""python -m orbit_editor           -> window
python -m orbit_editor <comando> -> command-line tool (see cli.py)"""
import sys

if len(sys.argv) > 1:
    from .cli import main
    sys.exit(main())
else:
    from .gui import main
    main()
