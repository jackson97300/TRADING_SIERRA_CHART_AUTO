"""Script de demarrage du dashboard MIA."""
import os
import sys

# Ajouter le repertoire parent au path pour permettre
# l'execution directe : python DASHBOARD/start_dashboard.py
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

import uvicorn

from DASHBOARD.config import API_HOST, API_PORT

if __name__ == "__main__":
    uvicorn.run(
        "DASHBOARD.api.app:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_level="info",
    )
