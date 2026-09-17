$code = (Get-Clipboard)
[System.IO.File]::WriteAllText("$pwd\main.py", $code, [System.Text.Encoding]::UTF8)
git add main.py
git commit -m "Feat: Sistema completo de automatizacion y despacho de WhatsApp integrado"
git push origin main
