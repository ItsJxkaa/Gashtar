Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
' Запуск сервера FastAPI скрыто в фоне
WshShell.Run "cmd /c run_server.bat", 0, False
WScript.Sleep 2000
' Запуск Cloudflare Tunnel скрыто в фоне
WshShell.Run "cmd /c run_tunnel.bat", 0, False
