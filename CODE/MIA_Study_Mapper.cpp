// =============================================================================
// MIA_Study_Mapper.cpp - INVENTAIRE COMPLET (basé sur Inspector qui marche)
// =============================================================================
// 07/02/2026 - V3 DÉFINITIVE
//
// APPROCHE : Copie exacte de la logique MIA_Study_Inspector.cpp
//            qui trouvait 44 études sur chart 25.
//
// PRINCIPE : On ne lit PAS les valeurs pour décider si une étude existe.
//            On demande uniquement les MÉTADONNÉES :
//            - GetStudyIDByIndex → l'étude existe-t-elle ?
//            - GetStudyNameFromChart → comment s'appelle-t-elle ?
//            - GetStudyArraysFromChartUsingID → combien de subgraphs ?
//            - GetStudySubgraphNameFromChart → nom de chaque subgraph
//
//            Les valeurs sont lues en BONUS (info supplémentaire)
//            mais ne servent JAMAIS de filtre.
//
// SORTIE : D:\TRADING_SIERRA_CHART_AUTO\STUDIES\chart_XX.json
// USAGE  : Ajouter sur CHAQUE chart (13 charts), scan automatique
// =============================================================================

#include "sierrachart.h"
#include <cstdio>
#include <ctime>

SCDLLName("MIA_Study_Mapper")

// =============================================================================
// HELPERS
// =============================================================================

static void EnsureDir(const char* path) {
#ifdef _WIN32
    CreateDirectoryA(path, NULL);
#endif
}

static void WriteEscaped(FILE* f, const char* s) {
    if (!s) return;
    while (*s) {
        switch (*s) {
            case '"':  fprintf(f, "\\\""); break;
            case '\\': fprintf(f, "\\\\"); break;
            case '\n': fprintf(f, "\\n"); break;
            case '\r': fprintf(f, "\\r"); break;
            case '\t': fprintf(f, "\\t"); break;
            default:   fputc(*s, f); break;
        }
        s++;
    }
}

// =============================================================================
// FONCTION PRINCIPALE — Calquée sur MIA_Study_Inspector
// =============================================================================

