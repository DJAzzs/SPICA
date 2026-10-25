; SPICA Windows Installer (NSIS)
; Build: makensis spica.nsi
; Prereq: PyInstaller output in dist/SPICA/

!define APPNAME "SPICA"
!define VERSION "0.1.0"
!define PUBLISHER "SPICA Contributors"
!define URL "https://github.com/YOUR_USERNAME/spica"

Name "${APPNAME}"
OutFile "SPICA-${VERSION}-setup.exe"
InstallDir "$PROGRAMFILES64\${APPNAME}"
InstallDirRegKey HKLM "Software\${APPNAME}" "InstallDir"
RequestExecutionLevel admin

Page directory
Page instfiles

Section "Install"
    SetOutPath $INSTDIR
    
    ; PyInstaller 输出
    File /r "..\..\dist\SPICA\*.*"
    
    ; 前端
    File /r "..\..\web\dist\*.*" "$INSTDIR\web\dist\"
    
    ; DSH patch
    File "..\..\run\dsh-patch.yml" "$INSTDIR\run\"
    
    ; 创建快捷方式
    CreateDirectory "$SMPROGRAMS\${APPNAME}"
    CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\SPICA.exe"
    CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\SPICA.exe"
    
    ; 写注册表
    WriteRegStr HKLM "Software\${APPNAME}" "InstallDir" $INSTDIR
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" \
        "DisplayName" "${APPNAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" \
        "UninstallString" "$INSTDIR\uninstall.exe"
    
    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\*.*"
    RMDir /r "$INSTDIR"
    Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
    RMDir "$SMPROGRAMS\${APPNAME}"
    Delete "$DESKTOP\${APPNAME}.lnk"
    DeleteRegKey HKLM "Software\${APPNAME}"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"
SectionEnd
