---
paths:
  - "CORE/**"
---

# Regles CORE (pipeline Python)

- Lancer `python -X utf8 CORE/dmp_validator.py` apres toute modification des features
- Lancer `python -X utf8 CORE/mia_bench.py DATA/ES DATA/NQ` pour le benchmark complet
- Schema actif : 3.7.2, 262 colonnes. Verifier la coherence si ajout de features
- Walk-forward OBLIGATOIRE pour le ML — JAMAIS de random split
- MenthorQ reader : si fichier JSON absent, retourne df inchange (pas de crash)
- Les colonnes mq_* sont daily (broadcast sur chaque barre) sauf mq_dist_* (dynamiques par prix)
- Features mortes connues : bar_long_dn_up, bar_long_up_dn, delta_divergence (toujours 0)
