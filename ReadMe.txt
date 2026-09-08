The code creates a simple graphical interface for generating LoD 2.2 CityJSON building models with Roofer

## Requirements
- Python 3.11+
- PyQt6
- tomlkit
- Roofer executable

Install: pip install PyQt6 tomlkit

Run:  python main.py

## Key behavior

* The GUI provides a simple interface for generating LoD 2.2 CityJSON building models with Roofer.
* Users can select one or multiple `.las` / `.laz` point-cloud files.
* Alternatively, users can select a folder containing `.las` / `.laz` point-cloud files. The folder is checked to ensure it contains only supported point-cloud files.
* One `.gpkg` building-footprint file is selected for each reconstruction.
* Users select an output folder where the generated results will be stored.
* An optional Roofer TOML configuration file can be loaded and used for advanced reconstruction settings.
* The path to the Roofer executable can be configured through the application settings.
* Clicking Generate validates the selected inputs and starts Roofer in the background.
* Roofer's processing messages and errors are displayed directly in the GUI, so a terminal is not required for normal use.
* Each reconstruction is stored in a new timestamped run folder, preventing previous results from being overwritten.
* Generated CityJSON / CityJSONSequence files are displayed in the Generated files section.
* Clicking a generated file reveals it in the operating system's file manager.
* Generated models can be prepared for visualization using CityJSON Ninja.
* Processing messages can be copied or saved as a log file.
* A running Roofer reconstruction can be stopped from the GUI.
* The application remembers previously selected paths and settings between sessions.
* When a TOML configuration is updated through the GUI, the original configuration is protected with a `.bak` backup.
* Multiple `[[pointclouds]]` groups in a TOML configuration are preserved rather than being flattened or rewritten by the GUI.
