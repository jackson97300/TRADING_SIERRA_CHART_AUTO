#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_Utils.h - SECTION 4: FONCTIONS UTILITAIRES
// ═══════════════════════════════════════════════════════════════════════════════
// Extrait de MIA_AutoTrader_BN_v1.cpp (lignes 1111-1260)
// Refactoring: 31/01/2026
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Config.h"
#include "MIA_Globals.h"

// --- Conversion temps ---
// 🆕 FIX: Convertir heure locale (FR) en ET
// ═══════════════════════════════════════════════════════════════════════════
// CONVERSION HEURE LOCALE → HEURE ET (Eastern Time)
// ═══════════════════════════════════════════════════════════════════════════
// 🔧 IMPORTANT: Ajuster FR_TO_ET_OFFSET selon la config Sierra Chart!
// - Si Sierra Chart est en heure FR: FR_TO_ET_OFFSET = 6 (hiver) ou 5 (été)
// - Si Sierra Chart est en heure ET: FR_TO_ET_OFFSET = 0
// - Si Sierra Chart est en UTC: FR_TO_ET_OFFSET = -5 (hiver) ou -4 (été)
// ═══════════════════════════════════════════════════════════════════════════
// 🔧 27/01/2026: Sierra Chart affiche l'heure UTC!
// Conversion: UTC → ET (Eastern Time)
// - Hiver (EST): UTC - 5h → FR_TO_ET_OFFSET = 5
// - Été (EDT): UTC - 4h → FR_TO_ET_OFFSET = 4
// Formule: now_min_et = now_min_utc - FR_TO_ET_OFFSET * 60
inline const int FR_TO_ET_OFFSET = 5;  // 🔧 Sierra Chart en UTC → conversion vers EST (hiver)

inline int GetMinutesSinceMidnightET(SCDateTime dt) {
    int hour, minute, second;
    dt.GetTimeHMS(hour, minute, second);
    int now_min_local = hour * 60 + minute;

    int now_min_et = now_min_local - FR_TO_ET_OFFSET * 60;
    if (now_min_et < 0) now_min_et += 24 * 60;  // Wrap-around minuit
    if (now_min_et >= 24 * 60) now_min_et -= 24 * 60;  // Wrap-around 24h

    return now_min_et;
}

// --- Vérification session ---
// 🆕 Paramètre mode: 0=PRODUCTION (horaires stricts), 1=TEST (session étendue)
inline bool IsWithinTradingSession(SCStudyInterfaceRef sc, int mode = MODE_PRODUCTION) {
    int now_min = GetMinutesSinceMidnightET(sc.CurrentSystemDateTime);
    bool in_session = false;

    if (mode == MODE_TEST) {
        // ═══════════════════════════════════════════════════════════════════
        // MODE TEST: Session étendue (Asie 18:00 ET → Fermeture US 17:00 ET)
        // = Minuit FR → 23h00 FR (presque 24h sauf 1h de maintenance)
        // SANS pause US Open pour maximiser les tests
        // ═══════════════════════════════════════════════════════════════════

        // Session quasi-continue: 18:00 ET → 17:00 ET (23h/24)
        // Seule pause: 17:00-18:00 ET (maintenance CME)
        if (now_min >= TEST_SESSION_START_ET || now_min < TEST_SESSION_END_ET) {
            in_session = true;
        }

        // PAS de pause US Open en mode TEST

    } else {
        // ═══════════════════════════════════════════════════════════════════
        // MODE PRODUCTION: Horaires stricts (02h30 FR → 21h00 FR)
        // AVEC pause US Open (15:00-15:45 FR)
        // ═══════════════════════════════════════════════════════════════════

        // Session overnight: 20:30 ET -> 15:00 ET (next day)
        if (now_min >= SESSION_START_ET || now_min < SESSION_END_ET) {
            in_session = true;
        }

        // Pause avant/pendant US Open (PRODUCTION uniquement)
        if (now_min >= PRE_US_PAUSE_START_ET && now_min < US_OPR_END_ET) {
            in_session = false;
        }
    }

    return in_session;
}