SCSFExport scsf_MIA_Study_Mapper(SCStudyInterfaceRef sc)
{
    SCInputRef Input_MaxStudy    = sc.Input[0];
    SCInputRef Input_ForceRescan = sc.Input[1];

    if (sc.SetDefaults) {
        sc.GraphName = "MIA - Study Mapper";
        sc.StudyDescription = 
            "Inventaire complet des etudes et subgraphs (noms + valeurs). "
            "Sortie: D:\\TRADING_SIERRA_CHART_AUTO\\STUDIES\\chart_XX.json";
        sc.AutoLoop = 0;

        // ═══ CRITIQUE : UpdateAlways = 0 ═══
        // Comme l'Inspector. Avec 1, le scan tourne au premier tick
        // quand les données ne sont pas encore chargées → 0 résultats.
        sc.UpdateAlways = 0;

        Input_MaxStudy.Name = "Max Study Index to scan";
        Input_MaxStudy.SetInt(200);

        Input_ForceRescan.Name = "Force Rescan (toggle 0/1)";
        Input_ForceRescan.SetInt(0);

        return;
    }

    // ─── UN SEUL SCAN PAR SESSION ───
    int& done = sc.GetPersistentInt(1);
    int& lastRescan = sc.GetPersistentInt(2);

    if (Input_ForceRescan.GetInt() != lastRescan) {
        lastRescan = Input_ForceRescan.GetInt();
        done = 0;
    }

    if (done == 1) return;
    done = 1;

    // ─── PARAMÈTRES ───
    const int chartNum = sc.ChartNumber;
    int maxStudy = Input_MaxStudy.GetInt();
    if (maxStudy < 1) maxStudy = 200;

    // ─── RÉPERTOIRE + FICHIER ───
    EnsureDir("D:\\TRADING_SIERRA_CHART_AUTO");
    EnsureDir("D:\\TRADING_SIERRA_CHART_AUTO\\STUDIES");

    char filepath[512];
    snprintf(filepath, sizeof(filepath),
        "D:\\TRADING_SIERRA_CHART_AUTO\\STUDIES\\chart_%d.json", chartNum);

    FILE* f = fopen(filepath, "w");
    if (!f) {
        SCString err;
        err.Format("[Mapper] Cannot open %s", filepath);
        sc.AddMessageToLog(err, 1);
        return;
    }

    // ─── TIMESTAMP ───
    time_t now = time(nullptr);
    struct tm* lt = localtime(&now);
    char timestamp[32];
    snprintf(timestamp, sizeof(timestamp), "%04d-%02d-%02d %02d:%02d:%02d",
             lt ? lt->tm_year + 1900 : 1970, lt ? lt->tm_mon + 1 : 1,
             lt ? lt->tm_mday : 1, lt ? lt->tm_hour : 0,
             lt ? lt->tm_min : 0, lt ? lt->tm_sec : 0);

    // ─── HEADER JSON ───
    SCString chartSymbol = sc.GetChartSymbol(chartNum);

    fprintf(f, "{\n");
    fprintf(f, "  \"chart_number\": %d,\n", chartNum);
    fprintf(f, "  \"chart_symbol\": \"");
    WriteEscaped(f, chartSymbol.GetChars());
    fprintf(f, "\",\n");
    fprintf(f, "  \"scan_timestamp\": \"%s\",\n", timestamp);
    fprintf(f, "  \"studies\": [\n");

    // ═══════════════════════════════════════════════════════════════════
    // BOUCLE PRINCIPALE — IDENTIQUE À L'INSPECTOR
    // ═══════════════════════════════════════════════════════════════════

    int studyIndex = 1;
    int found = 0;
    bool firstJson = true;

    while (studyIndex <= maxStudy) {

        // ─── Obtenir l'ID de l'étude ───
        const int studyID = sc.GetStudyIDByIndex(chartNum, studyIndex);

        // ═══ BREAK si plus d'études (comme l'Inspector) ═══
        if (studyID <= 0) break;

        // ─── Métadonnées (toujours disponibles, pas besoin de données) ───
        const SCString studyName = sc.GetStudyNameFromChart(chartNum, studyID);
        SCString shortName;
        sc.GetChartStudyShortName(chartNum, studyID, shortName);

        // ─── Nombre de subgraphs ───
        SCGraphData studyData;
        sc.GetStudyArraysFromChartUsingID(chartNum, studyID, studyData);
        const int nsg = studyData.GetArraySize();

        // ═══ ÉCRIRE L'ÉTUDE — TOUJOURS, PAS DE FILTRE ═══
        if (!firstJson) fprintf(f, ",\n");
        firstJson = false;

        fprintf(f, "    {\n");
        fprintf(f, "      \"study_index\": %d,\n", studyIndex);
        fprintf(f, "      \"study_id\": %d,\n", studyID);
        fprintf(f, "      \"name\": \"");
        WriteEscaped(f, studyName.GetChars());
        fprintf(f, "\",\n");
        fprintf(f, "      \"short_name\": \"");
        WriteEscaped(f, shortName.GetChars());
        fprintf(f, "\",\n");
        fprintf(f, "      \"n_subgraphs\": %d,\n", nsg);
        fprintf(f, "      \"subgraphs\": [\n");

        // ─── LISTER CHAQUE SUBGRAPH (nom + valeur bonus) ───
        for (int sg = 0; sg < nsg; sg++) {

            // Nom du subgraph (métadonnée, toujours dispo)
            SCString sgName;
            sc.GetStudySubgraphNameFromChart(chartNum, studyID, sg, sgName);

            // Valeur = BONUS (on essaie de lire, on ne filtre pas)
            float val = 0.0f;
            bool hasVal = false;
            SCFloatArray arr;
            sc.GetStudyArrayFromChartUsingID(chartNum, studyID, sg, arr);
            if (arr.GetArraySize() > 0) {
                float v = arr[arr.GetArraySize() - 1];
                if (v == v && v > -1e10f && v < 1e10f) {  // pas NaN, pas overflow
                    val = v;
                    hasVal = true;
                }
            }

            // Écrire le subgraph
            if (sg > 0) fprintf(f, ",\n");
            fprintf(f, "        {\"i\": %d, \"name\": \"", sg);
            WriteEscaped(f, sgName.GetChars());
            fprintf(f, "\"");
            if (hasVal) {
                fprintf(f, ", \"val\": %.6f", val);
            }
            fprintf(f, "}");
        }

        fprintf(f, "\n      ]\n");
        fprintf(f, "    }");

        // ─── LOG ───
        SCString msg;
        msg.Format("[Mapper] #%d ID:%d %s (%d sg)",
                   studyIndex, studyID, studyName.GetChars(), nsg);
        sc.AddMessageToLog(msg, 0);

        found++;
        studyIndex++;
    }

    // ═══════════════════════════════════════════════════════════════════
    // FERMER JSON
    // ═══════════════════════════════════════════════════════════════════

    fprintf(f, "\n  ],\n");
    fprintf(f, "  \"summary\": {\"total_studies\": %d}\n", found);
    fprintf(f, "}\n");
    fclose(f);

    // ─── LOG FINAL ───
    if (found == 0) {
        SCString msg;
        msg.Format("[Mapper] Aucune etude sur chart %d!", chartNum);
        sc.AddMessageToLog(msg, 1);
    } else {
        SCString msg;
        msg.Format("[Mapper] Chart %d: %d etudes -> %s",
                   chartNum, found, filepath);
        sc.AddMessageToLog(msg, 0);
    }
}
