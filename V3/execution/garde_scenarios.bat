@echo off
rem Le garde de l'ecrivain SCENARIOS — a planifier toutes les 5 minutes :
rem   schtasks /create /tn "V3 garde scenarios" /sc minute /mo 5 /tr "<racine du depot>\V3\execution\garde_scenarios.bat"
rem Chemins relatifs a ce fichier : aucun chemin de machine ici.
cd /d "%~dp0..\.."
python -X utf8 V3\execution\garde_scenarios.py >> LOGS\garde_scenarios.log 2>&1
