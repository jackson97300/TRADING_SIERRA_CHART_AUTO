# À FAIRE — 09/09 : les deux audits Fable, consolidés

*Un seul endroit pour tout ce que les audits du 09/09 ont soulevé, pour que rien
ne tombe entre deux sessions (Jackson : « qu'on ne les oublie pas, qu'on ne
passe pas à côté »). Deux audits : la REVUE QUALITÉ (14 fichiers logique, à
`045443c`) et l'AUDIT V1-LESSONS (chaîne V3 en 12 étapes vs lanceur V1
`MIA-IA-SYSTEM-2026-`). État : ✅ fait / 📝 tracé / ⏳ passe dédiée.*

## ✅ Corrigé le 09/09 (revue qualité)
- **A2** frais → `None` jamais `False` sur ATR absent (cfb7af5)
- **C1** fail-loud sur sym inconnu, plus de défaut ES silencieux (cfb7af5)
- **A3** SPEC news alignée sur `is_news_60m` (±60 min), le −15/+30 par niveau
  = NEXT_CYCLE (391bf88 → ad25e65)
- **C3** sortie horaire PAR FAMILLE en config L5 (`seuils.yaml`) + `sortie_source`
  journalisé (repli défaut jamais silencieux) (ad25e65)

## 📝 Tracé (notes, pas de code)
- **A4** LECTURE règle 19 : le journal LIVE ne fait pas foi sur `POSITION_OUVERTE`
  jusqu'au pas 2b (défaut §0). Le rejeu 21:01 est juste.
- **B2 / C2** PLAN §7 : B-NIV exige une intention en PRIX absolus (cycle 2) ;
  TTL état 60 s + battement d'état toutes les 30 s.
- **A1** gamma : bug documenté à 3 endroits (docstring `_gamma`, INCIDENT_LOG,
  garde YAML au-dessus de `mode: observee` — ne pas promouvoir sans le fix).

## ⏳ PASSE DÉDIÉE — avant le gel SI POSSIBLE
- **#4 — LE LIEU dans la ligne PASSE** (V1-lessons #4). **PAS une colonne** :
  vérifié dans `CORE/research/hypotheses.py`, le lieu dépend de famille+sens et
  `h7` lit TROIS niveaux (ovn_low/pdl/ib_low). Exige que les fonctions
  d'hypothèse surfacent LE niveau déclencheur (nom de colonne + prix reconstruit
  `close + dist·tick` + `dist_ticks`), puis `chaine` le journalise dans
  l'entonnoir principal. Touche L3 + chaine GELÉS → review. « Si possible » (Fable) :
  colonne de journal, pas une décision — ne change pas ce que la chaîne décide.

## ⏳ PASSES DÉDIÉES — quand elles viennent
- **Passe lecture** : découper `lecture.py` (plafond 300), PUIS
  - **A1** gamma PAR SENS : `side` dans `lire` + porter `gamma_block_short`
    dans l'agrégation 15 min (ABSENTE aujourd'hui — mesuré). Porte OBSERVÉE,
    ne bloque rien, mais corrompt la lecture du jour 61 (veto mono-sens).
  - **B3** `rang_du_jour` depuis `minutes_et` (au lieu de `i`, qui suppose
    silencieusement un `df` cash commençant à 9h30 ET).
- **B1 — coûts SOURCE UNIQUE** : 4 copies (`chaine.py`, `vetos.py`,
  `hypothesis_runner` CORE, `seuils`). `chaine.py:173/189` garde le silent-fallback
  ES que C1 a tué dans `vetos` — deux politiques pour le même nombre. Règle 1 de
  METHODE, 8 jours de retard. Une source, fail-loud partout, + test `grep`
  `2.82|4.32` dans `*.py` qui échoue.
- **`triple_barriere` (CORE)** : coller la fonction + ses tests à Fable. QUATRE
  conventions qui décident TOUTES les mesures : TP+SL touchés la même barre =
  SL (conservateur) ou TP ? entrée `open(t+1)` réelle ou `close(t)` ? frais
  déduits 1× ou 2× ? expiration à la clôture de la 20e barre ou de la 19e ? Si
  UNE réponse est « TP », 60 jours de devenirs sont optimistes.

## ⏳ PAS 2b / EXEC (post-gel) — le gros morceau, cahier des charges de l'audit V1
- **Pas 2b** (câblage de l'état, après le gel) : brancher `POSITION_OUVERTE` /
  `STOP_*` / `COOLDOWN` sur `etat_<sym>.json` ; TTL 60 s + battement 30 s ;
  réconciliation au boot broker → fichier → journal (`STOP` sur divergence) ;
  `source_etat` sur chaque ligne. + les V1-lessons qui en dépendent :
  - **#1 `L0_NIVEAU_RECENT`** (anti double-tap) : niveau tradé interdit 20 min
    après un gain / 45 après une perte, depuis `etat_<sym>.json` (`dernier_trade`
    a le `snapshot_id`, il faut ajouter le PRIX). Observée.
  - **#2 `L0_STREAK`** : 3 pertes consécutives → pause 30 min. Même source. Observée.
  - **#5 snapshot du rejet L4** : L4 journalise ses `k` barres 1 min AVEC le
    verdict, pas seulement le verdict. L4 ne trace RIEN aujourd'hui.
- **Pas 3 (EXEC)** : source DTC = `BOT/dtc_connector.py` V2 (cf `EXEC_COPIE_V1.md`,
  à copier — seule étape où V1 > V3). + **#3 rotation d'état** (`pnl_jour`, streak,
  cooldown à 22:00 UTC, JAMAIS au boot). + lecture des 2 instruments EN PARALLÈLE
  (V1 `_read_all_snapshots_parallel`, un timeout par instrument).
- **Pas 4 `pourquoi.py`** : trace un `snapshot_id` de bout en bout (retenu →
  émis → exécuté → refusé pourquoi).

## ✅ Anti-patterns V1 à NE JAMAIS reprendre (déjà évités dans V3)
- **somme pondérée** (`ml_3layer`, contexte à 0,12) → V3 a le test anti-addition.
- **signal dérivé du régime** (`generate_fade_signal`) → REG autorise des
  familles, il ne déclenche rien (deux étages séparés).
- **taille dynamique + trailing stop** avant qu'une hypothèse les ait mesurés
  → non pré-enregistrés au cycle 1 ; au cycle 2 après 200 trades.
