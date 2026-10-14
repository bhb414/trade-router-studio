Option Explicit

Dim shell, fileSystem, folder, executable, command
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

folder = fileSystem.GetParentFolderName(WScript.ScriptFullName)
executable = folder & "\.venv\Scripts\trade-studio.exe"

If Not fileSystem.FileExists(executable) Then
  MsgBox "Trade Router Studio is not installed in this folder.", 16, "Trade Router Studio"
  WScript.Quit 1
End If

command = Chr(34) & executable & Chr(34) & " start"
shell.Run command, 0, False
