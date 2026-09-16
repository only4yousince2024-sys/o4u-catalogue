' Runs sync.bat silently (no console window). Used by the "O4U Sync" scheduled task.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\CLAUDE PROJECTS\ONLY 4 YOU"
sh.Run "cmd.exe /c """"D:\CLAUDE PROJECTS\ONLY 4 YOU\sync.bat"" /auto""", 0, False
