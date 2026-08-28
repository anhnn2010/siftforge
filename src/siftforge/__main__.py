"""Allow `python -m siftforge` to invoke the SiftForge CLI."""

from siftforge.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
