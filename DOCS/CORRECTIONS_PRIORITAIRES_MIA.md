# 🔧 CORRECTIONS PRIORITAIRES - MIA TRADING SYSTEM

**Date**: 31/01/2026  
**Complément à**: AUDIT_ARCHITECTURAL_MIA.md

---

## 🚨 CORRECTION 1: Protection des Variables Globales (4h)

### Problème
```cpp
// Actuel - DANGEREUX
inline BotState g_es_state;
inline BotState g_nq_state;
```

### Solution: Wrapper Thread-Safe

**Fichier: `MIA_StateManager.h`**
```cpp
#pragma once
#include "MIA_Config.h"
#include <mutex>

class StateManager {
private:
    BotState m_es_state;
    BotState m_nq_state;
    DashboardData m_dashboard;
    std::mutex m_es_mutex;
    std::mutex m_nq_mutex;
    std::mutex m_dashboard_mutex;
    
public:
    // Singleton pattern
    static StateManager& Instance() {
        static StateManager instance;
        return instance;
    }
    
    // ES State - Thread-safe access
    BotState GetESState() {
        std::lock_guard<std::mutex> lock(m_es_mutex);
        return m_es_state;  // Copie
    }
    
    void UpdateESState(const std::function<void(BotState&)>& updater) {
        std::lock_guard<std::mutex> lock(m_es_mutex);
        updater(m_es_state);
    }
    
    // NQ State - Thread-safe access
    BotState GetNQState() {
        std::lock_guard<std::mutex> lock(m_nq_mutex);
        return m_nq_state;
    }
    
    void UpdateNQState(const std::function<void(BotState&)>& updater) {
        std::lock_guard<std::mutex> lock(m_nq_mutex);
        updater(m_nq_state);
    }
    
    // Dashboard - Thread-safe
    void UpdateDashboard(const std::function<void(DashboardData&)>& updater) {
        std::lock_guard<std::mutex> lock(m_dashboard_mutex);
        updater(m_dashboard);
    }
    
    DashboardData GetDashboard() {
        std::lock_guard<std::mutex> lock(m_dashboard_mutex);
        return m_dashboard;
    }
    
private:
    StateManager() = default;
};

// Macros de compatibilité pour migration graduelle
#define GET_ES_STATE() StateManager::Instance().GetESState()
#define GET_NQ_STATE() StateManager::Instance().GetNQState()
#define UPDATE_ES_STATE(updater) StateManager::Instance().UpdateESState(updater)
#define UPDATE_NQ_STATE(updater) StateManager::Instance().UpdateNQState(updater)
```

### Migration
```cpp
// Avant
g_es_state.in_position = true;
g_es_state.entry_price = 6100.0f;

// Après
UPDATE_ES_STATE([&](BotState& state) {
    state.in_position = true;
    state.entry_price = 6100.0f;
});
```

---

## 🚨 CORRECTION 2: Versioning des Schémas JSON (2h)

### Problème
```cpp
// Actuel - Pas de version
file << "{\n";
file << "  \"bot_running\": true,\n";
```

### Solution: Header Versionné

**Constante dans `MIA_Config.h`**
```cpp
// Ajouter en haut de MIA_Config.h
inline const char* MIA_SCHEMA_VERSION = "2.1.0";
inline const char* MIA_BUILD_DATE = "2026-01-31";
```

**Modifier `SaveTradeSnapshot()` dans `MIA_Logging.h`**
```cpp
inline void SaveTradeSnapshot(
    SCStudyInterfaceRef sc,
    const TradeSnapshot& snap,
    const SymbolConfig& config
) {
    // ... création fichier ...
    
    file << "{\n";
    
    // 🆕 HEADER VERSIONNÉ
    file << "  \"_schema\": {\n";
    file << "    \"version\": \"" << MIA_SCHEMA_VERSION << "\",\n";
    file << "    \"type\": \"trade_snapshot\",\n";
    file << "    \"build\": \"" << MIA_BUILD_DATE << "\",\n";
    file << "    \"generated_at\": \"" << FormatTimestamp(sc.CurrentSystemDateTime) << "\"\n";
    file << "  },\n";
    
    // Reste du JSON...
    file << "  \"trade_id\": " << snap.trade_id << ",\n";
    // ...
}
```

