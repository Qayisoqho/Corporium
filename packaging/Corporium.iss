#ifndef AppSource
  #define AppSource "..\release\app\Corporium"
#endif
#ifndef WebViewInstaller
  #define WebViewInstaller "..\build-tools\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
#endif
#ifndef LegalDir
  #define LegalDir "licenses"
#endif
[Setup]
AppId={{D06731DF-0CEC-448C-A02A-77BB3684C3F0}
AppName=Corporium
AppVersion=0.9.01026.4
VersionInfoVersion=0.9.1026.4
VersionInfoTextVersion=0.9.01026.4
VersionInfoProductVersion=0.9.1026.4
VersionInfoProductTextVersion=0.9.01026.4
AppPublisher=Corporium
DefaultDirName={localappdata}\Programs\Corporium
DisableDirPage=no
DefaultGroupName=Corporium
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\release
OutputBaseFilename=Corporium-0.9.01026.4-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Corporium.exe
SetupIconFile=Corporium.ico
CloseApplications=yes
AppMutex=Local\CorporiumDesktop
SetupLogging=yes
#include "installer-messages.iss"

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebViewInstaller}"; DestDir: "{tmp}"; Flags: deleteafterinstall nocompression; Check: NeedsWebView
Source: "{#LegalDir}\Corporium-LICENSE.txt"; Flags: dontcopy
Source: "{#LegalDir}\Microsoft-WebView2-Runtime-LICENSE.txt"; Flags: dontcopy
Source: "{#LegalDir}\THIRD-PARTY-NOTICES.txt"; Flags: dontcopy
[Icons]
Name: "{group}\Corporium"; Filename: "{app}\Corporium.exe"
Name: "{autodesktop}\Corporium"; Filename: "{app}\Corporium.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "{cm:DesktopShortcut}"; Flags: unchecked
[Run]
Filename: "{app}\Corporium.exe"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent
[Code]
var
  LicenseAccepted: Boolean;
  LicenseLink: TNewButton;
  LicenseNotice: TNewStaticText;
  LicenseDocuments: TNewComboBox;
  LicenseText: TNewMemo;
  NextLeft, NextWidth, BackLeft: Integer;

function LicenseFileName(Index: Integer): String;
begin
  case Index of
    1: Result := 'Microsoft-WebView2-Runtime-LICENSE.txt';
    2: Result := 'THIRD-PARTY-NOTICES.txt';
  else
    Result := 'Corporium-LICENSE.txt';
  end;
end;

function LicenseContents(Index: Integer): String;
var
  Name: String;
  Content: AnsiString;
