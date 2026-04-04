#include "sierrachart.h"
#include <vector>
#include <string>
#include <ctime>

SCDLLName("MIA_Study_Inspector")

static SCString TodayStr() {
  time_t now = time(nullptr);
  struct tm* lt = localtime(&now);
  char buf[16];
  snprintf(buf, sizeof(buf), "%04d%02d%02d",
           lt ? lt->tm_year + 1900 : 1970,
           lt ? lt->tm_mon + 1 : 1,
           lt ? lt->tm_mday : 1);
  return SCString(buf);
}

static void EnsureOutDir() {
#ifdef _WIN32
  CreateDirectoryA("D:\\MIA_IA_system", NULL);
#endif
}

static void AppendLine(const SCString& path, const SCString& line) {
  FILE* f = fopen(path.GetChars(), "a");
  if (f) { fprintf(f, "%s\n", line.GetChars()); fclose(f); }
}

SCSFExport scsf_MIA_Study_Inspector(SCStudyInterfaceRef sc)
{
  if (sc.SetDefaults) {
    sc.GraphName = "MIA - Study Inspector";
    sc.AutoLoop = 0;
    sc.UpdateAlways = 0;

    sc.Input[0].Name = "Chart to Inspect (0 = current)";
    sc.Input[0].SetInt(0);

    sc.Input[1].Name = "Max Study Index to Scan (safety)";
    sc.Input[1].SetInt(200);

    return;
  }

  const int chart = sc.Input[0].GetInt() == 0 ? sc.ChartNumber : sc.Input[0].GetInt();
  int maxIdx = sc.Input[1].GetInt(); if (maxIdx < 1) maxIdx = 200;

  // Construire chemin fichier
  EnsureOutDir();
  SCString outPath;
  outPath.Format("D:\\MIA_IA_system\\study_inventory_chart_%d_%s.jsonl", chart, TodayStr().GetChars());

  // On repart de zéro à chaque exécution
  FILE* clr = fopen(outPath.GetChars(), "w"); if (clr) fclose(clr);

  int studyIndex = 1; // 1-based
  int found = 0;

  while (studyIndex <= maxIdx) {
    const int studyID = sc.GetStudyIDByIndex(chart, studyIndex);
    if (studyID <= 0) break; // plus d’études à cette position

    const SCString name = sc.GetStudyNameFromChart(chart, studyID);
    SCString shortName;
    sc.GetChartStudyShortName(chart, studyID, shortName);

    // Nombre de subgraphs
    SCGraphData studyData;
    sc.GetStudyArraysFromChartUsingID(chart, studyID, studyData);
    const int nsg = studyData.GetArraySize();

    // Émettre la ligne JSON
    SCString j;
    j.Format("{\"chart\":%d,\"index\":%d,\"study_id\":%d,"
             "\"name\":\"%s\",\"short\":\"%s\",\"n_subgraphs\":%d",
             chart, studyIndex, studyID,
             name.GetChars(), shortName.GetChars(), nsg);

    // Ajouter les subgraphs (noms)
    j += ",\"subgraphs\":[";
    for (int sg = 0; sg < nsg; ++sg) {
      SCString sgName;
      sc.GetStudySubgraphNameFromChart(chart, studyID, sg, sgName);
      SCString item; item.Format("{\"i\":%d,\"name\":\"%s\"}", sg, sgName.GetChars());
      j += item;
      if (sg != nsg - 1) j += ",";
    }
    j += "]}";

    AppendLine(outPath, j);

    // Log court
    SCString msg; msg.Format("[Inspector] #%d ID:%d %s (SG:%d)", studyIndex, studyID, name.GetChars(), nsg);
    sc.AddMessageToLog(msg, 0);

    ++found;
    ++studyIndex;
  }

  if (found == 0) {
    SCString msg; msg.Format("[Inspector] Aucun study détecté sur chart %d (vérifie le numéro).", chart);
    sc.AddMessageToLog(msg, 1);
  } else {
    SCString msg; msg.Format("[Inspector] %d study(s) listés sur chart %d. Fichier: %s",
                             found, chart, outPath.GetChars());
    sc.AddMessageToLog(msg, 0);
  }
}
