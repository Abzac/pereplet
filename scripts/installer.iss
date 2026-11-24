#ifndef PackageDir
  #error PackageDir must point to the verified portable directory
#endif
#ifndef AppVersion
  #error AppVersion is required
#endif
[Setup]
AppId={{70A64597-5707-4D5B-85DA-6D78433AB87E}
AppName=Переплёт
AppVersion={#AppVersion}
AppPublisher=Переплёт
DefaultDirName={localappdata}\Programs\Pereplet
DefaultGroupName=Переплёт
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
DisableDirPage=no
WizardStyle=modern
SetupIconFile={#PackageDir}\app-icon.ico
UninstallDisplayIcon={app}\Pereplet.exe
Compression=lzma2/normal
SolidCompression=yes
OutputBaseFilename=Pereplet-Setup-Windows-x64
CloseApplications=yes
RestartApplications=no
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Переплёт"; Filename: "{app}\Pereplet.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Переплёт"; Filename: "{app}\Pereplet.exe"; WorkingDir: "{app}"; Tasks: desktopicon
[Run]
Filename: "{app}\Pereplet.exe"; Description: "{cm:LaunchProgram,Переплёт}"; Flags: nowait postinstall skipifsilent
; No UninstallDelete: user-created data is intentionally retained.
