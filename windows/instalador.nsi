; Instalador do Grupos TS3 (Windows) - instalar / atualizar / corrigir / desinstalar
Unicode true
!define NOME "Grupos TS3"
!define VERSAO "1.2"
!include "senha.nsh"   ; define SENHA (arquivo fora do GitHub)
!define REG "Software\Microsoft\Windows\CurrentVersion\Uninstall\GruposTS3"

!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!include "WordFunc.nsh"
!insertmacro VersionCompare

Name "${NOME}"
OutFile "Instalar-Grupos-TS3.exe"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "Frost - ${NOME} ${VERSAO}"

!define MUI_ICON "assets\app.ico"
!define MUI_UNICON "assets\app.ico"
!define MUI_ABORTWARNING
!define MUI_BGCOLOR "05030B"
!define MUI_TEXTCOLOR "F6F1FF"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "assets\header.bmp"
!define MUI_HEADERIMAGE_RIGHT
!define MUI_WELCOMEFINISHPAGE_BITMAP "assets\side.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "assets\side.bmp"
!define MUI_WELCOMEPAGE_TITLE "Grupos TS3 ${VERSAO}"
!define MUI_WELCOMEPAGE_TEXT "Painel para setar grupos (tags) do TeamSpeak 3 rapidamente.$\r$\n$\r$\nExclusivo Frost. Clique em Avançar para continuar."
!define MUI_FINISHPAGE_RUN "$INSTDIR\python\pythonw.exe"
!define MUI_FINISHPAGE_RUN_FUNCTION AbreApp
!define MUI_FINISHPAGE_RUN_TEXT "Abrir o ${NOME} agora"
!define MUI_FINISHPAGE_TEXT "Tudo certo.$\r$\n$\r$\nNa primeira vez, o app pede a API key: no TeamSpeak vá em Preferências > Suplementos > Plug-ins > ClientQuery > Configurações."

Var SenhaBox
Var Instalado   ; 0 = nao instalado, 1 = instalado, 2 = registrado mas com arquivos faltando
Var VerInst
Var Cmp         ; 0 igual, 1 instalada MAIS NOVA, 2 instalada mais antiga
Var Modo        ; instalar | atualizar | reparar | limpo | desinstalar
Var RadA
Var RadB
Var RadC
Var RadD
Var OpA
Var OpB
Var OpC
Var OpD

Function AbreApp
  Exec '"$INSTDIR\python\pythonw.exe" "$INSTDIR\app\server.py"'
FunctionEnd

Function .onInit
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\${NOME}"
  StrCpy $Instalado 0
  StrCpy $Modo "instalar"
  ReadRegStr $0 HKCU "Software\GruposTS3" "Dir"
  ReadRegStr $VerInst HKCU "Software\GruposTS3" "Versao"
  ${If} $0 != ""
    StrCpy $INSTDIR $0
    ${If} ${FileExists} "$INSTDIR\app\server.py"
      StrCpy $Instalado 1
    ${Else}
      StrCpy $Instalado 2
    ${EndIf}
  ${EndIf}
  ${If} $VerInst == ""
    StrCpy $VerInst "1.0"   ; versoes antigas nao gravavam a versao
  ${EndIf}
  ${VersionCompare} "$VerInst" "${VERSAO}" $Cmp
FunctionEnd

!insertmacro MUI_PAGE_WELCOME
Page custom PaginaSenha SaiSenha
Page custom PaginaModo SaiModo
!define MUI_PAGE_CUSTOMFUNCTION_PRE PreDiretorio
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

; ---------------- senha ----------------
Function PaginaSenha
  !insertmacro MUI_HEADER_TEXT "Senha de instalação" "Digite a senha para liberar a instalação."
  nsDialogs::Create 1018
  Pop $0
  ${NSD_CreateLabel} 0 10u 100% 12u "Senha:"
  Pop $0
  ${NSD_CreatePassword} 0 24u 100% 14u ""
  Pop $SenhaBox
  ${NSD_CreateLabel} 0 46u 100% 24u "Esta instalação é protegida. Sem a senha correta não é possível continuar."
  Pop $0
  SetCtlColors $0 "8878AD" "transparent"
  nsDialogs::Show
FunctionEnd

Function SaiSenha
  ${NSD_GetText} $SenhaBox $0
  StrCmpS $0 "${SENHA}" ok
  MessageBox MB_ICONSTOP|MB_OK "Senha incorreta."
  Abort
  ok:
FunctionEnd

