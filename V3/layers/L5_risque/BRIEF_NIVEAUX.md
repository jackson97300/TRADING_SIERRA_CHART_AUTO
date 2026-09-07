# BRIEF L5 — LA BARRIERE PAR NIVEAUX (SL derriere un niveau, TP devant)

*Ecrit par Fable sur le concept de Jackson (version 1), depose le 07/09/2026.
La campagne tourne : rien ici ne change ce qui s'execute. Tout est calcule
HORS LIGNE, journalise, et lu au jour 61.*

## Le concept, en trois phrases

- **Le SL est derriere un niveau**, pas a une distance fixe : pour le toucher,
  le marche doit conquerir quelque chose. Et derriere le niveau PLUS la
  profondeur habituelle du balayage — sinon le stop est le carburant que
  sweep + reclaim va chercher.
- **Le TP est devant le prochain niveau**, jamais derriere un mur : on ne
  demande pas au prix de traverser un obstacle pour payer.
- **Ca se mesure avant de s'appliquer** : la barriere ATR qui tourne reste la
  barriere ; celle-ci est H-L5-NIVEAUX, pre-enregistree, calculee sur chaque
  signal a cote, comparee au jour 61.

## Les trois barrieres par signal

- **B-ATR** (reference, inchangee) : SL 1,0 ATR, TP 1,5 ATR, expiration 20
  barres — `triple_barriere()` du runner.
- **B-NIV** (la regle de Jackson) : SL derriere le premier niveau eligible
  CONTRE le trade dans la fenetre mesuree + buffer de balayage ; TP devant le
  prochain niveau dans le sens, plafonne 1,5 ATR ; niveaux FIGES au signal
  (regle F23) ; proxys interdits par un test ; pas de niveau -> defaut B-ATR
  avec motif.
- **B-NAT** (la sortie naturelle par famille) : la cible du declencheur figee
  au signal — le constat 0.1 du cycle 1 teste sur les quatre.

## LA REPONSE A LA QUESTION 9 — trouvee au depot, pas choisie

`CORE/mia_sltp.py` (13/03/2026) porte la regle V1 de Jackson, avec son audit
(07/03/2026, 44 niveaux, 1 349 barres) :

    Tier 1 (score > 0,35)    GEX, SESSION HVN/LVN, EXT_EDGE, SESS_HIGH
    Tier 2 (0,20-0,35)       CUR_VAH, VWAP+-SD, PREV_VAL, SWING, OVN_HIGH
    Tier 3 (< 0,20)          VWAP_D, MQ_HVL, IB_LOW, PREV_VWAP -> PIEGES

    SL : DERRIERE un Tier 1 seul, OU 2+ Tier 2 en confluence (< 30 t) ;
         JAMAIS derriere un Tier 3 seul ; JAMAIS dans le vide.
         Buffer : 8 t NQ / 4 t ES (etendu 13/8).
    TP : premier obstacle Tier 1/2 ; NE PAS traverser un Tier 1.

Ni « le mur d'abord » ni « la VA d'abord » : un CLASSEMENT PAR SOLIDITE
MESUREE. Pour H-L5-NIVEAUX v1, la regle mecanique reste « le plus proche
eligible dans la fenetre » ; les tiers V1 informent la LISTE des candidats et
la mesure par type de niveau du rapport permettra de re-noter les tiers sur
les donnees V3 — les scores de mars sur du 1 min ne se recopient pas sur du
15 min sans mesure (regle 04/09 : jamais recopier un seuil d'un contexte a
l'autre). Jackson tranche l'ordre final ; sa V1 est le point de depart.

## Le journal

`LOGS/barrieres/barrieres_<jour>.jsonl` — une ligne par signal et par
barriere, liee par snapshot_id : niveau, distance, buffer, plafonne, motif,
candidats ecartes avec raison. REGLE : aucun null sans motif a cote.

## L'attendu, ecrit avant

B-NIV touche moins de SL ; ses TP sont plus courts ; l'esperance nette est
INCONNUE — c'est la question. Part attendue de vrais niveaux : 60-80 % au SL,
50-70 % au TP. Trois verdicts possibles au jour 61 ; si elle perd, le SL trop
loin et le TP trop court se lisent SEPAREMENT.

## Ce qui ne bouge pas

`chaine.py`, `campagne.py`, `coureur_live.py`, les declencheurs,
`config/campagne.yaml`. Le calcul quotidien des barrieres est un script
SEPARE lance apres le rejeu de 21:01 — pas une modification du rejeu.
