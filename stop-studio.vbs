Option Explicit

Dim shell, fileSystem, folder, executable, stopStudio, stopRouter
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

folder = fileSystem.GetParentFolderName(WScript.ScriptFullName)
executable = folder & "\.venv\Scripts\pythonw.exe"

If Not fileSystem.FileExists(executable) Then
  MsgBox "Trade Router Studio is not installed in this folder.", 16, "Trade Router Studio"
  WScript.Quit 1
End If

stopStudio = Chr(34) & executable & Chr(34) & " -m trade_router_studio.cli stop"
stopRouter = Chr(34) & executable & Chr(34) & " -m trade_router.cli daemon stop"

shell.Run stopStudio, 0, True
shell.Run stopRouter, 0, True