; ---------------- escolha: atualizar / corrigir / ... ----------------
Function PaginaModo
  ${If} $Instalado == 0
    Abort   ; primeira instalacao: segue direto
  ${EndIf}

  !insertmacro MUI_HEADER_TEXT "O ${NOME} já está instalado" "Escolha o que fazer."
  nsDialogs::Create 1018
  Pop $0

  ; texto de situacao
  ${If} $Instalado == 2
    ${NSD_CreateLabel} 0 0 100% 24u "A instalação anterior está incompleta (arquivos faltando).$\r$\nRecomendo reparar."
  ${ElseIf} $Cmp == 2
    ${NSD_CreateLabel} 0 0 100% 24u "Versão instalada: $VerInst     Versão deste instalador: ${VERSAO}$\r$\nHá uma versão mais nova disponível."
  ${ElseIf} $Cmp == 0
    ${NSD_CreateLabel} 0 0 100% 24u "Versão instalada: $VerInst  -  já está atualizado.$\r$\nSe algo não está funcionando, use Corrigir erros."
  ${Else}
    ${NSD_CreateLabel} 0 0 100% 24u "Versão instalada: $VerInst     Versão deste instalador: ${VERSAO}$\r$\nA versão instalada é MAIS NOVA que este instalador."
  ${EndIf}
  Pop $0

  ; monta as opcoes conforme a situacao
  StrCpy $OpC ""
  StrCpy $OpD ""
  ${If} $Instalado == 2
    StrCpy $OpA "reparar"
    StrCpy $OpB "desinstalar"
    ${NSD_CreateFirstRadioButton} 0 34u 100% 12u "Reparar (reinstalar os arquivos)  - recomendado"
    Pop $RadA
    ${NSD_CreateAdditionalRadioButton} 0 50u 100% 12u "Desinstalar"
    Pop $RadB
  ${ElseIf} $Cmp == 2
    StrCpy $OpA "atualizar"
    StrCpy $OpB "reparar"
    StrCpy $OpC "limpo"
    StrCpy $OpD "desinstalar"
    ${NSD_CreateFirstRadioButton} 0 34u 100% 12u "Atualizar para a versão ${VERSAO}  - recomendado (mantém API key e presets)"
    Pop $RadA
    ${NSD_CreateAdditionalRadioButton} 0 50u 100% 12u "Corrigir erros (reinstala tudo e limpa o cache)"
    Pop $RadB
    ${NSD_CreateAdditionalRadioButton} 0 66u 100% 12u "Reinstalar do zero (apaga também API key e presets)"
    Pop $RadC
    ${NSD_CreateAdditionalRadioButton} 0 82u 100% 12u "Desinstalar"
    Pop $RadD
  ${ElseIf} $Cmp == 0
    StrCpy $OpA "reparar"
    StrCpy $OpB "limpo"
    StrCpy $OpC "desinstalar"
    ${NSD_CreateFirstRadioButton} 0 34u 100% 12u "Corrigir erros (reinstala tudo e limpa o cache)  - recomendado"
    Pop $RadA
    ${NSD_CreateAdditionalRadioButton} 0 50u 100% 12u "Reinstalar do zero (apaga também API key e presets)"
    Pop $RadB
    ${NSD_CreateAdditionalRadioButton} 0 66u 100% 12u "Desinstalar"
    Pop $RadC
  ${Else}
    StrCpy $OpA "atualizar"
    StrCpy $OpB "reparar"
    StrCpy $OpC "desinstalar"
    ${NSD_CreateFirstRadioButton} 0 34u 100% 12u "Voltar para a versão ${VERSAO}  (a instalada é mais nova)"
    Pop $RadA
    ${NSD_CreateAdditionalRadioButton} 0 50u 100% 12u "Corrigir erros da versão instalada ($VerInst)"
    Pop $RadB
    ${NSD_CreateAdditionalRadioButton} 0 66u 100% 12u "Desinstalar"
    Pop $RadC
  ${EndIf}
  ${NSD_Check} $RadA

  GetDlgItem $0 $HWNDPARENT 1
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Continuar"
  nsDialogs::Show
FunctionEnd

