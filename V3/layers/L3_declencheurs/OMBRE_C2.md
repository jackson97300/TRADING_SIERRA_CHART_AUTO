# BRIEF OMBRE C2 — LES DOUZE DÉCLENCHEURS, PRÊTS À CÂBLER
*À déposer : `layers/L3_declencheurs/OMBRE_C2.md`. Fable, 09/09/2026 (v2 : + famille SD1 et famille options). Pour Claude Code. Rien n'entre dans `LES_QUATRE` ; tout tourne dans `ombre_c2.py` (modèle : `ombre16.py`), journal `LOGS/entonnoir/ombre_c2_<jour>.jsonl`, jamais par la chaîne. Lecture setup par setup à N = 40 sur NQ, jamais en groupe.*

---

## 0. Règles communes — s'appliquent aux douze

- **Unités** : `dist_*` en ticks, `atr_barre` en points ; seule conversion `seuil_ticks()` (planchers P05–P20 de la SPEC L3). Toute colonne `_r` est recalculée dans `recalc.py`, jamais la colonne C++ quand elle existe en `_r`.
- **Provenance** : une colonne C++ en B n'est lue que si `test_ctx`-style l'a reproduite (mismatch = 0 sur 2 jours). Sinon elle se recalcule ou le setup attend. Proxys refusés par `lecture.py`.
- **Signal = franchissement** (`signaux_par_franchissement`), une barre 15 min à la clôture, `None` sur donnée absente (jamais de signal sur NaN).
- **Chaque setup a** : `nom`, `famille`, `side`, `lieu()`, `reaction()`, `regime()`, `cible_famille` (pour B-NAT de L5), `colonnes` (avec provenance), `attendu` (N sur 60 jours + direction attendue), `date_ombre`.
- **Journal** : une ligne par signal — `snapshot_id, ts, sym, setup, side, lieu_prix, colonnes_lues{}, regime, cible_prix` — et **une ligne par barre de lieu sans réaction** (`motif = "lieu_sans_reaction"`) : l'entonnoir `lieu → régime → réaction` doit être lisible par setup, sinon « N = 0 » ne dit pas quel étage est vide.
- **Pré-enregistrement** : `DECISIONS.md`, une ligne par setup activé : nom, date d'ombre, attendu. Lecture sur les jours ≥ `date_ombre` seulement.
- **Tests** : par setup, LONG/SHORT miroir × {lieu seul, lieu+réaction, lieu sans réaction, colonne absente → None} = 8 cas ; parité `OMBRE_C2.md` ↔ `LES_DOUZE` dans `test_spec_l3.py` ; anti-fuite (le signal à `t` ne lit rien après `t`).
- **Seuils** : dans `layers/L3_declencheurs/seuils_c2.yaml`, `null` tant que la distribution n'est pas dans `rapports/`.

---

## 1. Règle des 80 % — `C2_80PCT` (= H4) — **câbler ce soir**
- **Famille** : profil / rotation. **Régime** : B5 = ouverture hors VA veille (`open_above_prev_vah` / `open_below_prev_val`, B → recalculer depuis `open_cash_lvl` vs `prev_vah/val_lvl`, A).
- **Lieu** : le prix rentre dans la VA veille (`inside_prev_va` = 1).
- **Réaction** : **acceptation** = deux clôtures 15 min consécutives dans la VA (définition F23 ; pas le flag C++ `rule_80pct`).
- **Side** : vers l'autre bord de la VA (ouverture au-dessus → LONG… non : ouverture au-dessus, retour dedans → **SHORT** vers VAL ; miroir). **Cible** : bord opposé (`prev_val_lvl` / `prev_vah_lvl`).
- **Colonnes** : `open_cash_lvl`, `prev_vah_lvl`, `prev_val_lvl`, `inside_prev_va`, OHLC 15 min.
- **Attendu** : ouverture hors VA 30–40 % des jours, acceptation sur 40 % → N ≈ 10–15 par instrument en 60 jours ; direction : positif (Dalton Capital 1987–91, 80 % de traversée). **Code** : `h4` existe — vérifier qu'il lit l'acceptation à deux clôtures, sinon l'adapter avant de câbler.

