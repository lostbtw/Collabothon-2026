import sys

from .main import run

sys.exit(run(sys.argv[1:]) or 0)
