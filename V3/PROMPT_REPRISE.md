# PROMPT DE REPRISE — à coller au début de la prochaine session
*Écrit le 08/09/2026 en fin de session. Se met à jour à chaque fin de session
si l'état a bougé.*

---

Tu reprends le chantier **MIA V3** — un système de trading **full rules**
(aucun ML au cycle 1), couche par couche, ES/NQ futures micros, barres 15 min.
Le dépôt est la mémoire : **rien de ce qui compte ne vit dans une
conversation.** Tu travailles sous la méthode de `V3/METHODE.md` — tu
construis, mesures, commites et publies ; tu ne scelles jamais seul ; Fable
(chat externe) relit à chaque scellement ; Jackson décide.

## 1. Lis dans cet ordre, avant toute réponse substantielle

1. `V3/METHODE.md` — les rôles, la brique en 8 étapes, les 14 règles dures.
2. `V3/STATUS.md` — l'état des briques.
3. `V3/A_FAIRE_08_09.md` — points 1-14 : les bloqueurs de revue (1-5), la
   lecture des barres de nuit (points 1-10), la quarantaine F23 (11), le récit
   (12), la carte (13), l'audit du narratif (14).
4. `V3/REPONSES_NARRATIF.md` — l'ordre en 7 étapes qui décidera si F23 devient
   une feature.
5. `V3/DECISIONS.md` + `git log --oneline -15` — ce qui est tranché.

## 2. L'état en six lignes (08/09 au soir)

- **L0 + L0-live** : scellée / mesurée (14 scénarios de faux live). **L6** : passée.
- **L1** : B1p mesurée et écartée (couverture 100 %, séparation nulle/inversée) ;
  B1n attend F23 ; H-EXT pré-enregistrée pour le jour 61.
- **F23** : fiches testées au tick, MAIS `cur_*` en quarantaine (niveaux
  dynamiques) et « piégé » sous condition de déséquilibre (l'épisode 200 538
  contrats / delta −534 était une ROTATION). `recit.py` s'auto-vérifie et
  refuse de publier sur écart.
- **L4** : J1 fait (provenance, distributions, formules héritées disqualifiées) ;
  **J2 est LA priorité** — c'est écrit au point 14 : le narratif est séduisant,
  les vetos sont arides, et c'est le narratif qui a mangé la dernière journée.
- **Campagne d'ombre** : rythme quotidien 21:01 UTC = L6 + `V3/pourquoi.py` +
  journal MANUEL. Jamais le P&L. Rollover à contrôler le 10/09.
- **BLOQUEUR JACKSON** : 3 webhooks Discord actifs dans le dépôt principal
  public (`TRADING_SIERRA_CHART_AUTO`) ; 75+ commits locaux attendent.

## 3. Le travail, dans l'ordre

1. **L4 J2** (spec : `layers/L4_orderflow/SPEC.md`, seuils mesurés dans son
   `seuils.yaml`) : bloc `l4` de `lecture.py` + test anti-fuite → `vetos.py`
   (5 vetos en SÉRIE, jamais un compte) → glissement → mesure k=1/2/3 →
   `k` dans DECISIONS.md. Prérequis à traiter en passant : `rvol_r` /
   `cvd_sess_r` dans l'agrégation ; test de reproduction des `ctx_*` (ils ne
   reproduisent PAS leur formule relue — point 4 d'A_FAIRE).
2. **Bloqueurs du tag** (revue Fable, points 1-5 d'A_FAIRE) : `campagne.yaml`
   en unités 15 min ; source news unique ; SPEC L3 gelée ; F23 dans la porte
   observée.
3. **F23 étape par étape** selon `REPONSES_NARRATIF.md` §ordre — PAS avant L4.

## 4. Les règles qu'on ne re-négocie pas (chacune a coûté)

- Série, jamais somme (`grep` anti-score dans les tests) ; `None` jamais
  `False` ; aucune mesure hors `rapports/` ; aucun nombre dans le code ;
  l'attendu écrit AVANT chaque mesure ; unité statistique déclarée (bloc
  semaine pour ce qui est hebdo) ; signe avant magnitude ; deux conventions
  avant une anomalie ; un incident écrit le jour même ; rien ne change pendant
  la campagne ; **mesurer avant d'annoncer, et qu'un autre lise**.
- Publier = `sh V3/publier.sh` (6 contrôles). Jamais de push direct.
- Le dépôt public est `github.com/jackson97300/mia-v3` (V3 seul). Le dépôt
  principal ne se pousse PAS tant que les webhooks ne sont pas révoqués.

## 5. Ce que tu fais en premier

Vérifie la collecte du jour (`scp` depuis le VPS, fichiers nommés par journée
de trading), lance `python -X utf8 V3/pourquoi.py --journal <dernier>` et
`python -X utf8 V3/layers/L0_interrupteur/test_portes.py` pour confirmer que
tout tourne — puis attaque le §3.1. Si un point de ce prompt contredit le
dépôt, **le dépôt a raison** ; corrige ce fichier.
