; Inno Setup script for Refract on Windows (built by build_windows.ps1, which
; passes /DAppVersion=... /DSourceDir=<PyInstaller folder> /DIconFile=... /DLicenseDir=...).
;
; File association (PLAN phase 7): Refract adds itself to the "Open with" list
; of .prism and .pzfx (OpenWithProgids, Applications\Refract.exe\SupportedTypes)
; and never writes the extensions' default value, so the application that opens
; them by default (Prism, if installed) stays the default. Per-user install by
; default (no administrator rights needed); the keys go under HKCU or HKLM
; to match.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1B2A47-3C1E-4B8E-9E57-5A1D2C7E9F30}
AppName=Refract
AppVersion={#AppVersion}
AppPublisher=The Refract authors
AppCopyright=Copyright (C) 2026 the Refract authors
DefaultDirName={autopf}\Refract
DefaultGroupName=Refract
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=Refract-{#AppVersion}-windows-x64-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\Refract.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
InfoBeforeFile={#LicenseDir}\NOTICE.txt
ChangesAssociations=yes

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#LicenseDir}\*"; DestDir: "{app}\LICENSES"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Refract"; Filename: "{app}\Refract.exe"
Name: "{autodesktop}\Refract"; Filename: "{app}\Refract.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Registry]
; the program identifier Refract opens these files with
Root: HKA; Subkey: "Software\Classes\Refract.Project"; ValueType: string; ValueName: ""; ValueData: "Refract project"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Refract.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Refract.exe,0"
Root: HKA; Subkey: "Software\Classes\Refract.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Refract.exe"" ""%1"""
; listed under "Open with" only: a value in OpenWithProgids, never the extension's default
Root: HKA; Subkey: "Software\Classes\.prism\OpenWithProgids"; ValueType: string; ValueName: "Refract.Project"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.pzfx\OpenWithProgids"; ValueType: string; ValueName: "Refract.Project"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\Refract.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "Refract"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\Refract.exe\SupportedTypes"; ValueType: string; ValueName: ".prism"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Refract.exe\SupportedTypes"; ValueType: string; ValueName: ".pzfx"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Refract.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Refract.exe"" ""%1"""

[Run]
Filename: "{app}\Refract.exe"; Description: "{cm:LaunchProgram,Refract}"; Flags: nowait postinstall skipifsilent