// --- Nom de session actuelle ---
inline const char* GetCurrentSessionName(SCStudyInterfaceRef sc) {
    int now_min = GetMinutesSinceMidnightET(sc.CurrentSystemDateTime);

    if (now_min >= 20 * 60 + 30 || now_min < 3 * 60) {
        return "Asia";
    } else if (now_min >= 3 * 60 && now_min < 9 * 60) {
        return "London";
    } else if (now_min >= 9 * 60 && now_min < 9 * 60 + 45) {
        return "US_Open_Pause";
    } else if (now_min >= 9 * 60 + 45 && now_min < 15 * 60) {
        return "US";
    } else {
        return "Closed";
    }
}

// --- Détection spread anormal (annonces) ---
inline bool IsSpreadAbnormal(SCStudyInterfaceRef sc, const SymbolConfig& config) {
    float spread = sc.Ask - sc.Bid;
    float spread_ticks = spread / config.tick_size;
    return spread_ticks > config.spread_alert_ticks;
}

// --- Détection DOM vide ---
inline bool IsDOMEmpty(SCStudyInterfaceRef sc, const SymbolConfig& config) {
    // Lire profondeur DOM niveau 1
    s_MarketDepthEntry bid_entry, ask_entry;
    sc.GetBidMarketDepthEntryAtLevel(bid_entry, 0);
    sc.GetAskMarketDepthEntryAtLevel(ask_entry, 0);

    int total_depth = bid_entry.Quantity + ask_entry.Quantity;
    return total_depth < config.dom_min_depth;
}

// --- Format timestamp ---
inline std::string FormatTimestamp(SCDateTime dt) {
    int year, month, day, hour, minute, second;
    dt.GetDateTimeYMDHMS(year, month, day, hour, minute, second);

    std::ostringstream oss;
    oss << year << "-"
        << std::setfill('0') << std::setw(2) << month << "-"
        << std::setfill('0') << std::setw(2) << day << " "
        << std::setfill('0') << std::setw(2) << hour << ":"
        << std::setfill('0') << std::setw(2) << minute << ":"
        << std::setfill('0') << std::setw(2) << second;
    return oss.str();
}

// ═══════════════════════════════════════════════════════════════════════════════
// HELPER: Lecture Study Array avec vérification
// NOTE: sc.GetStudyArrayFromChartUsingID() retourne void, pas int!
// ═══════════════════════════════════════════════════════════════════════════════
inline bool GetStudyValue(SCStudyInterfaceRef sc, int chart, int study_id, int subgraph,
                          SCFloatArray& arr, float& out_value, int bar_offset = 0) {
    sc.GetStudyArrayFromChartUsingID(chart, study_id, subgraph, arr);
    int size = arr.GetArraySize();
    if (size > bar_offset) {
        out_value = arr[size - 1 - bar_offset];
        return true;
    }
    return false;
}

