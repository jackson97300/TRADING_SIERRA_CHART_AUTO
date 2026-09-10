@echo off
rem L'ecrivain SCENARIOS, detache, sans fenetre (pythonw), console dans LOGS\scenarios_console.log.
rem Lancement manuel ou par la tache « V3 scenarios » au demarrage ; le garde le relance s'il meurt.
rem Chemins relatifs a ce fichier : aucun chemin de machine ici.
cd /d "%~dp0..\.."
start "" /b pythonw -X utf8 -u V3\scenarios\boucle.py >> LOGS\scenarios_console.log 2>&1
