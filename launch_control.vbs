Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = base
cmd = Chr(34) & base & "\.venv\Scripts\python.exe" & Chr(34) & " " & Chr(34) & base & "\control_panel.pyw" & Chr(34)
shell.Run cmd, 0, False
