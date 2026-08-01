!macro customUnInstall
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\uninstall\stop-installed-runtimes.ps1" -InstallRoot "$INSTDIR"'
!macroend