// Version qui retourne directement la valeur (0 si échec)
inline float ReadStudyValue(SCStudyInterfaceRef sc, int chart, int study_id, int subgraph, int bar_offset = 0) {
    SCFloatArray arr;
    sc.GetStudyArrayFromChartUsingID(chart, study_id, subgraph, arr);
    int size = arr.GetArraySize();
    if (size > bar_offset) {
        return arr[size - 1 - bar_offset];
    }
    return 0.0f;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 🆕 31/01/2026: ROTATION AUTOMATIQUE DES LOGS
// ═══════════════════════════════════════════════════════════════════════════════
// Nettoie les vieux logs pour éviter de remplir le disque
// À appeler une fois au démarrage du bot

inline void RotateLogsIfNeeded(const char* log_dir, int max_days = 30) {
    // Chercher tous les fichiers MIA_*.log dans le répertoire
    char pattern[512];
    snprintf(pattern, sizeof(pattern), "%s\\MIA_*.log", log_dir);
    
    WIN32_FIND_DATAA findData;
    HANDLE hFind = FindFirstFileA(pattern, &findData);
    
    if (hFind == INVALID_HANDLE_VALUE) {
        return;  // Aucun fichier trouvé ou erreur
    }
    
    // Obtenir la date actuelle
    SYSTEMTIME now;
    GetSystemTime(&now);
    
    // Convertir en FILETIME pour comparaison
    FILETIME now_ft;
    SystemTimeToFileTime(&now, &now_ft);
    
    // Constante: 100-nanoseconds intervals dans un jour
    const ULONGLONG INTERVALS_PER_DAY = 10000000ULL * 60 * 60 * 24;
    const ULONGLONG MAX_AGE = INTERVALS_PER_DAY * max_days;
    
    int deleted_count = 0;
    int total_count = 0;
    
    do {
        // Skip directories
        if (findData.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            continue;
        }
        
        total_count++;
        
        // Convertir FILETIME en ULONGLONG pour calcul
        ULARGE_INTEGER file_time, current_time;
        file_time.LowPart = findData.ftLastWriteTime.dwLowDateTime;
        file_time.HighPart = findData.ftLastWriteTime.dwHighDateTime;
        current_time.LowPart = now_ft.dwLowDateTime;
        current_time.HighPart = now_ft.dwHighDateTime;
        
        // Calculer l'âge du fichier
        ULONGLONG age = current_time.QuadPart - file_time.QuadPart;
        
        // Si plus vieux que max_days jours, supprimer
        if (age > MAX_AGE) {
            char filepath[768];
            snprintf(filepath, sizeof(filepath), "%s\\%s", log_dir, findData.cFileName);
            
            if (DeleteFileA(filepath)) {
                deleted_count++;
            }
        }
        
    } while (FindNextFileA(hFind, &findData));
    
    FindClose(hFind);
    
    // Log le résultat (optionnel - peut être commenté si trop verbeux)
    // printf("[LOG_ROTATION] %d fichiers analyses, %d supprimes (>%d jours)\n", 
    //        total_count, deleted_count, max_days);
}

// Version pour nettoyer snapshots JSON aussi
inline void RotateSnapshotsIfNeeded(const char* snapshot_dir, int max_days = 90) {
    // Chercher tous les fichiers MIA_TRADE_*.json dans le répertoire
    char pattern[512];
    snprintf(pattern, sizeof(pattern), "%s\\MIA_TRADE_*.json", snapshot_dir);
    
    WIN32_FIND_DATAA findData;
    HANDLE hFind = FindFirstFileA(pattern, &findData);
    
    if (hFind == INVALID_HANDLE_VALUE) {
        return;
    }
    
    SYSTEMTIME now;
    GetSystemTime(&now);
    
    FILETIME now_ft;
    SystemTimeToFileTime(&now, &now_ft);
    
    const ULONGLONG INTERVALS_PER_DAY = 10000000ULL * 60 * 60 * 24;
    const ULONGLONG MAX_AGE = INTERVALS_PER_DAY * max_days;
    
    int deleted_count = 0;
    
    do {
        if (findData.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            continue;
        }
        
        ULARGE_INTEGER file_time, current_time;
        file_time.LowPart = findData.ftLastWriteTime.dwLowDateTime;
        file_time.HighPart = findData.ftLastWriteTime.dwHighDateTime;
        current_time.LowPart = now_ft.dwLowDateTime;
        current_time.HighPart = now_ft.dwHighDateTime;
        
        ULONGLONG age = current_time.QuadPart - file_time.QuadPart;
        
        if (age > MAX_AGE) {
            char filepath[768];
            snprintf(filepath, sizeof(filepath), "%s\\%s", snapshot_dir, findData.cFileName);
            
            if (DeleteFileA(filepath)) {
                deleted_count++;
            }
        }
        
    } while (FindNextFileA(hFind, &findData));
    
    FindClose(hFind);
}