## 2. Momentum de fin de journée — `C2_EOD` (= S-1)
- **Famille** : temps / continuation. **Régime** : aucun (c'est le point : Baltussen et al. JFE 2021, niveau A).
- **Lieu** : la barre 15h15–15h30 ET clôturée. **Réaction** : signe de `close(15h30) − open(9h30)` ; |rendement| ≥ `r_min` (null → distribution ; attendu ~0,3 ATR-jour).
- **Side** : sens du rendement de la journée. **Entrée** 15h30, **sortie 16h00 ET** — sortie horaire, pas de barrière ATR ; exception `SESSION_CLOTURE` prévue en L0 (`exceptions: [C2_EOD]`).
- **Colonnes** : OHLC 15 min, `open_cash_lvl`, calendrier (demi-séances → pas de signal).
- **Attendu** : N = 60 par instrument (un par jour) ; direction positive ; Sharpe brut attendu faible, net de frais inconnu — c'est le seul candidat qui atteint la puissance en une campagne.

## 3. Retour sur la VWAP ou sur SD1 en tendance — `C2_VWAP_RET` / `C2_SD1_RET`
*Une famille à niveau paramétré, journalisée comme DEUX setups : le niveau ∈ {`vwap_rth_r`, `vwap_rth_sd1u/d_r`}, celui des deux qui a tenu le dernier (F23). Les jours de forte tendance, le prix ne redescend pas jusqu'à la VWAP : il se cale sur la bande — c'est l'observation de Jackson. On ne fade jamais SD1 en tendance.*
- **Famille** : continuation sur niveau. **Régime** : B5 hors VA veille **ET** `vwap_slope_r` de signe stable sur 4 barres (recalculer : pente de `vwap_rth_r` sur 4 barres 15 min en ATR — la colonne C++ `vwap_slope_10/30` est B, à reproduire sinon ignorer) **ET** clôture du même côté de la VWAP depuis ≥ 3 barres.
- **Lieu** : `dist_vwap_rth_r` dans ± P10 (recalculée, A).
- **Réaction** : la barre touche la VWAP (`low ≤ vwap` pour long) et clôture au-dessus, `finish_r` > p50 (`finish_r` = (close − low)/(high − low), à ajouter à `recalc.py` — remplace `finish_delta_pct`).
- **Mémoire** : `n_tests` de la fiche F23 sur `vwap_rth` (niveau figé, hors quarantaine) journalisé avec le signal ; le rang du retour est une colonne du journal, pas un filtre.
- **Side** : sens de la tendance. **Cible** : SD1 pour le retour VWAP ; **SD2** pour le retour SD1. **Entrée** : clôture de la barre qui a tenu (pas au touché — à confirmer par Jackson).
- **Attendu** : jours de tendance 15–20 %, 1–2 retours/jour → N ≈ 20–30 par setup ; direction positive sur les retours 1–2, nulle au-delà. Attendu croisé : SD1 tient les jours d'IB large, VWAP les jours d'IB moyenne — REG le dira, lecture séparée.

## 4. Balayage ONH/ONL + regain — `C2_SWEEP_ON`
- **Famille** : piège. **Régime** : 60 premières minutes cash. **Lieu** : `high > onh` (ou `low < onl`) sur la barre — `onh/onl` A.
- **Réaction** : F23 sur le niveau ON rend `issue = regagne` (deux clôtures de retour) **et** `desequilibre_au_dela` ≥ seuil (null → p75 des cassures, par instrument).
- **Side** : contre le balayage. **Cible** : `vwap_rth_r` ou `prev_vpoc_lvl` (le plus proche).
- **Colonnes** : `onh`, `onl`, OHLC 1 min (pour le déséquilibre), F23.
- **Attendu** : N ≈ 20–25 ; direction positive si H-PIÈGE tient, nulle sinon — c'est H-PIÈGE avec un lieu.

## 5. Réparation de poor high/low — `C2_POOR`
- **Famille** : profil. **Lieu** : `ctx_poor_high` (reproduit, mismatch = 0) formé depuis ≥ 3 barres ; prix revenu à ≤ P10 du poor high.
- **Réaction** : clôture au-dessus du poor high (la réparation) avec `rvol_r` ≥ p50.
- **Side** : LONG à travers (miroir bas). **Cible** : prochain niveau figé (PDH, VAH veille, mur).
- **Colonnes** : `ctx_poor_high/low` (B reproduit), prix du poor (à journaliser depuis la barre de formation), `rvol_r`.
- **Attendu** : N ≈ 15 ; direction positive (Dalton : un poor high est « inachevé », il attire).

## 6. Divergence delta au niveau — `C2_DIV_DELTA`
- **Famille** : flux. **Lieu** : nouveau plus haut de session à ≤ P10 d'un niveau figé (`prev_vah`, `pdh`, `mq_call` — A).
- **Réaction** : `cvd_sess_r` au plus haut de la barre < `cvd_sess_r` au précédent plus haut de session (recalculé — pas `delta_div_*` C++), et clôture sous le niveau.
- **Side** : SHORT (miroir). **Cible** : `vwap_rth_r`.
- **Colonnes** : `cvd_sess_r` (fait), niveaux A, OHLC.
- **Attendu** : N ≈ 20 ; direction positive faible.

## 7. Open-drive — `C2_OPEN_DRIVE` (cycle 2, pré-enregistré seulement)
- **Lieu** : barres 9h30 et 9h45 clôturent dans le même sens, la 2ᵉ hors du range de la 1ʳᵉ, `open_cash_lvl` jamais retouché. **Réaction** : 3ᵉ barre : retrait sans retoucher l'ouverture, clôture dans le sens. **Régime** : B5 aligné. **Cible** : prochain niveau figé.
- **Prérequis** : `open_type_r` recalculé (la colonne C++ vaut 0 hors cash). **Attendu** : N ≈ 8 — ombre longue.

## 8. Absorption 1 min au niveau — `C2_ABS_1M` (= H8 corrigé, après L4 J2)
- **Lieu** : ≤ P20 d'un niveau figé (liste `NIVEAUX_H8` sans les `cur_*` avant 11h). **Réaction** : `absorption_sens` de L4 en 1 min sur la fenêtre `k` (`rvol_r ≥ 2`, `|delta_pct| ≥ 0,3`, finish contraire) — *information* L4, lue ici comme réaction. **Side** : sens de la clôture. **Cible** : niveau opposé de la VA.
- **Attendu** : plus de signaux que H8p ; direction inconnue.

## 9. Rejet au mur d'options — `C2_MUR_REJET`
- **Famille** : options / rotation. **Régime** : gamma positif lu par REG — prix au-dessus du HVL (`dist_mq_hvl`, A) : le régime où les murs *tiennent* (Barbon & Buraschi : gamma positif = réversion). Jamais `gamma_block_*` ni `mq_gamma_condition` (proxys).
- **Lieu** : ≤ P10 de `mq_call` (short) ou `mq_put` (long) — `dist_mq_call/put` A, snapshot MenthorQ **figé** jusqu'à la mise à jour de midi ; `mq_snapshot_ts` journalisé avec le signal.
- **Réaction** : F23 sur le mur rend `tenu` + `finish_r` contraire au mur ; L4 sans veto.
- **Side** : contre le mur. **Cible** : `vwap_rth_r` ou HVL, le plus proche.
- **Attendu** : lieu rare sur ES (H1 du cycle 1 : mur à 84 pts médians), plus fréquent sur NQ → N ≈ 10–20 ; direction positive en gamma positif. **Première mesure avant tout** : part des barres cash à ≤ 1 ATR d'un mur, par instrument — si c'est 2 % comme au cycle 1, #9–#11 ne se jugent pas en 60 jours, et il faut le savoir avant de câbler.

## 10. Cassure du mur acceptée en gamma négatif — `C2_MUR_CASSE`
- **Régime** : sous le HVL (gamma négatif = momentum, les dealers vendent la baisse). **Lieu** : F23 sur le mur rend `casse` (deux clôtures au-delà). **Réaction** : le retest du mur cassé tient (pas de `regagne`, clôture au-delà). **Side** : sens de la cassure. **Cible** : prochain niveau GEX (`dist_gex_nearest_up/dn`, A).
- **Attendu** : N ≈ 10 (gamma négatif ≈ 30 % des jours du lot) ; direction positive. C'est le miroir de #9 : si les deux ont le même signe au jour 61, le régime gamma ne sépare rien — lecture jointe pré-enregistrée.

## 11. Pin 0DTE en fin de séance — `C2_PIN_0DTE`
- **Régime** : jour avec niveaux 0DTE présents (`dist_mq_call/put_0dte` non nuls — absents la nuit). **Lieu** : après 14h00 ET, prix à ≤ P15 d'un mur 0DTE. **Réaction** : deux barres 15 min sans clôture au-delà du mur. **Side** : vers le mur (le prix est *aimanté*, pas repoussé). **Cible** : le mur ; sortie 16h00 comme #2.
- **Référence** : Cboe / Banque du Canada 2024 — jours 0DTE : volatilité réalisée plus basse, gamma dealer plus grand en fin de séance. Niveau B.
- **Attendu** : N ≈ 15–20 ; c'est un test de *pin*, pas de sens : « le prix finit à ≤ P10 du mur plus souvent que le hasard » (contrôle : mur tiré au sort parmi les niveaux du jour).

## 12. Trois « à tuer proprement » — `C2_GAP`, `C2_SINGLE`, `C2_MIDI` (cycle 2, pré-enregistrés)
- **Gap non comblé** : `open_gap_ticks` (A) ≥ seuil (null → p75), non comblé après 4 barres → sens du gap, cible PDH/PDL. Attendu : nul net de frais.
- **Single prints revisités** : première revisite de `single_print_mid` (provenance à établir ; sinon recalcul depuis le profil 1 min), réaction = clôture qui le traverse. Attendu : inconnu.
- **Réversion de midi** : 12h00–13h30, > 1 ATR de la VWAP, `rvol_r` < p25, première barre contraire → vers la VWAP. Attendu : nul ou négatif (niveau C, écrit pour être tué).

---

## 13. Ordre de câblage

| jour | action |
|---|---|
| ce soir | `OMBRE_C2.md` déposé ; `DECISIONS.md` : 1–6 pré-enregistrés avec date et attendu ; **#1 câblé** (h4 vérifié sur l'acceptation) |
| J+1 | `finish_r`, `vwap_slope_r` dans `recalc.py` + tests ; **#2 câblé** (spec d'une page, exception L0) |
| J+2 | reproduction `ctx_poor_*` ; **#5, #6 câblés** |
| J+2 aussi | **distribution du lieu options** (part des barres cash à ≤ 1 ATR d'un mur, ES/NQ) → décide si #9–#11 se câblent ce cycle |
| après F23 hors quarantaine (VWAP, SD1, ON, murs sont figés : pas de `cur_*`) | **#3 (les deux setups), #4, #9, #10 câblés** |
| quand la distribution du lieu 0DTE est mesurée | #11 |
| après L4 J2 | #8 |
| cycle 2 | #7, #12 |

**Ce qu'on ne fait pas** : regarder les 57 jours pour choisir lesquels « auraient marché ». Les distributions servent à poser les seuils (p50/p75 des colonnes de réaction), jamais à lire un devenir. Le P&L de ces douze n'existe nulle part avant la lecture à N = 40.

**Question ouverte à Jackson (fixe #3)** : entrée à la clôture de la barre qui a tenu la VWAP, ou au touché par ordre limite ? Par défaut : la clôture.
