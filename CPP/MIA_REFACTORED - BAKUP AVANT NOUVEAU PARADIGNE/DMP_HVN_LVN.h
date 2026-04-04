#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// DMP_HVN_LVN.h  —  MIA Data Dumper G3 : Section C — HIGH/LOW VOLUME NODES
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Rôle   : Détecter programmatiquement les HVN (High Volume Nodes) et LVN
//           (Low Volume Nodes) de la session courante via VolumeAtPriceForBars.
//
//  Pourquoi pas sg17/sg18 ? Ces subgraphs sont VISUELS uniquement — confirmé
//  par scan JSON (chart_26.json sg17/sg18 = null). Aucune valeur numérique
//  n'est jamais retournée par GetStudyArrayFromChartUsingID sur ces indices.
//
//  Algorithme :
//    1. Parcourir toutes les barres depuis le début de la session RTH
//    2. Agréger volumes par prix → histogramme tick-by-tick
//    3. Calculer volume moyen sur niveaux actifs
//    4. HVN = volume > HVN_RATIO × moyenne (nœud fort, prix résiste)
//    5. LVN = volume < LVN_RATIO × moyenne (nœud faible, prix traverse vite)
//    6. Trier et retenir nearest above/below pour features ML
//
//  Performance : Calcul déclenché UNIQUEMENT sur nouvelle barre fermée.
//    Cache persistant via sc.GetPersistentFloat().
//    Recalcul toutes les DMP_HVN_RECALC_BARS barres pour ne pas saturer CPU.
//    Composite 20J/50J/100J/200J : TODO — nécessite VolumeAtPriceForBars
//    sur des milliers de barres (trop coûteux sans accès au chart composite
//    depuis un study externe). Session 1J uniquement pour l'instant.
//
//  Portée : Session courante RTH uniquement (9h30-16h00 ET).
//           Basé sur le chart hôte (même symbole que le dumper).
//
//  Auteur : MIA Trading System
//  Date   : 2026-02-28
//  Build  : G3-Unifier v1.0
//
// ═══════════════════════════════════════════════════════════════════════════════

#include "DMP_Reader.h"
#include <algorithm>   // std::sort
#include <cmath>       // std::fabs, std::isfinite

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 — CONSTANTES
// ═══════════════════════════════════════════════════════════════════════════════

// Seuils de classification HVN/LVN (ratio vs volume moyen)
constexpr float DMP_HVN_RATIO        = 1.5f;   // HVN = volume > 1.5x moyenne
constexpr float DMP_LVN_RATIO        = 0.5f;   // LVN = volume < 0.5x moyenne

// Nombre maximum de HVN/LVN stockés (par côté : above / below)
constexpr int   DMP_HVN_MAX          = 5;       // 5 HVN above + 5 below
constexpr int   DMP_LVN_MAX          = 5;       // 5 LVN above + 5 below

// Histogramme prix/volume : résolution et taille max
constexpr int   DMP_VAP_MAX_LEVELS   = 2000;    // Max niveaux de prix distincts
constexpr int   DMP_VAP_MAX_BARS     = 600;     // Barres max à scanner (session ≈ 390 min)

// Recalcul toutes les N barres (performance)
// 5 = recalcul toutes les 5 minutes sur chart 1min, acceptable
constexpr int   DMP_HVN_RECALC_BARS = 5;

// Confluence : 2 HVN/LVN séparés de moins de N ticks = confluents
constexpr float DMP_HVN_CONFLUENCE_TICKS = 4.0f;

// Index des variables persistantes (sc.GetPersistentFloat)
// IMPORTANT : sc.GetPersistentFloat est ISOLÉ PAR STUDY — aucun risque de
// collision entre le bot et le dumper (ce sont deux études différentes).
// En revanche, les index DOIVENT être cohérents entre tous les modules DMP_*
// inclus dans le même DMP_Main.cpp. Plage réservée pour DMP_HVN_LVN : 50–74.
constexpr int DMP_PERSIST_LAST_CALC_BAR  = 50;  // Barre du dernier calcul
constexpr int DMP_PERSIST_HVN_ABV_0      = 51;  // HVN above[0..4] → idx 51-55
constexpr int DMP_PERSIST_HVN_BLW_0      = 56;  // HVN below[0..4] → idx 56-60
constexpr int DMP_PERSIST_LVN_ABV_0      = 61;  // LVN above[0..4] → idx 61-65
constexpr int DMP_PERSIST_LVN_BLW_0      = 66;  // LVN below[0..4] → idx 66-70
constexpr int DMP_PERSIST_HVN_ABV_COUNT  = 71;  // Compteurs
constexpr int DMP_PERSIST_HVN_BLW_COUNT  = 72;
constexpr int DMP_PERSIST_LVN_ABV_COUNT  = 73;
constexpr int DMP_PERSIST_LVN_BLW_COUNT  = 74;

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 — STRUCTURES
// ═══════════════════════════════════════════════════════════════════════════════

