#ifndef AppVersion
  #error Pass AppVersion from pyproject.toml via Build-Windows.ps1
#endif

[Setup]
AppId={{B37C254F-4FA3-4D66-8A05-5165F94169A0}
AppName=Wordcel
AppMutex=Local\wordcel
AppVersion={#AppVersion}
AppPublisher=Wordcel contributors
AppPublisherURL=https://github.com/namidanokisetsu/wordcel
DefaultDirName={localappdata}\Programs\wordcel
PrivilegesRequired=lowest
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=wordcel-{#AppVersion}-windows-x64-setup
SetupIconFile=..\src\wordcel\resources\icon.ico
UninstallDisplayIcon={app}\wordcel.exe
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=wordcel.exe,wordcel-cli.exe

[Files]
Source: "..\dist\wordcel\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Tasks]
Name: "desktopicon"; Description: "Desktop shortcut"; Flags: unchecked

[Icons]
Name: "{autoprograms}\Wordcel"; Filename: "{app}\wordcel.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Wordcel"; Filename: "{app}\wordcel.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\wordcel.exe"; Description: "Open Wordcel"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "wordcel"; Flags: uninsdeletevalue

[Code]
var
  RemoveUserData: Boolean;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Cleaned: Boolean;
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    RemoveUserData := ExpandConstant('{param:REMOVEUSERDATA|0}') = '1';
    if (not RemoveUserData) and (not UninstallSilent) then
      RemoveUserData := SuppressibleMsgBox(
        'Remove settings, language profiles, and downloaded data?' + #13#10 +
        'Dictionaries and models in Wordcel''s data folder will be deleted.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
  end;
  if (CurUninstallStep = usPostUninstall) and RemoveUserData then
  begin
    Cleaned := True;
    if RegKeyExists(HKCU, 'Software\wordcel') then
      Cleaned := RegDeleteKeyIncludingSubkeys(HKCU, 'Software\wordcel');
    DataDir := ExpandConstant('{localappdata}\wordcel');
    if DirExists(DataDir) then
      if not DelTree(DataDir, True, True, True) then Cleaned := False;
    DataDir := ExpandConstant('{userappdata}\wordcel');
    if DirExists(DataDir) then
      if not DelTree(DataDir, True, True, True) then Cleaned := False;
    if not Cleaned then
      SuppressibleMsgBox('Some Wordcel data could not be removed. Close Wordcel and remove the remaining data before reinstalling.',
        mbError, MB_OK, IDOK);
  end;
end;
