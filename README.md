# Running from the source

If you don't want to install this tool and you prefer running the source code, you can follow the following steps:

1. Create a virtual Python environment (assuming you have already installed Python)

```{bash}
   python -m venv venv
```

2. Activate the virtual Python environment (in Linux `source \venv\bin\activate`)

```{bash}
   \venv\Scripts\activate
```

2. Install requirements (only the first time)

```{bash}
   pip install -r requirements.txt
```

3. Run the source code

```{bash}
   python main.py
```


# Build the MultiRoofs executables

This guide shows how to turn the MultiRoofs CityJSON generator (a Python/PyQt6 application) into
a standalone application for Windows and Linux. The result runs on computers that do not have
Python or any Python packages installed.

The build is intended to be runned with one command per operating system and the script does the
rest. Build each version on its own operating system (the Windows version on Windows, the Linux
version on Linux).

The workflow is:

1. Install the prerequisites (first time only).
2. Run the build script. PyInstaller creates the application in `dist/MultiRoofs`.
3. Test the application.
4. Optionally, package it for distribution: a Windows installer (`MultiRoofsSetup.exe`) or a Linux
   AppImage (`MultiRoofs-x86_64.AppImage`).

## What you need

- The `multiRoofs-build` folder, which contains the source code and all build files (listed in
  [What is in the build folder](#what-is-in-the-build-folder)).
- Python 3 on the build computer.
- **Windows only:** Inno Setup 6, if you want to create an installer.
- **Linux only:** an Ubuntu computer with `sudo` rights, and optionally appimagetool if you want
  to create an AppImage.

End users only need the result of the build. They do not need Python, PyInstaller, Inno Setup or
appimagetool.

```{note}
Do not forget to add the software version in .\multiroofs-build\MultiRoofs_Windows\installer\installer_windows.iss
and in the DialogAbout.py script.
```

## Build on Windows

### Step 1: Install the prerequisites (first time only)

1. Install Python 3.11 or superior from [python.org](https://www.python.org/downloads/). To check that it is
   installed, open **Command Prompt** (search for `cmd` in the Start menu) and run:

```
   py -3 --version
```

2. If you want to create an installer, install
   [Inno Setup 6](https://jrsoftware.org/isdl.php) with the default options. The build script
   finds it automatically in its standard location
   (`C:\Program Files (x86)\Inno Setup 6\ISCC.exe`).

### Step 2: Go to the build folder

In Command Prompt, go to the folder `multiroofs_build`, for example:

```
   cd C:\Your\User\Path\YourName\UIcityJSON\multiRoofs_build\MultiRoofs_Windows
```

### Step 3: Run the build

```
   build_windows.bat
```

The script:

1. Checks that all required source, interface and build files are present. If any are
   missing, it lists them and stops.
   ```{note}
	If a new file is added to the folder UI, this has to be verified as well in `build_windows.bat`
	```
2. Creates a Python virtual environment in `venv` (only if the project already hasn't one) and installs the
   dependencies listed in `requirements.txt`.
3. Runs PyInstaller with `multiroof.spec` to create `dist\MultiRoofs\MultiRoofs.exe` and the auxiliar folder.
4. If Inno Setup is installed, builds the installer with `installer\installer_windows.iss`.
   If it is not installed, the script reports that only the executable was created.

If a step fails, the script stops and prints which step failed. A successful run ends with
`SUCCESS` and the paths of the application and the installer.

```{warning}
Each run deletes the `build`, `dist` and `installer_output` folders before building. Copy any
previous build you want to keep to another location first.
```

### Step 4: Test the application

Start the application by opening the executable `MultiRoofs.exe` located in:

```
   .\dist\MultiRoofs\MultiRoofs.exe
```

```{warning}
`MultiRoofs.exe` only works together with the other files in the `dist\MultiRoofs` folder. Do not
copy the `.exe` on its own. To share the application without an installer, share the whole
`dist\MultiRoofs` folder.
```

### Step 5: Get the installer

If Inno Setup is installed, the installer is created at:

```
   installer_output\MultiRoofs_CityJSON_Setup.exe
```

This single file is what you give to users. It installs MultiRoofs and all its supporting files.

```{note}
`MultiRoofs.exe` is the application. `MultiRoofs_CityJSON_Setup.exe` is the installer for that application.
Inno Setup is not needed to create or run `MultiRoofs.exe`; it is only needed to create the
installer.
```

## Build on Linux

These instructions are written for Ubuntu 24.04.5 LTS.

### Step 1: Install the prerequisites (first time only)

Open a **Terminal** and run:

```
   sudo apt update
   sudo apt install -y python3 python3-venv python3-pip libgl1 libegl1
```

When `sudo` asks for a password, type your user password and press Enter. Nothing is shown while
you type. These packages provide Python, virtual environments, pip, and the graphics libraries
that PyQt6 needs.

### Step 2: Go to the build folder and make the scripts executable

The build files are in `multiroofs-build/MultiRoofs_Linux` inside the project. Go to that folder,
replacing the path with the location of your copy of the project:

```
   cd ~/path/to/UIcityJSON/multiroofs-build/MultiRoofs_Linux
   chmod +x build_linux.sh AppRun install_multiroofs.sh
```

The `chmod` command is only needed the first time.

```{warning}
Do not move the `MultiRoofs_Linux` folder out of the project. The build script looks for
`main.py`, `requirements.txt` and the `UI` folder two levels above it.
```

### Step 3: Run the build

```
   ./build_linux.sh
```

The script:

1. Checks that all required source, interface and build files are present. If any are
   missing, it lists them and stops.
2. Creates a Python virtual environment in `MultiRoofs_Linux/venv` (only the first time) and
   installs the dependencies listed in the project's `requirements.txt`.
3. Runs PyInstaller with `multiroofs_linux.spec` to create `dist/MultiRoofs/MultiRoofs`.
4. Creates a release package, `release/MultiRoofs-linux-x86_64.tar.gz`, containing the
   application, the installer and the icon.
5. Prepares a `MultiRoofs.AppDir` folder and, if appimagetool is available, creates an
   AppImage (Step 6).

If a step fails, the script stops and prints an error. When it finishes, you should see messages
similar to:

```
   Build complete! The results are available in: .../dist
   PyInstaller application created: .../dist/MultiRoofs/MultiRoofs
   Release package created: .../release/MultiRoofs-linux-x86_64.tar.gz
```

```{warning}
Each run deletes the `build`, `dist`, `release` and `MultiRoofs.AppDir` folders before
building. Copy any previous build you want to keep to another location first.
```

### Step 4: Test the application

```
   ./dist/MultiRoofs/MultiRoofs
```

The tools's UI should open. Check that the icon and interface are displayed, that the
file-selection dialogs work, and that a MultiRoofs workflow can be started. To start it again
later, run the same command from the `MultiRoofs_Linux` folder; there is no need to rebuild.

```{note}
The `MultiRoofs` executable only works together with the other files in `dist/MultiRoofs`.
To share the application, use the release package (Step 5) or the AppImage (Step 6), not the
executable on its own.
```

You do not need to rebuild every time you want to use MultiRoofs. After a restart, just run the
command above from the `MultiRoofs_Linux` folder. Rebuild only after changing the source code,
the interface files or the resources.

### Step 5: Share and install the application

The file to share with users is:

```
   release/MultiRoofs-linux-x86_64.tar.gz
```

Users extract it and run the installer from the extracted folder:

```
   tar -xzf MultiRoofs-linux-x86_64.tar.gz
   cd MultiRoofs-linux-x86_64
   ./install_multiroofs.sh
```

By default, MultiRoofs is installed for the current user only, and no root privileges are needed.
To install it for all users of the computer, use `sudo` and `--system` instead:

```
   sudo ./install_multiroofs.sh --system
```

| | User installation (default) | System installation |
|---|---|---|
| Root needed | No | Yes |
| Application files | `~/.local/share/multiroofs` | `/opt/multiroofs` |
| Command | `~/.local/bin/multiroofs` | `/usr/local/bin/multiroofs` |
| Menu entry | `~/.local/share/applications` | `/usr/local/share/applications` |

After installation, MultiRoofs appears in the application menu and can also be started from a
terminal with `multiroofs`. Running the installer again updates an existing installation.

To uninstall, run the installer with `--uninstall` (and `sudo ... --system --uninstall` for a
system installation):

```
   ./install_multiroofs.sh --uninstall
```

```{note}
If the `multiroofs` command is not found right after a user installation, log out and back in.
Ubuntu adds `~/.local/bin` to the `PATH` at login once the folder exists. The menu entry works
immediately.
```

### Step 6 (optional): Create an AppImage

An AppImage packs the application into a single file that runs without installation.

1. Download `appimagetool-x86_64.AppImage` from the
   [appimagetool releases page](https://github.com/AppImage/appimagetool/releases) and save it in
   the `MultiRoofs_Linux` folder.
2. Make it executable and run the build again:

```
   chmod +x appimagetool-x86_64.AppImage
   ./build_linux.sh
```

3. Test the result, which is created in the `MultiRoofs_Linux` folder:

```
   chmod +x MultiRoofs-x86_64.AppImage
   ./MultiRoofs-x86_64.AppImage
```

The AppImage should behave exactly like the version in `dist/MultiRoofs`.

```{note}
If appimagetool is missing, the script reports that the AppImage was not created. This does not
mean the build failed: the application in `dist/MultiRoofs` and the release package are still
created.
```

```{note}
Some AppImages need FUSE 2, which Ubuntu 24.04 does not install by default. If appimagetool or
the MultiRoofs AppImage fails with a FUSE error, either install it with
`sudo apt install libfuse2t64`, or run the AppImage without FUSE by adding
`--appimage-extract-and-run`, for example `./MultiRoofs-x86_64.AppImage --appimage-extract-and-run`.
The release package from Step 5 does not need FUSE.
```

## Rebuilding after changes

If you change the source code, the interface files or the icons, run the build script again
(`build_windows.bat` or `./build_linux.sh`). The prerequisites do not need to be reinstalled.

## Reference

### What is in the build folder

| File or folder | Used on | Purpose |
|---|---|---|
| `main.py` | Both | Entry point of the MultiRoofs application. |
| `UI/` | Both | Qt Designer interface files and About-dialog logos. |
| `icons/` | Both | Application icon (`MultiRoofs.ico` for Windows, `MultiRoofs.png` for Linux). |
| `requirements-build.txt` | Both | Python dependencies installed during the build, including PyInstaller. |
| `build_windows.bat` | Windows | Entry point. Starts `build_windows.ps1` with the required PowerShell settings. |
| `build_windows.ps1` | Windows | Main build script: checks files, creates the virtual environment, installs dependencies, runs PyInstaller, checks the executable, finds Inno Setup and builds the installer. |
| `multiroof.spec` | Windows | PyInstaller configuration: entry point, resources, icon, executable name, GUI mode, one-folder output. |
| `installer/installer_windows.iss` | Windows | Inno Setup configuration: install location, shortcuts, icon, files, administrator rights, compression, installer name. |
| `build_linux.sh` | Linux | Main build script: checks files, creates the virtual environment, installs dependencies, runs PyInstaller, prepares the AppDir and optionally creates the AppImage. |
| `multiroof_linux.spec` | Linux | PyInstaller configuration for Linux. |
| `AppRun` | Linux | Launcher placed in `MultiRoofs.AppDir`. Starts `usr/bin/MultiRoofs/MultiRoofs`. |
| `multiroof.desktop` | Linux | Desktop entry: application name, executable, icon, terminal behaviour, categories. |

### Resources included in the application

Besides the Python code, both spec files package these resources so the application works on
another computer:

- `UI/mainWindow.ui`, `UI/dialogSettings.ui`, `UI/dialogAbout.ui`
- `UI/resources/logo_interreg.png`, `UI/resources/logo_ulb.png`, `UI/resources/logo_mlg.png`
- `icons/MultiRoofs.ico` (Windows) or `icons/MultiRoofs.png` (Linux)

If you add a new interface file or image, add it to both spec files as well.

### Tools and versions

| Tool | Version | Role |
|---|---|---|
| PyQt6 | >= 6.7, < 7 | GUI framework of MultiRoofs. |
| tomlkit | >= 0.12, < 1 | Reads and writes the TOML configuration files. |
| PyInstaller | >= 6.10, < 7 | Packages the code, Python runtime, libraries and resources into an application. |
| Inno Setup | 6 | Creates the Windows installer (Windows only, optional). |
| appimagetool | any | Creates the Linux AppImage (Linux only, optional). |