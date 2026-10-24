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
AppVersion=0.9.01024
VersionInfoVersion=0.9.1024.0
VersionInfoTextVersion=0.9.01024
VersionInfoProductVersion=0.9.1024.0
VersionInfoProductTextVersion=0.9.01024
AppPublisher=Corporium
DefaultDirName={localappdata}\Programs\Corporium
DisableDirPage=no
DefaultGroupName=Corporium
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\release
OutputBaseFilename=Corporium-0.9.01024-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Corporium.exe
SetupIconFile=Corporium.ico
CloseApplications=yes
AppMutex=Local\CorporiumDesktop
SetupLogging=yes
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
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
[Run]
Filename: "{app}\Corporium.exe"; Description: "Launch Corporium"; Flags: nowait postinstall skipifsilent
[Code]
var
  LicenseAccepted: Boolean;
  LicenseLink: TNewButton;
  LicenseNotice: TNewStaticText;
  LicenseDocuments: TNewComboBox;
  LicenseText: TNewMemo;

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
    RaiseException('无法读取许可文件：' + Name);
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
    Viewer.Caption := 'Corporium · 许可说明';
    LicenseDocuments := TNewComboBox.Create(Viewer);
    LicenseDocuments.Parent := Viewer;
    LicenseDocuments.SetBounds(ScaleX(12), ScaleY(12), Viewer.ClientWidth - ScaleX(24), ScaleY(24));
    LicenseDocuments.Style := csDropDownList;
    LicenseDocuments.Items.Add('Corporium 使用许可');
    LicenseDocuments.Items.Add('Microsoft WebView2 许可全文');
    LicenseDocuments.Items.Add('第三方组件与隐私说明');
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
    CloseButton.Caption := '关闭';
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
    Log('未接受许可，安装已停止。静默部署须先阅读随包许可，再显式指定 /ACCEPTLICENSES=1。');
end;

procedure InitializeWizard;
begin
  { Reuse Ready to Install: no license page and no extra checkbox. }
  WizardForm.ReadyMemo.Height := WizardForm.ReadyMemo.Height - ScaleY(64);
  WizardForm.ReadyMemo.WordWrap := True;
  WizardForm.ReadyMemo.ScrollBars := ssVertical;
  LicenseNotice := TNewStaticText.Create(WizardForm);
  LicenseNotice.Parent := WizardForm.ReadyPage;
  LicenseNotice.SetBounds(WizardForm.ReadyMemo.Left, WizardForm.ReadyMemo.Top + WizardForm.ReadyMemo.Height + ScaleY(8), WizardForm.ReadyMemo.Width, ScaleY(24));
  LicenseNotice.Caption := '点击“同意并安装”即表示接受 Corporium 与 WebView2 的许可。';
  LicenseNotice.WordWrap := True;
  LicenseLink := TNewButton.Create(WizardForm);
  LicenseLink.Parent := WizardForm.ReadyPage;
  LicenseLink.SetBounds(WizardForm.ReadyMemo.Left, LicenseNotice.Top + ScaleY(26), ScaleX(135), ScaleY(26));
  LicenseLink.Caption := '查看许可说明';
  LicenseLink.OnClick := @ViewLicenses;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpReady then
    WizardForm.NextButton.Caption := '同意并安装';
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := LicenseContents(0) + NewLine + NewLine +
    'Windows 桌面界面使用 Microsoft WebView2；缺少时将安装随包运行库。' + NewLine +
    'WebView2 包括 SmartScreen，按微软隐私声明收集并向微软发送相关信息。' + NewLine +
    '许可全文及隐私链接可点下方查看，安装后仍可在“管理 → 关于与许可”中阅读。' +
    NewLine + NewLine + MemoDirInfo + NewLine + NewLine + MemoGroupInfo + NewLine + MemoTasksInfo;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  if CurPageID = wpReady then begin
    LicenseAccepted := True;
    Log('用户点击“同意并安装”，接受本发行包所附 Corporium 与 WebView2 许可。');
  end;
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if LicenseAccepted then Result := ''
  else Result := '请先阅读许可说明，并点击“同意并安装”。';
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
    RaiseException('未接受许可，安装已停止。');
  if (CurStep = ssPostInstall) and NeedsWebView then begin
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code) then
      RaiseException('WebView2 installation could not start. Run this installer again.');
    if NeedsWebView then
      RaiseException('WebView2 installation did not complete. Restart Windows and run this installer again. Code: ' + IntToStr(Code));
  end;
end;
