# PROMPT DE REPRISE — à coller au début de la prochaine session
*Écrit le 08/09/2026 en fin de session, révisé le 08/09 après relecture Fable
(ordre du §3 inversé, constat du §5, trois points de la nuit ajoutés), puis au
soir : coureur `campagne.py` corrigé et validé (cf INCIDENT_LOG 08/09). Se met
à jour à chaque fin de session si l'état a bougé.*

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
3. `V3/A_FAIRE_08_09.md` — points 1-15 : les bloqueurs de revue (1-5, TRAITÉS
   le 08/09), la lecture des barres de nuit (points 1-10), la quarantaine F23
   (11), le récit (12), la carte (13), l'audit du narratif (14), l'audit
   direction (15 : H3+H7 contre-tendance 95-97 % les jours de tendance — le
   mode de mort de V1 ; B5 est l'antidote mesuré, H-B5TREND pré-enregistrée).
4. `V3/REPONSES_NARRATIF.md` — l'ordre en 7 étapes qui décidera si F23 devient
   une feature.
5. `V3/DECISIONS.md` + `git log --oneline -15` — ce qui est tranché.

## 2. L'état en six lignes (08/09 au soir)

- **L0 + L0-live** : scellée / mesurée (14 scénarios de faux live — un CHEMIN
  prouvé, pas un branchement : le bot n'emprunte pas encore
  `chaine.appliquer(strict=True)`). **L6** : passée.
- **L1** : B1p mesurée et écartée (couverture 100 %, séparation nulle/inversée) ;
  B1n attend F23 ; H-EXT pré-enregistrée pour le jour 61.
- **F23** : fiches testées au tick, MAIS `cur_*` en quarantaine (niveaux
  dynamiques) et « piégé » sous condition de déséquilibre (l'épisode 200 538
  contrats / delta −534 était une ROTATION). `recit.py` s'auto-vérifie et
  refuse de publier sur écart.
- **L4** : J1 fait (provenance, distributions, formules héritées disqualifiées) ;
  **J2 est LA priorité de la semaine** — c'est écrit au point 14 : le narratif
  est séduisant, les vetos sont arides, et c'est le narratif qui a mangé la
  dernière journée.
- **Campagne d'ombre** : démarrée le 08/09, **tag `campagne-ombre-1` posé**
  (bloqueurs 1-5 de la revue Fable traités le 08/09 : unités 15 min dans
  `campagne.yaml`, source news unique, défenses_du_niveau → fiches F23,
  SPEC L3 gelée, STATUS cohérent). Le coureur `V3/campagne.py` fait EXISTER
  la journée — corrigé et validé le 08/09 au soir : il court LES_QUATRE
  pré-enregistrées (pas le cycle 1), injecte `rvol_r` + bandes SD2 (chauffe
  20 j), compte par franchissement, et un journal VIDE est la preuve d'un
  jour couru muet (absent = incident). Rythme quotidien 21:01 UTC =
  `campagne.py` puis `pourquoi.py` + journal MANUEL. Jamais le P&L.
  Rollover à contrôler le 10/09.
- **BLOQUEUR JACKSON** : 3 webhooks Discord actifs dans le dépôt principal
  public ; 75+ commits locaux attendent. Troisième jour. Dix minutes.

## 3. Le travail, dans l'ordre

**OBJECTIF DE LA SEMAINE (decide par Jackson le 08/09) : tout construire EN
OBSERVATION, fige vendredi 12/09** — pour que les 60 jours d'ombre soient
homogenes. Ordre : coureur live (strict reel) -> prerequis L4 -> L4 J2 ->
scalaires F23 (prev_* seulement) -> carte + recap Discord (nouveaux webhooks,
jamais le P&L) -> pont DTC (ordres de TEST Sim, hors chaine decisionnelle) ->
tache planifiee 21:01. Apres vendredi : on n'ajoute plus, on regarde tourner.
Au jour 61 on ne « corrige » pas : on bascule observee->appliquee pour ce qui
a survecu. Branchement decisionnel Sim : cycle 2, ~mi-decembre.

0. **Le coureur LIVE** — la brique L0-live version branchée, et la réponse à
   la question 1 du constat qui reste NON : une boucle sur le fichier vivant
   avec `age_s` réel, L6 du jour et l'état du connecteur, passée à
   `chaine.appliquer(strict=True, live={...})`. Le mode `--strict` de
   `campagne.py` existe mais bloquerait tout par les trous DTC — c'est voulu
   (fail-closed), c'est le coureur qui manque. Toutes les pièces existent.
1. **L4 J2** (spec : `layers/L4_orderflow/SPEC.md`, seuils mesurés dans son
   `seuils.yaml`) : bloc `l4` de `lecture.py` + test anti-fuite → `vetos.py`
   (5 vetos en SÉRIE, jamais un compte) → glissement → mesure k=1/2/3 →
   `k` dans DECISIONS.md. Prérequis à traiter en passant, chacun avec son
   test — les trois points de la nuit qui n'en ont pas encore :
   - `rvol_r` / `cvd_sess_r` dans l'agrégation ;
   - **reproduction des `ctx_*`** sur 2 jours, mismatch = 0, comme la parité
     `direction()` (point 4 de la nuit) — sans ce test, J2 « recalcule selon
     la formule » contre une formule qu'on sait fausse ;
   - **B4 lit UNE seule colonne `im_smt`**, toujours la même (ES −1 / NQ 0 au
     même ts : elles divergent), écrite dans le `seuils.yaml` de L1 (point 5) ;
   - **`lecture.py` refuse mécaniquement** toute colonne dont la `_source`
     contient `proxy` (point 7 — `_mq_gamma_source: sierra_proxy_v2`).
2. **F23 étape par étape** selon `REPONSES_NARRATIF.md` §ordre — PAS avant L4.
3. La carte (`carte.py`, point 13) vient APRÈS L4 — le point 14 le dit : le
   narratif a déjà mangé une journée.

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

## 5. Ce que tu fais en premier — un CONSTAT, pas une vérification

Réponds d'abord à trois questions par **oui/non, avec la preuve** :

1. **Le bot a-t-il tourné aujourd'hui en `strict=True`** — c'est-à-dire en
   passant réellement par `chaine.appliquer(strict=True, live={...})` ?
   Preuve : son journal du jour, pas une lecture du code.
2. **Le fichier de la journée de trading du 08/09 est-il en local**
   (`scp` depuis le VPS, fichiers nommés par journée de trading) ?
3. **L'entonnoir du jour contient-il des lignes L0 avec `TROU_VIX` sur les
   barres de nuit** (`vix_level == 0` → TROU, jamais un régime) ?

**Si l'une est non, c'est LA tâche, avant tout le reste.** Un premier jour de
campagne sans preuve qu'il a eu lieu est un jour perdu. Si les trois sont oui :
`python -X utf8 V3/pourquoi.py --journal <dernier>` puis
`python -X utf8 V3/layers/L0_interrupteur/test_portes.py`, et attaque le §3.1.

Si un point de ce prompt contredit le dépôt, **le dépôt a raison** ; corrige ce
fichier.