**Modifier `SaveDashboardJSON()` pareil**
```cpp
inline void SaveDashboardJSON(SCStudyInterfaceRef sc) {
    // ...
    file << "{\n";
    file << "  \"_schema\": {\"version\": \"" << MIA_SCHEMA_VERSION << "\", \"type\": \"dashboard\"},\n";
    // ...
}
```

**Validation côté Python**
```python
# mia_data_loader.py
import json

EXPECTED_SCHEMA_VERSION = "2.1.0"

def load_snapshot(filepath):
    with open(filepath) as f:
        data = json.load(f)
    
    # Validation version
    schema = data.get("_schema", {})
    version = schema.get("version", "1.0.0")
    
    if version != EXPECTED_SCHEMA_VERSION:
        major_expected = EXPECTED_SCHEMA_VERSION.split('.')[0]
        major_actual = version.split('.')[0]
        
        if major_expected != major_actual:
            raise ValueError(f"Schema incompatible: attendu {EXPECTED_SCHEMA_VERSION}, reçu {version}")
        else:
            print(f"⚠️ Warning: version mineure différente ({version} vs {EXPECTED_SCHEMA_VERSION})")
    
    return data
```

---

## 🚨 CORRECTION 3: Externalisation des Study IDs (8h)

### Problème
```cpp
// Hardcodé dans MIA_DataReader.h
const int ES_FP_EDGE_BUY = 32;
const int ES_FP_EDGE_SELL = 35;
// ... 60+ constantes
```

### Solution: Fichier de Configuration

**Fichier: `D:\MIA_IA_system\config\study_mapping.json`**
```json
{
    "_comment": "Study IDs Sierra Chart - NE PAS MODIFIER SANS BACKUP",
    "_updated": "2026-01-31",
    
    "ES_FOOTPRINT": {
        "chart_number": 1,
        "studies": {
            "EDGE_BUY": 32,
            "EDGE_SELL": 35,
            "COLOR_UP": 56,
            "COLOR_DOWN": 57,
            "ABSORB_ASK": 25,
            "ABSORB_BID": 26,
            "DOUBLE_ASK": 28,
            "DOUBLE_BID": 27,
            "ROTATION_UP": 19,
            "ROTATION_DOWN": 20,
            "FPBS": 31,
            "ASK_100": 102,
            "BID_100": 103,
            "ASK_400": 8,
            "BID_400": 9,
            "ASK_1000": 29,
            "BID_1000": 30
        }
    },
    
    "NQ_FOOTPRINT": {
        "chart_number": 2,
        "studies": {
            "EDGE_BUY": 55,
            "EDGE_SELL": 56,
            "COLOR_UP": 53,
            "COLOR_DOWN": 54,
            "ABSORB_ASK": 29,
            "ABSORB_BID": 30,
            "TRIPLE_ASK": 28,
            "TRIPLE_BID": 27
        }
    },
    
    "ES_BARRES": {
        "chart_number": 25,
        "studies": {
            "COLOR_UP": 24,
            "COLOR_DOWN": 25,
            "LONG_DOWN_UP": 38,
            "LONG_UP_DOWN": 39,
            "EDGE_BUY": 16,
            "EDGE_SELL": 44,
            "MQ_GAMMA": 2,
            "MQ_BLIND": 22,
            "VWAP": 1
        }
    },
    
    "NQ_BARRES": {
        "chart_number": 23,
        "studies": {
            "COLOR_UP": 26,
            "COLOR_DOWN": 27,
            "LONG_DOWN_UP": 23,
            "LONG_UP_DOWN": 24,
            "EDGE_BUY": 32,
            "EDGE_SELL": 33,
            "MQ_GAMMA": 25,
            "MQ_BLIND": 2,
            "VWAP": 1
        }
    }
}
```