// Un niveau de prix avec son volume agrégé (histogramme)
struct DMP_VAPLevel {
    float price;         // Prix en points (ex: 5850.25)
    float volume;        // Volume cumulé à ce prix sur la session
};

// Résultat du calcul HVN/LVN pour la session courante
struct DMP_HVN_LVN_Result {

    // ── HVN (High Volume Nodes) ─────────────────────────────────────────────
    // Zones où le prix stagne — obstacles potentiels pour le TP
    float hvn_above[DMP_HVN_MAX];   // HVN au-dessus du prix (trié : le plus proche en [0])
    float hvn_below[DMP_HVN_MAX];   // HVN en-dessous du prix (trié : le plus proche en [0])
    int   num_hvn_above;
    int   num_hvn_below;

    // Nearest HVN (shortcut)
    float nearest_hvn_above;        // HVN le plus proche au-dessus (ticks positifs)
    float nearest_hvn_below;        // HVN le plus proche en-dessous
    float dist_hvn_above_ticks;     // Distance en ticks (positif)
    float dist_hvn_below_ticks;     // Distance en ticks (positif)

    // ── LVN (Low Volume Nodes) ──────────────────────────────────────────────
    // Zones de faiblesse — prix traverse vite → excellent pour TP
    float lvn_above[DMP_LVN_MAX];   // LVN au-dessus du prix (trié : le plus proche en [0])
    float lvn_below[DMP_LVN_MAX];   // LVN en-dessous du prix (trié : le plus proche en [0])
    int   num_lvn_above;
    int   num_lvn_below;

    // Nearest LVN (shortcut)
    float nearest_lvn_above;        // LVN le plus proche au-dessus
    float nearest_lvn_below;        // LVN le plus proche en-dessous
    float dist_lvn_above_ticks;     // Distance en ticks (positif)
    float dist_lvn_below_ticks;     // Distance en ticks (positif)

    // ── Confluence ──────────────────────────────────────────────────────────
    // Compte les noeuds clustérises AUTOUR du nearest (above ET below combinés)
    int   hvn_confluence_count;     // Nb HVN dans +-DMP_HVN_CONFLUENCE_TICKS du nearest HVN
    int   lvn_confluence_count;     // Nb LVN dans +-DMP_HVN_CONFLUENCE_TICKS du nearest LVN

    // ── Features ML directes ───────────────────────────────────────────────
    // Compteurs globaux dans +-100 ticks (above + below confondus)
    int   session_hvn_count;        // Nb total HVN dans +-100 ticks du prix courant
    int   session_lvn_count;        // Nb total LVN dans +-100 ticks du prix courant

    // lvn_between/hvn_between : remplis par DMP_HasLVN_Between() apres calcul TP
    float lvn_between_price_tp;     // 1=LVN entre prix et TP, 0=non (feature ML)
    float hvn_between_price_tp;     // 1=HVN entre prix et TP (obstacle), 0=non

    // ── Diagnostics ────────────────────────────────────────────────────────
    int   bars_scanned;             // Barres parcourues dans l'histogramme
    int   levels_found;             // Niveaux de prix distincts dans l'histogramme
    bool  valid;                    // true si calcul réussi avec données suffisantes
    int   last_calc_bar;            // Index de barre du dernier calcul
};

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 — INIT
// ═══════════════════════════════════════════════════════════════════════════════

