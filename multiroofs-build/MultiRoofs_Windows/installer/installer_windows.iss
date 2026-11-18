#define MyAppName "MultiRoofs"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "MultiRoofs"
#define MyAppExeName "MultiRoofs.exe"

[Setup]
AppId={{A4948B72-9C6B-47B9-8459-E994F8D00B3F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\MultiRoofs
DefaultGroupName=MultiRoofs
OutputDir=..\installer_output
OutputBaseFilename=MultiRoofs_CityJSON_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\..\..\UI\resources\uicityjson_icon.ico
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=lowest
DisableDirPage=no
DisableProgramGroupPage=no

[Files]
Source: "..\dist\MultiRoofs\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MultiRoofs"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\MultiRoofs"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch MultiRoofs"; Flags: nowait postinstall skipifsilent
