Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.Run Chr(34) & ".venv\Scripts\python.exe" & Chr(34) & " " & Chr(34) & "机器人控制台.pyw" & Chr(34), 0, False