inline void DMP_HVN_LVN_Init(DMP_HVN_LVN_Result& r) {
    for (int i = 0; i < DMP_HVN_MAX; i++) {
        r.hvn_above[i] = DMP_INVALID;
        r.hvn_below[i] = DMP_INVALID;
    }
    for (int i = 0; i < DMP_LVN_MAX; i++) {
        r.lvn_above[i] = DMP_INVALID;
        r.lvn_below[i] = DMP_INVALID;
    }
    r.num_hvn_above = 0; r.num_hvn_below = 0;
    r.num_lvn_above = 0; r.num_lvn_below = 0;
    r.nearest_hvn_above = DMP_INVALID; r.nearest_hvn_below = DMP_INVALID;
    r.nearest_lvn_above = DMP_INVALID; r.nearest_lvn_below = DMP_INVALID;
    r.dist_hvn_above_ticks = DMP_INVALID; r.dist_hvn_below_ticks = DMP_INVALID;
    r.dist_lvn_above_ticks = DMP_INVALID; r.dist_lvn_below_ticks = DMP_INVALID;
    r.hvn_confluence_count = 0; r.lvn_confluence_count = 0;
    r.session_hvn_count = 0; r.session_lvn_count = 0;
    r.lvn_between_price_tp = 0.0f; r.hvn_between_price_tp = 0.0f;
    r.bars_scanned = 0; r.levels_found = 0;
    r.valid = false; r.last_calc_bar = -1;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 — CONSTRUCTION HISTOGRAMME via VolumeAtPriceForBars
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Parcourt les barres de la session courante et construit un histogramme
//  prix → volume cumulé. Utilise VolumeAtPriceForBars de Sierra Chart.
//
//  IMPORTANT : sc.MaintainVolumeAtPriceData = 1 DOIT être activé dans
//  le SetDefaults du study DMP_Main.cpp sinon VolumeAtPriceForBars = nullptr.
//
//  Retourne le nombre de niveaux distincts dans l'histogramme, 0 si échec.

inline int DMP_BuildSessionHistogram(
    SCStudyInterfaceRef sc,
    float  current_price,
    float  tick_size,
    DMP_VAPLevel out_levels[],   // Tableau de sortie, taille DMP_VAP_MAX_LEVELS
    int&   out_bars_scanned,
    float  hist_price[],         // Buffer prix fourni par l'appelant (DMP_VAP_MAX_LEVELS)
    float  hist_vol[]            // Buffer volume fourni par l'appelant (DMP_VAP_MAX_LEVELS)
) {
    out_bars_scanned = 0;

    // Garde-fou : VolumeAtPriceForBars disponible ?
    if (!sc.VolumeAtPriceForBars) return 0;
    if (tick_size <= 0.0f)        return 0;

    // Trouver le début de la session RTH courante
    // Remonter depuis la barre actuelle jusqu'à IsNewTradingDay
    int session_start = sc.Index;
    int max_lookback  = DMP_VAP_MAX_BARS;

    while (session_start > 0 && max_lookback > 0) {
        if (sc.IsNewTradingDay(session_start)) break;
        session_start--;
        max_lookback--;
    }
    // session_start = index de la première barre de la session

    // ── Phase 1 : Construire un histogramme compact ─────────────────────────
    // Les buffers hist_price/hist_vol sont fournis par DMP_ComputeHVN_LVN
    // (static dans la fonction maître = isolés par study instance)
    int  hist_count = 0;

    for (int b = session_start; b <= sc.Index; b++) {
        int n = sc.VolumeAtPriceForBars->GetSizeAtBarIndex(b);
        out_bars_scanned++;

        for (int k = 0; k < n; k++) {
            const s_VolumeAtPriceV2* v = nullptr;
            if (!sc.VolumeAtPriceForBars->GetVAPElementAtIndex(b, k, &v) || !v)
                continue;

            // Prix réel = PriceInTicks × TickSize
            float price = v->PriceInTicks * tick_size;
            float vol   = (float)v->Volume;

            if (!std::isfinite(price) || price <= 0.0f || vol <= 0.0f) continue;

            // Chercher si ce prix existe déjà dans l'histogramme
            // Recherche linéaire — acceptable pour MAX_LEVELS=2000 en RTH
            bool found = false;
            for (int i = 0; i < hist_count; i++) {
                // Même tick → même niveau (tolérance 0.01f pour float)
                if (std::fabs(hist_price[i] - price) < tick_size * 0.5f) {
                    hist_vol[i] += vol;
                    found = true;
                    break;
                }
            }

            if (!found && hist_count < DMP_VAP_MAX_LEVELS) {
                hist_price[hist_count] = price;
                hist_vol  [hist_count] = vol;
                hist_count++;
            }
        }
    }

    if (hist_count < 5) return 0;  // Pas assez de données

    // ── Phase 2 : Copier dans out_levels et trier par prix ─────────────────
    for (int i = 0; i < hist_count; i++) {
        out_levels[i].price  = hist_price[i];
        out_levels[i].volume = hist_vol[i];
    }

    // Tri par prix croissant — std::sort O(n log n) au lieu de bubble sort O(n²)
    // Sur 2000 éléments : ~22 000 ops au lieu de 4 000 000 → critique pour perf ACSIL
    std::sort(out_levels, out_levels + hist_count,
              [](const DMP_VAPLevel& a, const DMP_VAPLevel& b) {
                  return a.price < b.price;
              });

    return hist_count;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5 — DÉTECTION HVN / LVN depuis l'histogramme
// ═══════════════════════════════════════════════════════════════════════════════

inline void DMP_DetectFromHistogram(
    const DMP_VAPLevel levels[],
    int   level_count,
    float current_price,
    float tick_size,
    DMP_HVN_LVN_Result& r,
    float tmp_hvn_above[],   // Buffers fournis par l'appelant (DMP_VAP_MAX_LEVELS)
    float tmp_hvn_below[],
    float tmp_lvn_above[],
    float tmp_lvn_below[]
) {
    if (level_count < 5) return;

    // ── Calculer volume moyen (uniquement niveaux avec volume > 0) ──────────
    double total_vol = 0.0;
    int    active    = 0;
    for (int i = 0; i < level_count; i++) {
        if (levels[i].volume > 0.0f) {
            total_vol += levels[i].volume;
            active++;
        }
    }
    if (active == 0) return;
    float avg_vol = (float)(total_vol / active);
    if (avg_vol <= 0.0f) return;

    const float hvn_threshold = avg_vol * DMP_HVN_RATIO;   // > 1.5x = HVN
    const float lvn_threshold = avg_vol * DMP_LVN_RATIO;   // < 0.5x = LVN

    // ── Collecter HVN/LVN above et below ────────────────────────────────────
    // Buffers reçus de DMP_ComputeHVN_LVN (static dans la fonction maître)
    int cnt_hvn_above = 0, cnt_hvn_below = 0;
    int cnt_lvn_above = 0, cnt_lvn_below = 0;

    for (int i = 0; i < level_count; i++) {
        float p   = levels[i].price;
        float vol = levels[i].volume;

        if (p > current_price) {  // Au-dessus
            if (vol >= hvn_threshold && cnt_hvn_above < DMP_VAP_MAX_LEVELS)
                tmp_hvn_above[cnt_hvn_above++] = p;
            else if (vol <= lvn_threshold && vol > 0.0f && cnt_lvn_above < DMP_VAP_MAX_LEVELS)
                tmp_lvn_above[cnt_lvn_above++] = p;
        } else if (p < current_price) {  // En-dessous
            if (vol >= hvn_threshold && cnt_hvn_below < DMP_VAP_MAX_LEVELS)
                tmp_hvn_below[cnt_hvn_below++] = p;
            else if (vol <= lvn_threshold && vol > 0.0f && cnt_lvn_below < DMP_VAP_MAX_LEVELS)
                tmp_lvn_below[cnt_lvn_below++] = p;
        }
    }

    // ── Prendre les N les plus proches du prix ───────────────────────────────
    // tmp_hvn_above est déjà trié par prix croissant → les plus proches sont en [0]
    // tmp_hvn_below est trié croissant → les plus proches sont à la fin [cnt-1]

    r.num_hvn_above = std::min(cnt_hvn_above, DMP_HVN_MAX);
    for (int i = 0; i < r.num_hvn_above; i++)
        r.hvn_above[i] = tmp_hvn_above[i];   // Plus proche en premier

    r.num_hvn_below = std::min(cnt_hvn_below, DMP_HVN_MAX);
    for (int i = 0; i < r.num_hvn_below; i++)
        // On prend depuis la fin (les plus proches du prix)
        r.hvn_below[i] = tmp_hvn_below[cnt_hvn_below - 1 - i];

    r.num_lvn_above = std::min(cnt_lvn_above, DMP_LVN_MAX);
    for (int i = 0; i < r.num_lvn_above; i++)
        r.lvn_above[i] = tmp_lvn_above[i];

    r.num_lvn_below = std::min(cnt_lvn_below, DMP_LVN_MAX);
    for (int i = 0; i < r.num_lvn_below; i++)
        r.lvn_below[i] = tmp_lvn_below[cnt_lvn_below - 1 - i];

    // ── Nearest + distances ──────────────────────────────────────────────────
    if (r.num_hvn_above > 0) {
        r.nearest_hvn_above    = r.hvn_above[0];
        r.dist_hvn_above_ticks = (r.nearest_hvn_above - current_price) / tick_size;
    }
    if (r.num_hvn_below > 0) {
        r.nearest_hvn_below    = r.hvn_below[0];
        r.dist_hvn_below_ticks = (current_price - r.nearest_hvn_below) / tick_size;
    }
    if (r.num_lvn_above > 0) {
        r.nearest_lvn_above    = r.lvn_above[0];
        r.dist_lvn_above_ticks = (r.nearest_lvn_above - current_price) / tick_size;
    }
    if (r.num_lvn_below > 0) {
        r.nearest_lvn_below    = r.lvn_below[0];
        r.dist_lvn_below_ticks = (current_price - r.nearest_lvn_below) / tick_size;
    }

    // ── Confluence ───────────────────────────────────────────────────────────
    // Compte les noeuds clustérisés AUTOUR du nearest (above ET below combinés).
    // Référence = nearest_hvn_above ou nearest_hvn_below, selon lequel est valide.
    // On cherche d'autres HVN/LVN à moins de DMP_HVN_CONFLUENCE_TICKS du nearest.

    // HVN above : comparer avec nearest_hvn_above
    if (r.num_hvn_above > 0) {
        float ref = r.nearest_hvn_above;
        for (int i = 1; i < r.num_hvn_above; i++) {
            if (std::fabs(r.hvn_above[i] - ref) / tick_size <= DMP_HVN_CONFLUENCE_TICKS)
                r.hvn_confluence_count++;
        }
        // HVN below aussi : le nearest below peut être en confluence avec nearest above
        if (r.num_hvn_below > 0) {
            if (std::fabs(r.nearest_hvn_below - ref) / tick_size <= DMP_HVN_CONFLUENCE_TICKS)
                r.hvn_confluence_count++;
        }
    } else if (r.num_hvn_below > 0) {
        // Pas de HVN above — compter la confluence autour du nearest below
        float ref = r.nearest_hvn_below;
        for (int i = 1; i < r.num_hvn_below; i++) {
            if (std::fabs(r.hvn_below[i] - ref) / tick_size <= DMP_HVN_CONFLUENCE_TICKS)
                r.hvn_confluence_count++;
        }
    }

    // LVN above : idem
    if (r.num_lvn_above > 0) {
        float ref = r.nearest_lvn_above;
        for (int i = 1; i < r.num_lvn_above; i++) {
            if (std::fabs(r.lvn_above[i] - ref) / tick_size <= DMP_HVN_CONFLUENCE_TICKS)
                r.lvn_confluence_count++;
        }
        if (r.num_lvn_below > 0) {
            if (std::fabs(r.nearest_lvn_below - ref) / tick_size <= DMP_HVN_CONFLUENCE_TICKS)
                r.lvn_confluence_count++;
        }
    } else if (r.num_lvn_below > 0) {
        float ref = r.nearest_lvn_below;
        for (int i = 1; i < r.num_lvn_below; i++) {
            if (std::fabs(r.lvn_below[i] - ref) / tick_size <= DMP_HVN_CONFLUENCE_TICKS)
                r.lvn_confluence_count++;
        }
    }

    // ── Compteurs globaux session (±100 ticks) ────────────────────────────────
    // Utile comme feature ML standalone, indépendamment de above/below.
    const float zone_100t = 100.0f * tick_size;
    for (int i = 0; i < r.num_hvn_above; i++)
        if (std::fabs(r.hvn_above[i] - current_price) <= zone_100t) r.session_hvn_count++;
    for (int i = 0; i < r.num_hvn_below; i++)
        if (std::fabs(r.hvn_below[i] - current_price) <= zone_100t) r.session_hvn_count++;
    for (int i = 0; i < r.num_lvn_above; i++)
        if (std::fabs(r.lvn_above[i] - current_price) <= zone_100t) r.session_lvn_count++;
    for (int i = 0; i < r.num_lvn_below; i++)
        if (std::fabs(r.lvn_below[i] - current_price) <= zone_100t) r.session_lvn_count++;
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6 — CACHE PERSISTANT (éviter recalcul chaque tick)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Sierra Chart fournit sc.GetPersistentFloat(index) et sc.GetPersistentInt(index)
//  pour stocker des valeurs entre les appels de la fonction study.
//
//  On stocke les 5 nearest HVN/LVN above+below + les compteurs.
//  Le reste (arrays complets) est recalculé à la demande.

inline void DMP_SaveToCache(SCStudyInterfaceRef sc, const DMP_HVN_LVN_Result& r) {
    // HVN above[0..4]
    for (int i = 0; i < DMP_HVN_MAX; i++)
        sc.GetPersistentFloat(DMP_PERSIST_HVN_ABV_0 + i) =
            (i < r.num_hvn_above) ? r.hvn_above[i] : 0.0f;

    // HVN below[0..4]
    for (int i = 0; i < DMP_HVN_MAX; i++)
        sc.GetPersistentFloat(DMP_PERSIST_HVN_BLW_0 + i) =
            (i < r.num_hvn_below) ? r.hvn_below[i] : 0.0f;

    // LVN above[0..4]
    for (int i = 0; i < DMP_LVN_MAX; i++)
        sc.GetPersistentFloat(DMP_PERSIST_LVN_ABV_0 + i) =
            (i < r.num_lvn_above) ? r.lvn_above[i] : 0.0f;

    // LVN below[0..4]
    for (int i = 0; i < DMP_LVN_MAX; i++)
        sc.GetPersistentFloat(DMP_PERSIST_LVN_BLW_0 + i) =
            (i < r.num_lvn_below) ? r.lvn_below[i] : 0.0f;

    // Compteurs
    sc.GetPersistentFloat(DMP_PERSIST_HVN_ABV_COUNT) = (float)r.num_hvn_above;
    sc.GetPersistentFloat(DMP_PERSIST_HVN_BLW_COUNT) = (float)r.num_hvn_below;
    sc.GetPersistentFloat(DMP_PERSIST_LVN_ABV_COUNT) = (float)r.num_lvn_above;
    sc.GetPersistentFloat(DMP_PERSIST_LVN_BLW_COUNT) = (float)r.num_lvn_below;

    // Barre du dernier calcul
    sc.GetPersistentFloat(DMP_PERSIST_LAST_CALC_BAR) = (float)r.last_calc_bar;
}

inline void DMP_LoadFromCache(SCStudyInterfaceRef sc, float current_price,
                               float tick_size, DMP_HVN_LVN_Result& r)
{
    DMP_HVN_LVN_Init(r);

    // Clamp explicite : protège contre valeurs aberrantes après recompilation
    // (les persistants se réinitialisent à 0 normalement, mais par sécurité...)
    auto clamp_count = [](int v, int max_v) -> int {
        return (v < 0 || v > max_v) ? 0 : v;
    };
    r.num_hvn_above = clamp_count((int)sc.GetPersistentFloat(DMP_PERSIST_HVN_ABV_COUNT), DMP_HVN_MAX);
    r.num_hvn_below = clamp_count((int)sc.GetPersistentFloat(DMP_PERSIST_HVN_BLW_COUNT), DMP_HVN_MAX);
    r.num_lvn_above = clamp_count((int)sc.GetPersistentFloat(DMP_PERSIST_LVN_ABV_COUNT), DMP_LVN_MAX);
    r.num_lvn_below = clamp_count((int)sc.GetPersistentFloat(DMP_PERSIST_LVN_BLW_COUNT), DMP_LVN_MAX);

    for (int i = 0; i < r.num_hvn_above && i < DMP_HVN_MAX; i++)
        r.hvn_above[i] = sc.GetPersistentFloat(DMP_PERSIST_HVN_ABV_0 + i);
    for (int i = 0; i < r.num_hvn_below && i < DMP_HVN_MAX; i++)
        r.hvn_below[i] = sc.GetPersistentFloat(DMP_PERSIST_HVN_BLW_0 + i);
    for (int i = 0; i < r.num_lvn_above && i < DMP_LVN_MAX; i++)
        r.lvn_above[i] = sc.GetPersistentFloat(DMP_PERSIST_LVN_ABV_0 + i);
    for (int i = 0; i < r.num_lvn_below && i < DMP_LVN_MAX; i++)
        r.lvn_below[i] = sc.GetPersistentFloat(DMP_PERSIST_LVN_BLW_0 + i);

    r.last_calc_bar = (int)sc.GetPersistentFloat(DMP_PERSIST_LAST_CALC_BAR);
    r.valid = (r.num_hvn_above + r.num_hvn_below + r.num_lvn_above + r.num_lvn_below) > 0;

    // Recalculer nearest + distances depuis le cache (le prix courant peut avoir bougé)
    if (r.num_hvn_above > 0) {
        // Trouver le nearest HVN above > current_price dans le cache
        r.nearest_hvn_above    = DMP_INVALID;
        r.dist_hvn_above_ticks = DMP_INVALID;
        for (int i = 0; i < r.num_hvn_above; i++) {
            float p = r.hvn_above[i];
            if (p > current_price) {
                r.nearest_hvn_above    = p;
                r.dist_hvn_above_ticks = (p - current_price) / tick_size;
                break;  // Tableau déjà trié par prix croissant
            }
        }
    }
    if (r.num_hvn_below > 0) {
        r.nearest_hvn_below    = DMP_INVALID;
        r.dist_hvn_below_ticks = DMP_INVALID;
        for (int i = 0; i < r.num_hvn_below; i++) {
            float p = r.hvn_below[i];
            if (p < current_price) {
                r.nearest_hvn_below    = p;
                r.dist_hvn_below_ticks = (current_price - p) / tick_size;
                break;  // Tableau trié par prix décroissant (le plus proche en [0])
            }
        }
    }
    if (r.num_lvn_above > 0) {
        r.nearest_lvn_above    = DMP_INVALID;
        r.dist_lvn_above_ticks = DMP_INVALID;
        for (int i = 0; i < r.num_lvn_above; i++) {
            float p = r.lvn_above[i];
            if (p > current_price) {
                r.nearest_lvn_above    = p;
                r.dist_lvn_above_ticks = (p - current_price) / tick_size;
                break;
            }
        }
    }
    if (r.num_lvn_below > 0) {
        r.nearest_lvn_below    = DMP_INVALID;
        r.dist_lvn_below_ticks = DMP_INVALID;
        for (int i = 0; i < r.num_lvn_below; i++) {
            float p = r.lvn_below[i];
            if (p < current_price) {
                r.nearest_lvn_below    = p;
                r.dist_lvn_below_ticks = (current_price - p) / tick_size;
                break;
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 7 — FEATURE ML : LVN/HVN BETWEEN PRICE AND TARGET
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Répond à la question : "Y a-t-il un LVN/HVN entre le prix actuel et le TP ?"
//
//  lvn_between = 1 → LVN sur la route du TP → POSITIF (prix traverse vite)
//  hvn_between = 1 → HVN sur la route du TP → NÉGATIF (obstacle, prix peut s'y bloquer)
//
//  Appeler APRÈS avoir calculé le TP target.
//  direction : +1=LONG (TP au-dessus), -1=SHORT (TP en-dessous).

inline void DMP_HasLVN_Between(
    const DMP_HVN_LVN_Result& r,
    float current_price,
    float tp_target,
    int   direction,          // +1=LONG / -1=SHORT
    float tick_size,
    float& out_lvn_between,   // 0.0f ou 1.0f
    float& out_hvn_between    // 0.0f ou 1.0f
) {
    out_lvn_between = 0.0f;
    out_hvn_between = 0.0f;

    if (tp_target <= 0.0f || tick_size <= 0.0f) return;

    float range_low  = std::min(current_price, tp_target);
    float range_high = std::max(current_price, tp_target);

    // Scanner LVN above (LONG) ou below (SHORT)
    if (direction == 1) {  // LONG : TP au-dessus
        for (int i = 0; i < r.num_lvn_above && i < DMP_LVN_MAX; i++) {
            float p = r.lvn_above[i];
            if (DMP_IsValid(p) && p > range_low && p < range_high) {
                out_lvn_between = 1.0f;
                break;
            }
        }
        for (int i = 0; i < r.num_hvn_above && i < DMP_HVN_MAX; i++) {
            float p = r.hvn_above[i];
            if (DMP_IsValid(p) && p > range_low && p < range_high) {
                out_hvn_between = 1.0f;
                break;
            }
        }
    } else if (direction == -1) {  // SHORT : TP en-dessous
        for (int i = 0; i < r.num_lvn_below && i < DMP_LVN_MAX; i++) {
            float p = r.lvn_below[i];
            if (DMP_IsValid(p) && p > range_low && p < range_high) {
                out_lvn_between = 1.0f;
                break;
            }
        }
        for (int i = 0; i < r.num_hvn_below && i < DMP_HVN_MAX; i++) {
            float p = r.hvn_below[i];
            if (DMP_IsValid(p) && p > range_low && p < range_high) {
                out_hvn_between = 1.0f;
                break;
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 8 — FONCTION MAÎTRE : DMP_ComputeHVN_LVN()
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Gestion du cache + déclenchement conditionnel du calcul.
//
//  Règle de déclenchement :
//    - Seulement sur nouvelle barre FERMÉE (pas chaque tick)
//    - Seulement toutes les DMP_HVN_RECALC_BARS barres (perf)
//    - Reset du cache au début d'une nouvelle session RTH
//
//  Appeler UNE FOIS par barre dans DMP_Main.cpp, après sc.IsNewBar().

inline void DMP_ComputeHVN_LVN(
    SCStudyInterfaceRef sc,
    float current_price,
    float tick_size,
    bool  is_new_bar_closed,    // true uniquement si nouvelle barre FERMÉE
    bool  is_rth_session,
    DMP_HVN_LVN_Result& r
) {
    DMP_HVN_LVN_Init(r);

    // Vérification garde-fou : tick_size valide
    if (tick_size <= 0.0f || !std::isfinite(tick_size)) {
        tick_size = 0.25f;  // Fallback ES/NQ
    }

    // ── BUFFERS STATIQUES CENTRALISÉS ────────────────────────────────────────
    // Tous les buffers temporaires sont déclarés ICI (unique point d'entrée)
    // et passés en paramètre aux sous-fonctions.
    // Isolés par study instance car Sierra Chart exécute les études
    // séquentiellement (pas de vraie concurrence inter-études en ACSIL).
    // Avantage vs static dans les sous-fonctions : un seul jeu de buffers
    // par study, clairement délimité, sans risque de collision ES↔NQ.
    static DMP_VAPLevel s_levels     [DMP_VAP_MAX_LEVELS]; // Histogramme final
    static float        s_hist_price [DMP_VAP_MAX_LEVELS]; // Buffer prix bruts
    static float        s_hist_vol   [DMP_VAP_MAX_LEVELS]; // Buffer volumes bruts
    static float        s_hvn_above  [DMP_VAP_MAX_LEVELS]; // HVN candidats above
    static float        s_hvn_below  [DMP_VAP_MAX_LEVELS]; // HVN candidats below
    static float        s_lvn_above  [DMP_VAP_MAX_LEVELS]; // LVN candidats above
    static float        s_lvn_below  [DMP_VAP_MAX_LEVELS]; // LVN candidats below

    // ── Décision : recalcul ou lecture du cache ? ────────────────────────────
    int last_calc = (int)sc.GetPersistentFloat(DMP_PERSIST_LAST_CALC_BAR);

    // Reset cache si nouvelle session (IsNewTradingDay)
    bool new_session = (sc.Index > 0 && sc.IsNewTradingDay(sc.Index));
    if (new_session) {
        // Invalider le cache — le premier tick de session déclenchera recalcul
        sc.GetPersistentFloat(DMP_PERSIST_LAST_CALC_BAR) = -1.0f;
        last_calc = -1;
    }

    // Recalcul si :
    //  (a) Barre fermée ET
    //  (b) N barres écoulées depuis le dernier calcul OU cache invalide
    bool do_recalc = is_new_bar_closed && is_rth_session
                     && (last_calc < 0 || (sc.Index - last_calc) >= DMP_HVN_RECALC_BARS);

    if (do_recalc && sc.VolumeAtPriceForBars) {
        // ── Calcul complet ───────────────────────────────────────────────────
        int bars_scanned = 0;

        int level_count = DMP_BuildSessionHistogram(sc, current_price, tick_size,
                                                    s_levels, bars_scanned,
                                                    s_hist_price, s_hist_vol);
        r.bars_scanned = bars_scanned;
        r.levels_found = level_count;

        if (level_count >= 5) {
            DMP_DetectFromHistogram(s_levels, level_count, current_price, tick_size, r,
                                    s_hvn_above, s_hvn_below, s_lvn_above, s_lvn_below);
            r.valid         = true;
            r.last_calc_bar = sc.Index;

            // Sauvegarder dans le cache persistant
            DMP_SaveToCache(sc, r);

            // Log diagnostic (une fois par calcul)
            char msg[256];
            snprintf(msg, sizeof(msg),
                "[DMP_HVN_LVN] Recalc bar=%d | bars=%d levels=%d | "
                "HVN↑=%d HVN↓=%d LVN↑=%d LVN↓=%d | "
                "NearLVN↑=%.2f NearLVN↓=%.2f",
                sc.Index, bars_scanned, level_count,
                r.num_hvn_above, r.num_hvn_below,
                r.num_lvn_above, r.num_lvn_below,
                DMP_IsValid(r.nearest_lvn_above) ? r.nearest_lvn_above : 0.0f,
                DMP_IsValid(r.nearest_lvn_below) ? r.nearest_lvn_below : 0.0f);
            sc.AddMessageToLog(msg, 0);
        } else {
            // Pas assez de données — invalider le cache
            sc.GetPersistentFloat(DMP_PERSIST_LAST_CALC_BAR) = -1.0f;
        }

    } else if (last_calc >= 0) {
        // ── Lecture du cache avec mise à jour des distances ──────────────────
        DMP_LoadFromCache(sc, current_price, tick_size, r);
    }
    // Si last_calc < 0 ET pas de recalcul → r reste à DMP_INVALID (invalide)
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 9 — DIAGNOSTIC
// ═══════════════════════════════════════════════════════════════════════════════

inline void DMP_LogHVN_LVN(SCStudyInterfaceRef sc, const DMP_HVN_LVN_Result& r,
                             float current_price)
{
    if (!r.valid) {
        sc.AddMessageToLog("[DMP_HVN_LVN] Pas de données valides", 1);
        return;
    }

    char msg[512];
    snprintf(msg, sizeof(msg),
        "[DMP_HVN_LVN] Px=%.2f | "
        "HVN↑%.2f(%.1ft) HVN↓%.2f(%.1ft) | "
        "LVN↑%.2f(%.1ft) LVN↓%.2f(%.1ft) | "
        "HVNconf=%d LVNconf=%d | bars=%d lvl=%d",
        current_price,
        DMP_IsValid(r.nearest_hvn_above) ? r.nearest_hvn_above : 0.0f,
        DMP_IsValid(r.dist_hvn_above_ticks) ? r.dist_hvn_above_ticks : 0.0f,
        DMP_IsValid(r.nearest_hvn_below) ? r.nearest_hvn_below : 0.0f,
        DMP_IsValid(r.dist_hvn_below_ticks) ? r.dist_hvn_below_ticks : 0.0f,
        DMP_IsValid(r.nearest_lvn_above) ? r.nearest_lvn_above : 0.0f,
        DMP_IsValid(r.dist_lvn_above_ticks) ? r.dist_lvn_above_ticks : 0.0f,
        DMP_IsValid(r.nearest_lvn_below) ? r.nearest_lvn_below : 0.0f,
        DMP_IsValid(r.dist_lvn_below_ticks) ? r.dist_lvn_below_ticks : 0.0f,
        r.hvn_confluence_count, r.lvn_confluence_count,
        r.bars_scanned, r.levels_found);
    sc.AddMessageToLog(msg, 0);
}

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_HVN_LVN.h
// ═══════════════════════════════════════════════════════════════════════════════
