#!/usr/bin/env python3
"""
Bot Telegram - Version Render.com
Port: 10000 (configuré automatiquement)
Auto-configuration des canaux depuis bot_config.json
"""
import os
import sys

# Forcer le port 10000 pour Render.com
os.environ['PORT'] = '10000'

# Charger les variables depuis Render (si définies)
if not os.getenv('API_ID'):
    print("⚠️ Variables d'environnement manquantes sur Render!")
    print("Configurez: API_ID, API_HASH, BOT_TOKEN, ADMIN_ID")
    sys.exit(1)

# Lancer le bot principal
print("🚀 Démarrage sur Render.com (Port 10000)...")
from main import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