begin
  Name := LicenseFileName(Index);
  ExtractTemporaryFile(Name);
  if not LoadStringFromFile(ExpandConstant('{tmp}\') + Name, Content) then
    RaiseException(FmtMessage(CustomMessage('LicenseReadError'),[Name]));
  Result := UTF8Decode(Content);
  { Windows memo controls require CRLF; keep source notices byte-for-byte intact. }
  StringChangeEx(Result, #13#10, #10, True);
  StringChangeEx(Result, #10, #13#10, True);
end;

procedure LicenseDocumentChanged(Sender: TObject);
begin
  LicenseText.Text := LicenseContents(LicenseDocuments.ItemIndex);
  LicenseText.SelStart := 0;
end;

procedure ViewLicenses(Sender: TObject);
var
  Viewer: TSetupForm;
  CloseButton: TNewButton;
begin
  Viewer := CreateCustomForm(ScaleX(620), ScaleY(440), False, False);
  try
    Viewer.Caption := CustomMessage('LicenseTitle');
    LicenseDocuments := TNewComboBox.Create(Viewer);
    LicenseDocuments.Parent := Viewer;
    LicenseDocuments.SetBounds(ScaleX(12), ScaleY(12), Viewer.ClientWidth - ScaleX(24), ScaleY(24));
    LicenseDocuments.Style := csDropDownList;
    LicenseDocuments.Items.Add(CustomMessage('AppLicense'));
    LicenseDocuments.Items.Add(CustomMessage('RuntimeLicense'));
    LicenseDocuments.Items.Add(CustomMessage('ThirdParty'));
    LicenseDocuments.ItemIndex := 0;
    LicenseDocuments.OnChange := @LicenseDocumentChanged;
    LicenseText := TNewMemo.Create(Viewer);
    LicenseText.Parent := Viewer;
    LicenseText.SetBounds(ScaleX(12), ScaleY(46), Viewer.ClientWidth - ScaleX(24), Viewer.ClientHeight - ScaleY(96));
    LicenseText.ReadOnly := True;
    LicenseText.WordWrap := True;
    LicenseText.ScrollBars := ssVertical;
    LicenseText.Anchors := [akLeft, akTop, akRight, akBottom];
    CloseButton := TNewButton.Create(Viewer);
    CloseButton.Parent := Viewer;
    CloseButton.SetBounds(Viewer.ClientWidth - ScaleX(92), Viewer.ClientHeight - ScaleY(38), ScaleX(80), ScaleY(26));
    CloseButton.Caption := CustomMessage('Close');
    CloseButton.Cancel := True;
    CloseButton.ModalResult := mrCancel;
    LicenseDocumentChanged(LicenseDocuments);
    Viewer.ShowModal;
  finally
    Viewer.Free;
  end;
end;

function InitializeSetup: Boolean;
begin
  LicenseAccepted := WizardSilent and (ExpandConstant('{param:ACCEPTLICENSES|0}') = '1');
  Result := (not WizardSilent) or LicenseAccepted;
  if not Result then
    Log(CustomMessage('SilentLicenseStopped'));
end;

procedure InitializeWizard;
begin
  { Reuse Ready to Install: no license page and no extra checkbox. }
  NextLeft := WizardForm.NextButton.Left;
  NextWidth := WizardForm.NextButton.Width;
  BackLeft := WizardForm.BackButton.Left;
  WizardForm.ReadyMemo.Height := WizardForm.ReadyMemo.Height - ScaleY(78);
  WizardForm.ReadyMemo.WordWrap := True;
  WizardForm.ReadyMemo.ScrollBars := ssVertical;
  LicenseNotice := TNewStaticText.Create(WizardForm);
  LicenseNotice.Parent := WizardForm.ReadyPage;
  LicenseNotice.SetBounds(WizardForm.ReadyMemo.Left, WizardForm.ReadyMemo.Top + WizardForm.ReadyMemo.Height + ScaleY(8), WizardForm.ReadyMemo.Width, ScaleY(32));
  LicenseNotice.Caption := CustomMessage('AcceptanceNotice');
  LicenseNotice.WordWrap := True;
  LicenseLink := TNewButton.Create(WizardForm);
  LicenseLink.Parent := WizardForm.ReadyPage;
  LicenseLink.SetBounds(WizardForm.ReadyMemo.Left, LicenseNotice.Top + ScaleY(36), ScaleX(135), ScaleY(26));
  LicenseLink.Caption := CustomMessage('ReadLicenses');
  LicenseLink.OnClick := @ViewLicenses;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  WizardForm.NextButton.Left := NextLeft;
  WizardForm.NextButton.Width := NextWidth;
  WizardForm.BackButton.Left := BackLeft;
  if CurPageID = wpReady then begin
    WizardForm.NextButton.Width := ScaleX(125);
    WizardForm.NextButton.Left := NextLeft + NextWidth - WizardForm.NextButton.Width;
    WizardForm.BackButton.Left := BackLeft - (WizardForm.NextButton.Width - NextWidth);
    WizardForm.NextButton.Caption := CustomMessage('AgreeInstall');
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := LicenseContents(0) + NewLine + NewLine +
    CustomMessage('RuntimeNotice') + NewLine +
    CustomMessage('PrivacyNotice') + NewLine +
    CustomMessage('ReadAfterInstall') +
    NewLine + NewLine + MemoDirInfo + NewLine + NewLine + MemoGroupInfo + NewLine + MemoTasksInfo;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  if CurPageID = wpReady then begin
    LicenseAccepted := True;
    Log(CustomMessage('LicenseAcceptedLog'));
  end;
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if LicenseAccepted then Result := ''
  else Result := CustomMessage('LicenseRequired');
end;

function NeedsWebView: Boolean;
var Version: String;
begin
  Result := not (RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
  if Result then
    Result := not (RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;
procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer;
begin
  if (CurStep = ssInstall) and not LicenseAccepted then
    RaiseException(CustomMessage('LicenseStopped'));
  if (CurStep = ssPostInstall) and NeedsWebView then begin
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code) then
      RaiseException(CustomMessage('WebViewStartError'));
    if NeedsWebView then
      RaiseException(FmtMessage(CustomMessage('WebViewFinishError'),[IntToStr(Code)]));
  end;
end;
