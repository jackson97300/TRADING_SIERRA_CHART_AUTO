Audit de coherence du pipeline C++ DMP.

Verifie que les 4 fichiers C++ + les fichiers Python sont alignes sur le meme schema.

Etapes :
1. Lire DMP_Config.h -> extraire DMP_SCHEMA_VERSION et nombre de colonnes
2. Verifier DMP_Reader.h, DMP_Transform.h, DMP_Writer.h, DMP_Main.cpp -> meme version
3. Verifier dmp_validator.py, mia_bench.py, dataset_builder.py, labeler.py -> meme schema
4. Verifier symetrie de toute nouvelle paire de colonnes (up/dn, u/d)
5. Rapport PASS/FAIL par fichier avec lignes exactes

Ne modifie aucun fichier sans accord explicite de l'utilisateur.
