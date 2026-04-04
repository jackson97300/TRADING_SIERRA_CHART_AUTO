---
paths:
  - "CPP/**"
---

# Regles C++ DMP

- NE PAS modifier le C++ sans audit complet (4 fichiers synchronises)
- Procedure : DMP_Reader.h → DMP_Transform.h → DMP_Writer.h → DMP_Config.h
- Incrementer DMP_SCHEMA_VERSION a chaque changement
- Deployer TOUJOURS sur les 2 dossiers VPS : ACS_Source + DUMPER
- Recompiler dans Sierra Chart (Analysis → Build Custom Studies DLL)
- Reloader Charts 30/31 apres compilation
- Ne JAMAIS deployer sur le VPS sans confirmation explicite de Jackson
