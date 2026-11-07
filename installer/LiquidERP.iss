; Instalator LiquidERP (Inno Setup 6). Budowanie: build.bat – podaje numer wersji z version.py.
; Deinstalacja usuwa program, ale NIE usuwa danych użytkownika z %AppData%\LiquidERP.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; Folder z wynikiem PyInstallera (podfolder LiquidERP); build.bat może podać inny przez /DDistDir=...
#ifndef DistDir
  #define DistDir "..\dist"
#endif
#define AppName "LiquidERP"
#define AppExe "LiquidERP.exe"
#define AppUrl "https://github.com/arqs112-debug/liquiderp-app"

[Setup]
AppId={{6C1D7E0A-2F4B-4C8E-9B1A-5A7E3D2F9C41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Instalacja dla bieżącego użytkownika bez uprawnień administratora (można zmienić w oknie instalatora).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#DistDir}
OutputBaseFilename=LiquidERP-Setup-{#AppVersion}
SetupIconFile=..\static\liquiderp.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
CloseApplications=yes
; Program sam uruchamia się po aktualizacji z programu ([Run] z /restart=1), więc bez drugiego uruchomienia.
RestartApplications=no

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#DistDir}\LiquidERP\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Odinstaluj {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; Aktualizacja z programu (cicha instalacja z /restart=1): uruchom nową wersję jako zwykły użytkownik.
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: RestartRequested

[UninstallDelete]
; Tylko pliki tymczasowe programu w folderze instalacji – dane w %AppData%\LiquidERP zostają.
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
function RestartRequested: Boolean;
begin
  Result := ExpandConstant('{param:restart|0}') = '1';
end;

[Messages]
polish.UninstalledAll=Program %1 został usunięty.%n%nTwoje dane (baza, kopie zapasowe) zostały w folderze AppData\Roaming\LiquidERP – usuń go ręcznie, jeśli nie są już potrzebne.