Function SaiModo
  StrCpy $Modo $OpA
  ${NSD_GetState} $RadB $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $Modo $OpB
  ${EndIf}
  ${If} $OpC != ""
    ${NSD_GetState} $RadC $0
    ${If} $0 == ${BST_CHECKED}
      StrCpy $Modo $OpC
    ${EndIf}
  ${EndIf}
  ${If} $OpD != ""
    ${NSD_GetState} $RadD $0
    ${If} $0 == ${BST_CHECKED}
      StrCpy $Modo $OpD
    ${EndIf}
  ${EndIf}

  ${If} $Modo == "limpo"
    MessageBox MB_ICONEXCLAMATION|MB_YESNO "Isso apaga a API key e os presets salvos. Continuar?" IDYES +2
    Abort
  ${EndIf}

  ${If} $Modo == "desinstalar"
    MessageBox MB_ICONQUESTION|MB_YESNO "Desinstalar o ${NOME}?" IDYES +2
    Abort
    Call FechaApp
    ExecWait '"$INSTDIR\Desinstalar.exe" /S _?=$INSTDIR'
    Delete "$INSTDIR\Desinstalar.exe"
    RMDir "$INSTDIR"
    MessageBox MB_ICONINFORMATION|MB_OK "${NOME} desinstalado."
    Quit
  ${EndIf}
FunctionEnd

Function PreDiretorio
  ${If} $Instalado != 0
    Abort   ; ja instalado: mantem a pasta
  ${EndIf}
FunctionEnd

; pede para o app fechar (para os arquivos nao ficarem travados)
Function FechaApp
  nsExec::Exec 'powershell -NoProfile -WindowStyle Hidden -Command "try{Invoke-WebRequest -Uri http://127.0.0.1:8765/api/quit -Method POST -Body {} -UseBasicParsing -TimeoutSec 3}catch{}"'
  Pop $0
  Sleep 1500
FunctionEnd

; ---------------- instalacao ----------------
Section "Instalar"
  ${If} $Instalado != 0
    Call FechaApp
  ${EndIf}

  ; reparar / do zero: limpa os arquivos antes de copiar de novo
  ${If} $Modo == "reparar"
  ${OrIf} $Modo == "limpo"
    RMDir /r "$INSTDIR\python"
    RMDir /r "$INSTDIR\app"
    Delete "$APPDATA\GruposTS3\perms.json"
    RMDir /r "$APPDATA\GruposTS3\current"   ; descarta atualização baixada (volta ao pacote instalado)
    RMDir /r "$APPDATA\GruposTS3\janela"
  ${EndIf}
  ${If} $Modo == "limpo"
    RMDir /r "$APPDATA\GruposTS3"
  ${EndIf}
  ${If} $Modo == "atualizar"
    RMDir /r "$INSTDIR\app"
    RMDir /r "$APPDATA\GruposTS3\current"
  ${EndIf}

  SetOutPath "$INSTDIR\python"
  File /r "build\python\*.*"
  SetOutPath "$INSTDIR\app"
  File "..\server.py"
  File "..\index.html"
  File "..\skin-frost.jpg"
  File "..\icon.png"
  File "..\updater.py"
  File "..\version.txt"
  SetOutPath "$INSTDIR"
  File "assets\app.ico"
  WriteUninstaller "$INSTDIR\Desinstalar.exe"

  CreateDirectory "$SMPROGRAMS\${NOME}"
  CreateShortcut "$SMPROGRAMS\${NOME}\${NOME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\app\server.py"' "$INSTDIR\app.ico" 0
  CreateShortcut "$SMPROGRAMS\${NOME}\Desinstalar.lnk" "$INSTDIR\Desinstalar.exe"
  CreateShortcut "$DESKTOP\${NOME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\app\server.py"' "$INSTDIR\app.ico" 0

  WriteRegStr HKCU "Software\GruposTS3" "Dir" "$INSTDIR"
  WriteRegStr HKCU "Software\GruposTS3" "Versao" "${VERSAO}"
  WriteRegStr HKCU "${REG}" "DisplayName" "${NOME}"
  WriteRegStr HKCU "${REG}" "DisplayVersion" "${VERSAO}"
  WriteRegStr HKCU "${REG}" "DisplayIcon" "$INSTDIR\app.ico"
  WriteRegStr HKCU "${REG}" "Publisher" "Frost"
  WriteRegStr HKCU "${REG}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegDWORD HKCU "${REG}" "NoModify" 1
SectionEnd

Section "Uninstall"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\app.ico"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\${NOME}.lnk"
  RMDir /r "$SMPROGRAMS\${NOME}"
  DeleteRegKey HKCU "${REG}"
  DeleteRegKey HKCU "Software\GruposTS3"
  ; a pasta %APPDATA%\GruposTS3 (API key e presets) e mantida de proposito
SectionEnd
