; Instalador de Trappi Caja (Inno Setup 6). Lo arma .github/workflows/caja-windows.yml:
;   iscc /DAppVersion=1.0.0 /DSourceDir=..\build\windows\x64\runner\Release trappi_caja.iss
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\windows\x64\runner\Release"
#endif

[Setup]
AppId={{8C3E2F1A-5B7D-4E8A-9C1F-7A2B3C4D5E6F}
AppName=Trappi Caja
AppVersion={#AppVersion}
AppPublisher=Trappi
AppPublisherURL=https://trappi.com.ar
AppSupportURL=https://trappi.com.ar
DefaultDirName={autopf}\Trappi Caja
DefaultGroupName=Trappi Caja
DisableProgramGroupPage=yes
OutputDir=..\build\installer
OutputBaseFilename=trappi-caja-setup
SetupIconFile=..\windows\runner\resources\app_icon.ico
UninstallDisplayIcon={app}\trappi_caja.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"
Name: "autostart"; Description: "Abrir Trappi Caja al prender la compu"; GroupDescription: "Inicio:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Trappi Caja"; Filename: "{app}\trappi_caja.exe"
Name: "{group}\Desinstalar Trappi Caja"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Trappi Caja"; Filename: "{app}\trappi_caja.exe"; Tasks: desktopicon
Name: "{userstartup}\Trappi Caja"; Filename: "{app}\trappi_caja.exe"; Tasks: autostart

[Run]
Filename: "{app}\trappi_caja.exe"; Description: "Abrir Trappi Caja"; Flags: nowait postinstall skipifsilent
