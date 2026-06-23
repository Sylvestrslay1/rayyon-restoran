# ============================================
# RAYYON RESTORAN — Avtomatik Deploy Script
# ============================================
# Ishlatish: PowerShell'da o'ng tugma -> "Run with PowerShell"

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  RAYYON RESTORAN — Deploy" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# 1. GitHub'ga kirish
Write-Host "[1/3] GitHub'ga kirishingiz kerak..." -ForegroundColor Yellow
Write-Host "      Brauzer ochiladi — GitHub'ga login qiling." -ForegroundColor Gray
Start-Sleep 2
gh auth login --web --git-protocol https

# 2. GitHub repo yaratish va push qilish
Write-Host ""
Write-Host "[2/3] GitHub'ga yuklanyapti..." -ForegroundColor Yellow
Set-Location $PSScriptRoot
gh repo create rayyon-restoran --public --source=. --remote=origin --push
Write-Host "      GitHub'ga yuklandi!" -ForegroundColor Green

# 3. Render.com'ni ochish
Write-Host ""
Write-Host "[3/3] Render.com'da deploy..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Brauzer ochiladi. Quyidagilarni bajaring:" -ForegroundColor White
Write-Host "  1. 'New Web Service' tugmasini bosing" -ForegroundColor White
Write-Host "  2. 'rayyon-restoran' repo'ni tanlang" -ForegroundColor White
Write-Host "  3. 'Deploy Web Service' tugmasini bosing" -ForegroundColor White
Write-Host "  4. 2-3 daqiqa kuting" -ForegroundColor White
Write-Host ""

# GitHub username'ni olish
$username = gh api user --jq ".login"
$repoUrl = "https://render.com/deploy?repo=https://github.com/$username/rayyon-restoran"

Start-Process "https://render.com/login"
Start-Sleep 3

Write-Host "======================================" -ForegroundColor Green
Write-Host "  Tayyor! Saytingiz manzili:" -ForegroundColor Green
Write-Host "  https://rayyon-restoran.onrender.com" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Green
Write-Host ""
Write-Host "Tugash uchun istalgan tugmani bosing..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
