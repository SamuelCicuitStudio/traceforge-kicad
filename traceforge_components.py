"""KiCad schematic tool entry point. Does not require a running PCB editor."""

from signal_path_analyzer.schematic_components import main

if __name__ == "__main__":
    raise SystemExit(main())
