!macro customInit
  ; Kill any running JADE / Python processes before install
  nsExec::ExecToLog 'taskkill /F /IM JADE.exe /T'
  nsExec::ExecToLog 'taskkill /F /IM python.exe /T'
  nsExec::ExecToLog 'taskkill /F /IM python3.exe /T'
  Sleep 1500
!macroend