**Nouveau fichier: `MIA_StudyConfig.h`**
```cpp
#pragma once
#include "MIA_Config.h"
#include <fstream>
#include <map>
#include <string>

// Structure pour stocker le mapping
struct ChartStudyMapping {
    int chart_number;
    std::map<std::string, int> studies;
};

class StudyConfig {
private:
    std::map<std::string, ChartStudyMapping> m_mappings;
    bool m_loaded = false;
    
public:
    static StudyConfig& Instance() {
        static StudyConfig instance;
        return instance;
    }
    
    bool LoadFromFile(const char* filepath) {
        std::ifstream file(filepath);
        if (!file.is_open()) return false;
        
        // Parse JSON simple (ou utiliser une lib JSON)
        // Pour simplifier, on peut aussi utiliser un format .ini ou .csv
        
        m_loaded = true;
        return true;
    }
    
    int GetStudyID(const char* chart_key, const char* study_name) {
        if (!m_loaded) {
            LoadFromFile("D:\\MIA_IA_system\\config\\study_mapping.json");
        }
        
        auto it = m_mappings.find(chart_key);
        if (it == m_mappings.end()) return -1;
        
        auto& studies = it->second.studies;
        auto sit = studies.find(study_name);
        if (sit == studies.end()) return -1;
        
        return sit->second;
    }
    
    int GetChartNumber(const char* chart_key) {
        auto it = m_mappings.find(chart_key);
        if (it == m_mappings.end()) return -1;
        return it->second.chart_number;
    }
};

// Macros pour migration facile
#define STUDY_ID(chart, name) StudyConfig::Instance().GetStudyID(chart, name)
#define CHART_NUM(chart) StudyConfig::Instance().GetChartNumber(chart)
```

**Migration dans `MIA_DataReader.h`**
```cpp
// Avant
const int ES_FP_EDGE_BUY = 32;
sc.GetStudyArrayFromChartUsingID(chart_footprint, ES_FP_EDGE_BUY, ...);

// Après
int edge_buy_id = STUDY_ID("ES_FOOTPRINT", "EDGE_BUY");
if (edge_buy_id > 0) {
    sc.GetStudyArrayFromChartUsingID(chart_footprint, edge_buy_id, ...);
}
```

---

## 🚨 CORRECTION 4: Rotation des Logs (2h)

### Problème
Les logs s'accumulent sans limite → disque plein potentiel.

### Solution: Rotation Quotidienne

**Ajouter dans `MIA_Utils.h`**
```cpp
inline void RotateLogsIfNeeded(const char* log_dir, int max_days = 30) {
    // Supprimer les fichiers de plus de max_days jours
    char pattern[256];
    snprintf(pattern, sizeof(pattern), "%s\\MIA_*.log", log_dir);
    
    WIN32_FIND_DATAA findData;
    HANDLE hFind = FindFirstFileA(pattern, &findData);
    
    if (hFind == INVALID_HANDLE_VALUE) return;
    
    SYSTEMTIME now;
    GetSystemTime(&now);
    
    do {
        // Calculer l'âge du fichier
        FILETIME ft = findData.ftLastWriteTime;
        SYSTEMTIME st;
        FileTimeToSystemTime(&ft, &st);
        
        // Différence en jours (approximatif)
        int age_days = (now.wYear - st.wYear) * 365 + 
                       (now.wMonth - st.wMonth) * 30 + 
                       (now.wDay - st.wDay);
        
        if (age_days > max_days) {
            char filepath[512];
            snprintf(filepath, sizeof(filepath), "%s\\%s", log_dir, findData.cFileName);
            DeleteFileA(filepath);
        }
    } while (FindNextFileA(hFind, &findData));
    
    FindClose(hFind);
}
```

**Appeler au démarrage dans `MIA_Main.cpp`**
```cpp
// Dans scsf_MIA_AutoTrader(), section INIT
if (sc.SetDefaults) {
    // ...
}

// Une fois au démarrage
static bool logs_rotated = false;
if (!logs_rotated) {
    RotateLogsIfNeeded("D:\\LOGS\\MIA", 30);
    RotateLogsIfNeeded("D:\\MIA_IA_system\\TRADING_SIERRA_CHART_AUTO\\SNAPSHOTS", 90);
    logs_rotated = true;
}
```

---

## 🚨 CORRECTION 5: Interface Abstraite pour Tests (16h)

### Objectif
Permettre de tester la logique Layers sans Sierra Chart.

**Fichier: `MIA_Interfaces.h`**
```cpp
#pragma once
#include "MIA_Config.h"

// Interface pour source de données OrderFlow
class IOrderFlowSource {
public:
    virtual ~IOrderFlowSource() = default;
    virtual BN_Data GetBatailleNavale(bool is_nq) = 0;
    virtual MenthorQ_Data GetMenthorQ(bool is_nq) = 0;
    virtual float GetCurrentPrice(bool is_nq) = 0;
    virtual float GetVIX() = 0;
    virtual float GetATR(bool is_nq) = 0;
};

// Interface pour exécution d'ordres
class IOrderExecutor {
public:
    virtual ~IOrderExecutor() = default;
    virtual bool SendBracketOrder(int direction, float entry, float sl, float tp) = 0;
    virtual bool CancelOrder(int order_id) = 0;
    virtual bool ModifyOrder(int order_id, float new_price) = 0;
};

// Interface pour logging
class ILogger {
public:
    virtual ~ILogger() = default;
    virtual void LogTrade(const TradeSnapshot& snap) = 0;
    virtual void LogReject(const char* reason) = 0;
    virtual void LogDashboard(const DashboardData& dash) = 0;
};
```

