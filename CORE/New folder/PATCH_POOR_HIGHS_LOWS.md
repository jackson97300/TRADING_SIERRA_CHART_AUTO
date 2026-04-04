# POOR HIGHS / LOWS — Guide d'implémentation
# 15/03/2026 — Market Profile avancé
#
# 3 fichiers à modifier:
#   1. DMP_Reader.h     ← FAIT (livré)
#   2. DMP_Transform.h  ← Patch ci-dessous
#   3. DMP_Main.cpp     ← Patch ci-dessous

# ═══════════════════════════════════════════════════════════════════════
# CONCEPT
# ═══════════════════════════════════════════════════════════════════════
#
# Poor High = le haut du profil session n'a PAS de "tail" (excess).
# Seulement 1-2 barres ont touché les 5 ticks du session high.
# → Le marché n'a pas fini son auction → continuation LONG probable.
#
# Poor Low = le bas du profil session n'a PAS de "tail".
# → Continuation SHORT probable.
#
# Dalton/Steidlmayer: "The market will always try to complete the auction."
#
# SEUIL: < 3 barres dans la zone des 5 ticks du high/low = "poor"
# En Market Profile: < 2 TPO periods = poor (1 TPO = 30 min = ~30 barres 1min)
# On adapte pour les barres 1-min: < 3 barres = pas d'excess

# ═══════════════════════════════════════════════════════════════════════
# PATCH 1 — DMP_Transform.h
# ═══════════════════════════════════════════════════════════════════════
#
# A. Ajouter 4 champs dans struct DMP_MLFeatures (après single_print_count):
#
#    // 🆕 15/03/2026: Poor Highs/Lows (Market Profile avancé)
#    float poor_high;           // 1.0 si le session high n'a pas d'excess (< 3 barres)
#    float poor_low;            // 1.0 si le session low n'a pas d'excess
#    float excess_high_bars;    // Nombre de barres dans les 5t du session high
#    float excess_low_bars;     // Nombre de barres dans les 5t du session low
#
# B. Initialiser dans DMP_Transform() (où f.single_print_count = 0.0f):
#
#    f.poor_high        = 0.0f;
#    f.poor_low         = 0.0f;
#    f.excess_high_bars = 0.0f;
#    f.excess_low_bars  = 0.0f;
#
# C. Remplir dans CalcSession() (après sess_range_atr):
#
#    // 🆕 15/03/2026: Poor Highs/Lows — lu depuis DMP_RawData (calculé dans DMP_Main)
#    f.excess_high_bars = (float)r.excess_high_bars;
#    f.excess_low_bars  = (float)r.excess_low_bars;
#    f.poor_high        = r.poor_high ? 1.0f : 0.0f;
#    f.poor_low         = r.poor_low  ? 1.0f : 0.0f;
#
# D. Ajouter au header CSV dans DMP_GetCSVHeader() :
#
#    Ajouter "poor_high,poor_low,excess_high_bars,excess_low_bars,"
#    dans la section session (après sess_range_atr)
#
# E. Ajouter au JSONL writer (DMP_Writer.h) — dans la section session :
#
#    ... "\"poor_high\":" << f.poor_high
#        << ",\"poor_low\":" << f.poor_low
#        << ",\"excess_high_bars\":" << f.excess_high_bars
#        << ",\"excess_low_bars\":" << f.excess_low_bars


# ═══════════════════════════════════════════════════════════════════════
# PATCH 2 — DMP_Main.cpp
# ═══════════════════════════════════════════════════════════════════════
#
# A. Ajouter les constantes PersistentFloat (après DMP_PS_RTH_SET = 121):
#
#    constexpr int DMP_PS_POOR_HIGH_COUNT = 122;  // Barres dans 5t du sess high
#    constexpr int DMP_PS_POOR_LOW_COUNT  = 123;  // Barres dans 5t du sess low
#    constexpr int DMP_PS_POOR_LAST_HIGH  = 124;  // Dernier sess_high connu
#    constexpr int DMP_PS_POOR_LAST_LOW   = 125;  // Dernier sess_low connu
#    constexpr float POOR_THRESHOLD_TICKS = 5.0f; // Distance en ticks pour "near"
#    constexpr int   POOR_MIN_BARS        = 3;    // < 3 barres = poor
#
# B. Ajouter cette fonction (après DMP_FreezeIB):
#
# ── CODE C++ À COPIER ──────────────────────────────────────────────

