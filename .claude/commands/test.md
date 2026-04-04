Lance la suite de tests automatiques MIA.

Exécute `python CORE/test_all.py` depuis la racine du projet.

Options :
- `--quick` pour les tests rapides (10s)
- Sans argument pour tous les tests (pipeline complet, ~60s)
- `--module menthorq` pour un module spécifique

Les tests vérifient :
1. Imports de tous les modules Python
2. DMP Reader (schema, colonnes critiques)
3. IB Recalc (cohérence buy+sell=total, delta=buy-sell)
4. Rolling Features (ctx_*)
5. Game Changers (parité C++ 105/105)
6. MenthorQ Reader (unités, gamma, distances, proxy vs futures)
7. FPBS (colonnes VAP, ask_pct [0,1], bar_duration)
8. Pipeline complet (DmpReader → IB → Rolling → Intermarket)

Si un test échoue, NE PAS déployer. Corriger d'abord.
