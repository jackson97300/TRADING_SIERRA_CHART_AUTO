# L5 — LE RISQUE : combien, où est le stop, où est la cible

*Spécification v1.0 — 07/09/2026. La couche qui parle d'argent était la
seule sans SPEC (revue structurelle Fable) ; EXEC lui obéira. Rien ici ne
change ce qui s'exécute pendant la campagne.*

## 1. Rôle et frontières

L5 est la seule couche qui lit le SENS du trade. Elle ne cherche pas de
setup : elle refuse une position dont le stop n'a pas de place, dont la
cible est mangée par les frais, ou qui se prend dans un mur — et elle POSE
le stop et la cible. Deux moitiés :

- **Les vetos** (`vetos.py`, existants, mesurés) : gamma (OBSERVÉE depuis le
  07/09 — entrée proxy refusée, arbitrage Jackson pendant), rvol extrême
  (`rvol_zscore`, la bascule vers `rvol_r` REFUSÉE par la mesure), part des
  frais dans le TP. Leurs seuils vivent dans `layers/L0_interrupteur/
  seuils.yaml` — une seule vérité, on ne déménage pas un fichier que la
  chaîne lit.
- **Les barrières** (ce chantier — brief : `BRIEF_NIVEAUX.md`) : où sont le
  SL et le TP. Trois par signal, calculées HORS LIGNE, comparées au jour 61.

## 2. Les trois barrières — chaque signal reçoit les trois

- **B-ATR** — la référence qui tourne : SL 1,0 ATR, TP 1,5 ATR, expiration
  20 barres (`triple_barriere()`, inchangée).
- **B-NIV** — H-L5-NIVEAUX, la règle de Jackson (V1) : le SL DERRIÈRE le
  premier niveau éligible contre le trade dans la fenêtre mesurée, PLUS le
  buffer de balayage (p75 des sweeps ≤ 15 min, par instrument — ES 20 t,
  NQ 109 t) ; le TP DEVANT le prochain niveau dans le sens, jamais derrière
  un mur, plafonné 1,5 ATR. Niveaux FIGÉS au signal (règle F23) ; `cur_*`
  exclus v1 (même quarantaine que F23) ; proxys interdits par un test. Pas
  de niveau → défaut B-ATR, avec motif.
- **B-NAT** — la sortie naturelle par famille : la cible du déclencheur,
  figée au signal (H3 : VPOC — déjà le runner ; H2p : VWAP cash ; H6p : IB
  mid ; H8p : VA opposée). Le constat 0.1 du cycle 1 enfin testé.

## 3. Le journal

`LOGS/barrieres/barrieres_<jour>.jsonl` — une ligne par signal et par
barrière, liée par `snapshot_id` : niveau (nom, prix, distance ATR), buffer,
plafonné, motif, verdict, **candidats écartés avec raison**, issue et
`pnl_atr` net. **RÈGLE : aucun `null` sans motif à côté** — un
`niveau_sl = null` avec `motif = defaut_aucun_niveau` est une information ;
un `null` seul est un bug. Écrit par un script SÉPARÉ après le rejeu de
21:01 (`campagne.py` ne bouge pas), lu par `pourquoi.py`.

## 4. La mesure et l'attendu (écrit avant)

Par instrument et par déclencheur, `stats.py`, bloc semaine, apparié,
contrôle hasard : part de vrais niveaux au SL (attendu 60-80 %) et au TP
(50-70 %) ; B-NIV touche MOINS de SL ; ses TP sont PLUS COURTS ; l'espérance
nette **inconnue — c'est la question** ; les « défaut » se comportent comme
B-ATR (contrôle interne) ; B-NAT vs B-ATR reproduit ou infirme le
constat 0.1. Trois verdicts au jour 61 : barrière du cycle 2 / reste
observée / retirée — et si elle perd, le SL trop loin et le TP trop court
se lisent SÉPARÉMENT.

## 5. Critère de scellement

1. Seuils mesurés, chaque `null` motivé (fait : `seuils.yaml`, rapport du
   07/09).
2. `barrieres.py` : trois fonctions pures, tests miroir LONG/SHORT, niveau
   figé au signal prouvé par test, anti-proxy, parité B-ATR =
   `triple_barriere()` sur 100 signaux.
3. Journal complet — aucun `null` sans motif, trois lignes par signal.
4. Test au tick : trois signaux réels lus à la main.
5. H-L5-NIVEAUX pré-enregistrée dans DECISIONS avec l'attendu §4.
