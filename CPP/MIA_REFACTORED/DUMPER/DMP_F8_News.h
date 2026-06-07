#pragma once
// =============================================================================
// DMP_F8_News.h  —  Batch B3 (F8) : Macro news events timing (US)
// =============================================================================
//
//  Role : Exposer 14 features autour des fenetres de news macro US :
//         - is_news_HHMM : 6 boolean event (match exact min)
//         - within_news_HHMM_5m : 6 boolean fenetre (5min apres event)
//         - mins_since_news : minutes depuis dernier event passe (DMP_INVALID si aucun)
//         - mins_to_next_news : minutes jusqu'au prochain event (DMP_INVALID si aucun)
//
//  NB : `mins_et` est utilise en INTERNE par ce helper (lu depuis r.mins_et,
//  source DMP_Reader.h:2745 R3 B3) mais N'EST PAS expose au JSONL. Decision
//  audit B3 : downstream peut recalculer mins_et depuis ts si necessaire,
//  on garde n_cols 347 -> 371 (= +24 strict en B3.A ; 5 F12 unsafe DEFER B3.B).
//
//  Audit B3 2026-06-07 : 14 features GO PORT (toutes). Le coeur de la logique
//  horaire est deja en C++ (`time_et` calcule DMP_Reader.h:2727). On expose
//  + derive. ETA 2h. Cf DOCS/AUDIT_B3_F8_F9_F12_F22.md section F8.
//
//  Tableau NEWS_TIMES_ET (heures ET, hardcode meme Python) :
//    7h15  : ICSM / Tankan / Survey du jeudi
//    7h30  : NFP / CPI / PCE / Jobless Claims
//    8h30  : Retail Sales / Durable Goods
//    8h45  : ECB rate
//    9h00  : Consumer Confidence
//    9h30  : RTH open + ISM / Pending Home Sales
//
//  Pendant Python : CORE/phase_b_plus_engine.py:708-715 +
//                   CORE/phase_b_plus_streaming.py:456-474
//
//  IMPORTANT (R2 audit) :
//    Sentinelles `-1` Python pour mins_since_news / mins_to_next_news
//    pendant 23h/24h sont REJETEES ici. On utilise DMP_INVALID. Le serializer
//    JSON le mappe en null, et LightGBM apprend correctement (pas un constant
//    -1 + pic 0-285 sur 2h15).
//
//  Date    : 2026-06-07
//  Build   : Batch B3 / Schema 3.7.20
// =============================================================================

#include "DMP_Reader.h"
#include <cmath>

// =============================================================================
// SECTION 1 — CONSTANTES NEWS_TIMES
// =============================================================================

// Tableau hardcode des 6 evenements macro en minutes depuis minuit ET.
// Aligne sur Python `NEWS_TIMES_ET` (CORE/phase_b_plus_engine.py:708).
// Tri ASC garanti -> le scan lineaire est O(1) (6 elements seulement).
constexpr int DMP_F8_NEWS_MINS_COUNT = 6;
constexpr int DMP_F8_NEWS_MINS[DMP_F8_NEWS_MINS_COUNT] = {
    7 * 60 + 15,    // 435  - news_715
    7 * 60 + 30,    // 450  - news_730
    8 * 60 + 30,    // 510  - news_830
    8 * 60 + 45,    // 525  - news_845
    9 * 60 +  0,    // 540  - news_900
    9 * 60 + 30,    // 570  - news_930 (= cash open)
};

// Fenetre "within X" : event + 5 minutes (inclusif start, exclusif end).
constexpr int DMP_F8_NEWS_WITHIN_MIN = 5;

// =============================================================================
// SECTION 2 — HELPERS
// =============================================================================

// Helper "INVALID-like" local (duplique pour eviter dep DMP_Writer).
static inline bool DMP_F8_IsInvalid(float v) {
    return (v >= FLT_MAX * 0.5f) || (v <= -FLT_MAX * 0.5f) || !std::isfinite(v);
}

// Convertit int -> float feature : si v < 0 OU sentinel -> retourne `default_val`.
// Sinon (float)v.
static inline float DMP_F8_IntToFeature(int v) {
    return (float)v;
}

// =============================================================================
// SECTION 3 — FONCTION PRINCIPALE
// =============================================================================
//
// Remplit les 14 champs F8 dans DMP_MLFeatures depuis r.mins_et (deja calcule
// par DMP_ReadAll, expose dans struct DMP_RawData via patch Reader B3).
//
// Si mins_et < 0 ou invalid (cas degenere timestamp casse) : tous les
// champs DMP_INVALID.