"""
// ═══════════════════════════════════════════════════════════════════════
// 🆕 15/03/2026: POOR HIGHS/LOWS — Accumulation par session
// ═══════════════════════════════════════════════════════════════════════
// Appelé à chaque barre pour compter les barres près du session high/low.
// Si le session high/low change (nouveau high), le compteur se reset.
//
// Usage dans DMP_Main: après DMP_FreezeIB(), appeler:
//   DMP_TrackPoorHighsLows(sc, r, config.tick_size);
// ═══════════════════════════════════════════════════════════════════════

constexpr int DMP_PS_POOR_HIGH_COUNT = 122;
constexpr int DMP_PS_POOR_LOW_COUNT  = 123;
constexpr int DMP_PS_POOR_LAST_HIGH  = 124;
constexpr int DMP_PS_POOR_LAST_LOW   = 125;
constexpr float POOR_THRESHOLD_TICKS = 5.0f;
constexpr int   POOR_MIN_BARS        = 3;

inline void DMP_TrackPoorHighsLows(SCStudyInterfaceRef sc, DMP_RawData& r, float tick_size) {
    if (!DMP_IsPriceValid(r.sess_high) || !DMP_IsPriceValid(r.sess_low))
        return;
    if (!DMP_IsPriceValid(r.price_high) || !DMP_IsPriceValid(r.price_low))
        return;

    float threshold = POOR_THRESHOLD_TICKS * tick_size;

    // ── Session High tracking ──
    float& high_count = sc.GetPersistentFloat(DMP_PS_POOR_HIGH_COUNT);
    float& last_high  = sc.GetPersistentFloat(DMP_PS_POOR_LAST_HIGH);

    // Si le session high a changé → reset le compteur
    if (r.sess_high != last_high) {
        high_count = 0.0f;
        last_high = r.sess_high;
    }

    // Si la barre actuelle est dans les 5t du session high → incrémenter
    if (r.price_high >= r.sess_high - threshold) {
        high_count += 1.0f;
    }

    // ── Session Low tracking ──
    float& low_count = sc.GetPersistentFloat(DMP_PS_POOR_LOW_COUNT);
    float& last_low  = sc.GetPersistentFloat(DMP_PS_POOR_LAST_LOW);

    if (r.sess_low != last_low) {
        low_count = 0.0f;
        last_low = r.sess_low;
    }

    if (r.price_low <= r.sess_low + threshold) {
        low_count += 1.0f;
    }

    // ── Écrire les résultats dans DMP_RawData ──
    r.excess_high_bars = (int)high_count;
    r.excess_low_bars  = (int)low_count;
    r.poor_high = (r.excess_high_bars < POOR_MIN_BARS);
    r.poor_low  = (r.excess_low_bars  < POOR_MIN_BARS);
}
"""

# ── FIN DU CODE C++ ─────────────────────────────────────────────────
#
# C. Dans la boucle principale de DMP_Main.cpp, APRÈS DMP_FreezeIB():
#
#    // 🆕 15/03/2026: Poor Highs/Lows
#    DMP_TrackPoorHighsLows(sc, r, tick_size);
#
# D. Reset au début de nouvelle session (là où IB est reset):
#
#    sc.GetPersistentFloat(DMP_PS_POOR_HIGH_COUNT) = 0.0f;
#    sc.GetPersistentFloat(DMP_PS_POOR_LOW_COUNT)  = 0.0f;
#    sc.GetPersistentFloat(DMP_PS_POOR_LAST_HIGH)  = 0.0f;
#    sc.GetPersistentFloat(DMP_PS_POOR_LAST_LOW)   = 0.0f;


# ═══════════════════════════════════════════════════════════════════════
# PATCH 3 — Python dmp_reader.py (optionnel — pour quand le JSONL inclut les champs)
# ═══════════════════════════════════════════════════════════════════════
#
# Les colonnes seront automatiquement lues par DmpReader si elles
# existent dans le JSONL. Pas besoin de modifier dmp_reader.py.
#
# Mais pour utiliser poor_high/poor_low dans le pipeline avant d'avoir
# les données, on peut les approximer depuis les données existantes
# dans rolling_features.py :
#
#    # Approximation Poor High: fpbs_high_ask_pct < 55% et peu de barres au high
#    # (sera remplacé par la vraie valeur quand le DMP sera mis à jour)

# ═══════════════════════════════════════════════════════════════════════
# SCHEMA UPDATE : 3.6.0 → 3.7.0 (quand les 3 patches sont appliqués)
# ═══════════════════════════════════════════════════════════════════════
# Nouvelles colonnes : poor_high, poor_low, excess_high_bars, excess_low_bars
# Total : 250 → 254 colonnes