**Implémentation Sierra Chart (production)**
```cpp
// MIA_SierraImpl.h
class SierraOrderFlow : public IOrderFlowSource {
private:
    SCStudyInterfaceRef& m_sc;
    int m_chart_es_fp, m_chart_nq_fp;
    
public:
    SierraOrderFlow(SCStudyInterfaceRef& sc, int chart_es, int chart_nq)
        : m_sc(sc), m_chart_es_fp(chart_es), m_chart_nq_fp(chart_nq) {}
    
    BN_Data GetBatailleNavale(bool is_nq) override {
        BN_Data bn;
        CollectBN_Data(m_sc, is_nq ? m_chart_nq_fp : m_chart_es_fp, ..., bn, is_nq);
        return bn;
    }
    
    // ... autres méthodes
};
```

**Implémentation Mock (tests)**
```cpp
// MIA_MockImpl.h (pour tests unitaires)
class MockOrderFlow : public IOrderFlowSource {
private:
    BN_Data m_bn_data;
    MenthorQ_Data m_mq_data;
    float m_price = 6100.0f;
    
public:
    void SetBNData(const BN_Data& data) { m_bn_data = data; }
    void SetMQData(const MenthorQ_Data& data) { m_mq_data = data; }
    void SetPrice(float price) { m_price = price; }
    
    BN_Data GetBatailleNavale(bool is_nq) override { return m_bn_data; }
    MenthorQ_Data GetMenthorQ(bool is_nq) override { return m_mq_data; }
    float GetCurrentPrice(bool is_nq) override { return m_price; }
    float GetVIX() override { return 15.0f; }
    float GetATR(bool is_nq) override { return is_nq ? 50.0f : 10.0f; }
};
```

**Test Unitaire Possible**
```cpp
// tests/test_layers.cpp
#include "MIA_Layers.h"
#include "MIA_MockImpl.h"
#include <cassert>

void TestLayer1_HVL_Proximity() {
    MockOrderFlow mock;
    
    MenthorQ_Data mq = {};
    mq.hvl = 6100.0f;
    mq.hvl_0dte = 6095.0f;
    mock.SetMQData(mq);
    mock.SetPrice(6098.0f);  // 12 ticks du HVL
    
    // Simuler Layer1 validation
    Layer1Result result = ValidateLayer1_Testable(
        mock.GetMenthorQ(false),
        mock.GetCurrentPrice(false),
        CONFIG_ES,
        0.0f,
        nullptr,
        true
    );
    
    assert(result.passed == true);
    assert(strcmp(result.level_name, "HVL") == 0 || 
           strcmp(result.level_name, "HVL_0DTE") == 0);
    
    printf("✅ TestLayer1_HVL_Proximity PASSED\n");
}

int main() {
    TestLayer1_HVL_Proximity();
    // ... autres tests
    return 0;
}
```

---

## 📋 ORDRE D'IMPLÉMENTATION RECOMMANDÉ

| Étape | Correction | Effort | Dépendances |
|-------|------------|--------|-------------|
| 1 | Versioning JSON | 2h | Aucune |
| 2 | Rotation logs | 2h | Aucune |
| 3 | Mutex états globaux | 4h | Aucune |
| 4 | Config Study IDs | 8h | Aucune |
| 5 | Interfaces abstraites | 16h | Étapes 1-4 |

**Total**: ~32h de développement

---

## ✅ CHECKLIST VALIDATION

Après chaque correction:

- [ ] Compiler sans erreur
- [ ] Test en MODE_TEST 30 min minimum
- [ ] Vérifier logs générés
- [ ] Vérifier JSON lisible par Python
- [ ] Backup du code avant/après
- [ ] Documentation mise à jour

---

*Guide de corrections - MIA Trading System - 31/01/2026*