inline void DMP_ComputeF8_News(DMP_MLFeatures& f, const DMP_RawData& r) {
    const int mins_et = r.mins_et;

    // ─────────────────────────────────────────────────────────────────────────
    // Guard : mins_et hors plage attendue [0, 1440) -> tous DMP_INVALID.
    // ─────────────────────────────────────────────────────────────────────────
    if (mins_et < 0 || mins_et >= 24 * 60) {
        f.is_news_715      = DMP_INVALID;
        f.is_news_730      = DMP_INVALID;
        f.is_news_830      = DMP_INVALID;
        f.is_news_845      = DMP_INVALID;
        f.is_news_900      = DMP_INVALID;
        f.is_news_930      = DMP_INVALID;
        f.within_news_715_5m = DMP_INVALID;
        f.within_news_730_5m = DMP_INVALID;
        f.within_news_830_5m = DMP_INVALID;
        f.within_news_845_5m = DMP_INVALID;
        f.within_news_900_5m = DMP_INVALID;
        f.within_news_930_5m = DMP_INVALID;
        f.mins_since_news    = DMP_INVALID;
        f.mins_to_next_news  = DMP_INVALID;
        return;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURES 1-6 — is_news_HHMM : boolean event (match exact min)
    //   1 EXACTEMENT au moment ou la bar 1min ferme sur l'event,
    //   0 sinon. Pas de fenetre, c'est un point ponctuel.
    // ─────────────────────────────────────────────────────────────────────────
    f.is_news_715 = (mins_et == DMP_F8_NEWS_MINS[0]) ? 1.0f : 0.0f;
    f.is_news_730 = (mins_et == DMP_F8_NEWS_MINS[1]) ? 1.0f : 0.0f;
    f.is_news_830 = (mins_et == DMP_F8_NEWS_MINS[2]) ? 1.0f : 0.0f;
    f.is_news_845 = (mins_et == DMP_F8_NEWS_MINS[3]) ? 1.0f : 0.0f;
    f.is_news_900 = (mins_et == DMP_F8_NEWS_MINS[4]) ? 1.0f : 0.0f;
    f.is_news_930 = (mins_et == DMP_F8_NEWS_MINS[5]) ? 1.0f : 0.0f;

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURES 7-12 — within_news_HHMM_5m : boolean fenetre 5min apres event
    //   1 si mins_et in [tgt, tgt + 5), 0 sinon.
    //   Cette fenetre couvre la bar event + les 4 bars suivantes (impact
    //   pic volatilite des news macro).
    // ─────────────────────────────────────────────────────────────────────────
    f.within_news_715_5m = (mins_et >= DMP_F8_NEWS_MINS[0]
                            && mins_et < DMP_F8_NEWS_MINS[0] + DMP_F8_NEWS_WITHIN_MIN)
                           ? 1.0f : 0.0f;
    f.within_news_730_5m = (mins_et >= DMP_F8_NEWS_MINS[1]
                            && mins_et < DMP_F8_NEWS_MINS[1] + DMP_F8_NEWS_WITHIN_MIN)
                           ? 1.0f : 0.0f;
    f.within_news_830_5m = (mins_et >= DMP_F8_NEWS_MINS[2]
                            && mins_et < DMP_F8_NEWS_MINS[2] + DMP_F8_NEWS_WITHIN_MIN)
                           ? 1.0f : 0.0f;
    f.within_news_845_5m = (mins_et >= DMP_F8_NEWS_MINS[3]
                            && mins_et < DMP_F8_NEWS_MINS[3] + DMP_F8_NEWS_WITHIN_MIN)
                           ? 1.0f : 0.0f;
    f.within_news_900_5m = (mins_et >= DMP_F8_NEWS_MINS[4]
                            && mins_et < DMP_F8_NEWS_MINS[4] + DMP_F8_NEWS_WITHIN_MIN)
                           ? 1.0f : 0.0f;
    f.within_news_930_5m = (mins_et >= DMP_F8_NEWS_MINS[5]
                            && mins_et < DMP_F8_NEWS_MINS[5] + DMP_F8_NEWS_WITHIN_MIN)
                           ? 1.0f : 0.0f;

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 13 — mins_since_news : min(mins_et - n) pour n in NEWS_MINS, n <= mins_et
    //   CRITIQUE : DMP_INVALID si AUCUN event n'est passe (mins_et < 7h15 = 435).
    //   NE PAS retourner -1 (= sentinelle Python qui leak en feature degeneree).
    //
    //   Tableau trie ASC -> on prend le plus grand n <= mins_et (= dernier
    //   element verifie en arriere).
    // ─────────────────────────────────────────────────────────────────────────
    {
        int last_passed = -1;
        for (int i = DMP_F8_NEWS_MINS_COUNT - 1; i >= 0; --i) {
            if (DMP_F8_NEWS_MINS[i] <= mins_et) {
                last_passed = DMP_F8_NEWS_MINS[i];
                break;
            }
        }
        if (last_passed < 0) {
            f.mins_since_news = DMP_INVALID;   // pas d'event passe aujourd'hui
        } else {
            f.mins_since_news = DMP_F8_IntToFeature(mins_et - last_passed);
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // FEATURE 14 — mins_to_next_news : min(n - mins_et) pour n in NEWS_MINS, n > mins_et
    //   CRITIQUE : DMP_INVALID si AUCUN event futur (mins_et > 9h30 = 570).
    //
    //   Tableau trie ASC -> on prend le plus petit n > mins_et.
    //   NB : on utilise > (pas >=) car si mins_et == n exact, c'est is_news_HHMM
    //   qui fire, et mins_to_next pointe vers le SUIVANT (pas vers maintenant).
    // ─────────────────────────────────────────────────────────────────────────
    {
        int next_future = -1;
        for (int i = 0; i < DMP_F8_NEWS_MINS_COUNT; ++i) {
            if (DMP_F8_NEWS_MINS[i] > mins_et) {
                next_future = DMP_F8_NEWS_MINS[i];
                break;
            }
        }
        if (next_future < 0) {
            f.mins_to_next_news = DMP_INVALID;  // pas d'event futur aujourd'hui
        } else {
            f.mins_to_next_news = DMP_F8_IntToFeature(next_future - mins_et);
        }
    }
}

// =============================================================================
// FIN DMP_F8_News.h
// =============================================================================
