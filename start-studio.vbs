Option Explicit

Dim shell, fileSystem, folder, launcher, command
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

folder = fileSystem.GetParentFolderName(WScript.ScriptFullName)
launcher = folder & "\start-studio.cmd"

If Not fileSystem.FileExists(launcher) Then
  MsgBox "Trade Router Studio is not installed in this folder.", 16, "Trade Router Studio"
  WScript.Quit 1
End If

command = Chr(34) & launcher & Chr(34)
shell.Run command, 1, False
