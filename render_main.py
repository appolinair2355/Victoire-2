# Bot Telegram pour Render.com
import os
import asyncio
from main import start_bot, client, run_health_server, main

if __name__ == "__main__":
    print("🚀 Démarrage bot Render.com...")
    asyncio.run(main())
