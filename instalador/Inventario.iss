; Instalador de Windows (Inno Setup 6). Se compila desde GitHub Actions: flujo «Instalador».
; Instala por usuario (sin pedir permisos de administrador). La base de datos, los respaldos y las
; fotos viven en %LOCALAPPDATA%\Inventario, así que actualizar o desinstalar no los borra.

#ifndef VersionApp
  #define VersionApp "0.0.0"
#endif

[Setup]
AppId={{6F1D0B6E-3E5B-4C58-9B7A-2D4A7C1E9A10}
AppName=Sistema de Inventario y Ventas
AppVersion={#VersionApp}
AppPublisher=Inventario
DefaultDirName={autopf}\Inventario
DefaultGroupName=Inventario
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\salida
OutputBaseFilename=Instalador-Inventario
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Sistema de Inventario y Ventas

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "iconoescritorio"; Description: "Crear un icono en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\Inventario\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{localappdata}\Inventario"

[Icons]
Name: "{autoprograms}\Inventario"; Filename: "{app}\Inventario.exe"
Name: "{autoprograms}\Inventario - carpeta de datos y respaldos"; Filename: "{localappdata}\Inventario"
Name: "{autodesktop}\Inventario"; Filename: "{app}\Inventario.exe"; Tasks: iconoescritorio

[Run]
Filename: "{app}\Inventario.exe"; Description: "Abrir Inventario ahora"; Flags: nowait postinstall skipifsilent
