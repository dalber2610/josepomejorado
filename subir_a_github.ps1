param(
    [Parameter(Mandatory=$false)]
    [string]$RepoUrl = "https://github.com/dalber2610/josepomejorado.git"
)

Set-Location $PSScriptRoot

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host " 🚀 SUBIENDO PROYECTO JOSEPO MEJORADO A GITHUB" -ForegroundColor Cyan
Write-Host " Repositorio: $RepoUrl" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

# Configurar remoto origin
$existingRemote = git remote | Where-Object { $_ -eq "origin" }
if ($existingRemote) {
    git remote set-url origin $RepoUrl
} else {
    git remote add origin $RepoUrl
}

# Subir rama base y rama de mejoras (feature branch para Pull Request de equipo)
Write-Host "[*] Subiendo rama base (main)..." -ForegroundColor Yellow
git push -u origin main

Write-Host "[*] Subiendo rama con todas las mejoras (feature/josepo-fases-1-a-7-produccion)..." -ForegroundColor Green
git push -u origin feature/josepo-fases-1-a-7-produccion

Write-Host "`n[OK] ¡Repositorio sincronizado con éxito en GitHub!" -ForegroundColor Green
Write-Host "👉 Ahora tus compañeros pueden ver todos los cambios en: $RepoUrl" -ForegroundColor Cyan
