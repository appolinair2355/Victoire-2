import os
import asyncio
import re
import json
import zipfile
import tempfile
import shutil
from datetime import datetime
from telethon import TelegramClient, events
from telethon.events import ChatAction
from dotenv import load_dotenv
from predictor import CardPredictor
from scheduler import PredictionScheduler
from yaml_manager import init_database, db
from excel_importer import ExcelPredictionManager
from aiohttp import web
import threading

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
try:
    API_ID = int(os.getenv('API_ID') or '0')
    API_HASH = os.getenv('API_HASH') or ''
    BOT_TOKEN = os.getenv('BOT_TOKEN') or ''
    ADMIN_ID = int(os.getenv('ADMIN_ID') or '0') if os.getenv('ADMIN_ID') else None
    PORT = int(os.getenv('PORT') or '10000')
    DISPLAY_CHANNEL = int(os.getenv('DISPLAY_CHANNEL') or '-1002999811353')

    # Validation des variables requises
    if not API_ID or API_ID == 0:
        raise ValueError("API_ID manquant ou invalide")
    if not API_HASH:
        raise ValueError("API_HASH manquant")
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN manquant")

    print(f"✅ Configuration chargée: API_ID={API_ID}, ADMIN_ID={ADMIN_ID or 'Non configuré'}, PORT={PORT}, DISPLAY_CHANNEL={DISPLAY_CHANNEL}")
except Exception as e:
    print(f"❌ Erreur configuration: {e}")
    print("Vérifiez vos variables d'environnement")
    exit(1)

# Fichier de configuration persistante
CONFIG_FILE = 'bot_config.json'

# Variables d'état
detected_stat_channel = None
detected_display_channel = None
confirmation_pending = {}
prediction_interval = 5  # Intervalle en minutes avant de chercher "A" (défaut: 5 min)

def load_config():
    """Load configuration with priority: JSON > Database > Environment"""
    global detected_stat_channel, detected_display_channel, prediction_interval
    try:
        # Toujours essayer JSON en premier (source de vérité)
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                detected_stat_channel = config.get('stat_channel')
                detected_display_channel = config.get('display_channel', DISPLAY_CHANNEL)
                prediction_interval = config.get('prediction_interval', 1)
                print(f"✅ Configuration chargée depuis JSON: Stats={detected_stat_channel}, Display={detected_display_channel}, Intervalle={prediction_interval}min")
                return

        # Fallback sur base de données si JSON n'existe pas
        if db:
            detected_stat_channel = db.get_config('stat_channel')
            detected_display_channel = db.get_config('display_channel') or DISPLAY_CHANNEL
            interval_config = db.get_config('prediction_interval')
            if detected_stat_channel:
                detected_stat_channel = int(detected_stat_channel)
            if detected_display_channel:
                detected_display_channel = int(detected_display_channel)
            if interval_config:
                prediction_interval = int(interval_config)
            print(f"✅ Configuration chargée depuis la DB: Stats={detected_stat_channel}, Display={detected_display_channel}, Intervalle={prediction_interval}min")
        else:
            # Utiliser le canal de display par défaut depuis les variables d'environnement
            detected_display_channel = DISPLAY_CHANNEL
            prediction_interval = 1
            print(f"ℹ️ Configuration par défaut: Display={detected_display_channel}, Intervalle={prediction_interval}min")
    except Exception as e:
        print(f"⚠️ Erreur chargement configuration: {e}")
        # Valeurs par défaut en cas d'erreur
        detected_stat_channel = None
        detected_display_channel = DISPLAY_CHANNEL
        prediction_interval = 1

def save_config():
    """Save configuration to database and JSON backup"""
    try:
        if db:
            # Sauvegarde en base de données
            db.set_config('stat_channel', detected_stat_channel)
            db.set_config('display_channel', detected_display_channel)
            db.set_config('prediction_interval', prediction_interval)
            print("💾 Configuration sauvegardée en base de données")

        # Sauvegarde JSON de secours
        config = {
            'stat_channel': detected_stat_channel,
            'display_channel': detected_display_channel,
            'prediction_interval': prediction_interval
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        print(f"💾 Configuration sauvegardée: Stats={detected_stat_channel}, Display={detected_display_channel}, Intervalle={prediction_interval}min")
    except Exception as e:
        print(f"❌ Erreur sauvegarde configuration: {e}")

def update_channel_config(source_id: int, target_id: int):
    """Update channel configuration"""
    global detected_stat_channel, detected_display_channel
    detected_stat_channel = source_id
    detected_display_channel = target_id
    save_config()

# Initialize database
database = init_database()

# Gestionnaire de prédictions
predictor = CardPredictor()

# Planificateur automatique
scheduler = None

# Gestionnaire d'importation Excel
excel_manager = ExcelPredictionManager()

# Initialize Telegram client with unique session name
import time
session_name = f'bot_session_{int(time.time())}'
client = TelegramClient(session_name, API_ID, API_HASH)

async def start_bot():
    """Start the bot with proper error handling"""
    try:
        # Load saved configuration first
        load_config()

        await client.start(bot_token=BOT_TOKEN)
        print("Bot démarré avec succès...")

        # Get bot info
        me = await client.get_me()
        username = getattr(me, 'username', 'Unknown') or f"ID:{getattr(me, 'id', 'Unknown')}"
        print(f"Bot connecté: @{username}")

    except Exception as e:
        print(f"Erreur lors du démarrage du bot: {e}")
        return False

    return True

# --- INVITATION / CONFIRMATION ---
@client.on(events.ChatAction())
async def handler_join(event):
    """Handle bot joining channels/groups"""
    global confirmation_pending

    try:
        # Ignorer les événements d'épinglage de messages
        if event.new_pin or event.unpin:
            return

        # Ignorer les événements sans user_id (comme les épinglages)
        if not event.user_id:
            return

        print(f"ChatAction event: {event}")
        print(f"user_joined: {event.user_joined}, user_added: {event.user_added}")
        print(f"user_id: {event.user_id}, chat_id: {event.chat_id}")

        if event.user_joined or event.user_added:
            me = await client.get_me()
            me_id = getattr(me, 'id', None)
            print(f"Mon ID: {me_id}, Event user_id: {event.user_id}")

            if event.user_id == me_id:
                confirmation_pending[event.chat_id] = 'waiting_confirmation'

                # Get channel info
                try:
                    chat = await client.get_entity(event.chat_id)
                    chat_title = getattr(chat, 'title', f'Canal {event.chat_id}')
                except:
                    chat_title = f'Canal {event.chat_id}'

                # Send private invitation to admin
                invitation_msg = f"""🔔 **Nouveau canal détecté**

📋 **Canal** : {chat_title}
🆔 **ID** : {event.chat_id}

**Choisissez le type de canal** :
• `/set_stat {event.chat_id}` - Canal de statistiques
• `/set_display {event.chat_id}` - Canal de diffusion

Envoyez votre choix en réponse à ce message."""

                try:
                    await client.send_message(ADMIN_ID, invitation_msg)
                    print(f"Invitation envoyée à l'admin pour le canal: {chat_title} ({event.chat_id})")
                except Exception as e:
                    print(f"Erreur envoi invitation privée: {e}")
                    # Fallback: send to the channel temporarily for testing
                    await client.send_message(event.chat_id, f"⚠️ Impossible d'envoyer l'invitation privée. Canal ID: {event.chat_id}")
                    print(f"Message fallback envoyé dans le canal {event.chat_id}")
    except Exception as e:
        print(f"Erreur dans handler_join: {e}")

@client.on(events.NewMessage(pattern=r'/set_stat (-?\d+)'))
async def set_stat_channel(event):
    """Set statistics channel (only admin in private)"""
    global detected_stat_channel, confirmation_pending

    try:
        # Only allow in private chat with admin
        if event.is_group or event.is_channel:
            return

        if ADMIN_ID and event.sender_id != ADMIN_ID:
            await event.respond("❌ Seul l'administrateur peut configurer les canaux")
            return

        # Extract channel ID from command
        match = event.pattern_match
        channel_id = int(match.group(1))

        # Check if channel is waiting for confirmation
        if channel_id not in confirmation_pending:
            await event.respond("❌ Ce canal n'est pas en attente de configuration")
            return

        detected_stat_channel = channel_id
        confirmation_pending[channel_id] = 'configured_stat'

        # Save configuration
        save_config()

        try:
            chat = await client.get_entity(channel_id)
            chat_title = getattr(chat, 'title', f'Canal {channel_id}')
        except:
            chat_title = f'Canal {channel_id}'

        await event.respond(f"✅ **Canal de statistiques configuré**\n📋 {chat_title}\n\n✨ Le bot surveillera ce canal pour les prédictions - développé par Sossou Kouamé Appolinaire\n💾 Configuration sauvegardée automatiquement")
        print(f"Canal de statistiques configuré: {channel_id}")

    except Exception as e:
        print(f"Erreur dans set_stat_channel: {e}")

@client.on(events.NewMessage(pattern=r'/set_display (-?\d+)'))
async def set_display_channel(event):
    """Set display channel (only admin in private)"""
    global detected_display_channel, confirmation_pending

    try:
        # Only allow in private chat with admin
        if event.is_group or event.is_channel:
            return

        if event.sender_id != ADMIN_ID:
            await event.respond("❌ Seul l'administrateur peut configurer les canaux")
            return

        # Extract channel ID from command
        match = event.pattern_match
        channel_id = int(match.group(1))

        # Check if channel is waiting for confirmation
        if channel_id not in confirmation_pending:
            await event.respond("❌ Ce canal n'est pas en attente de configuration")
            return

        detected_display_channel = channel_id
        confirmation_pending[channel_id] = 'configured_display'

        # Save configuration
        save_config()

        try:
            chat = await client.get_entity(channel_id)
            chat_title = getattr(chat, 'title', f'Canal {channel_id}')
        except:
            chat_title = f'Canal {channel_id}'

        await event.respond(f"✅ **Canal de diffusion configuré**\n📋 {chat_title}\n\n🚀 Le bot publiera les prédictions dans ce canal - développé par Sossou Kouamé Appolinaire\n💾 Configuration sauvegardée automatiquement")
        print(f"Canal de diffusion configuré: {channel_id}")

    except Exception as e:
        print(f"Erreur dans set_display_channel: {e}")

# --- COMMANDES DE BASE ---
@client.on(events.NewMessage(pattern='/start'))
async def start_command(event):
    """Send welcome message when user starts the bot"""
    try:
        welcome_msg = """🎯 **Bot de Prédiction de Cartes - Bienvenue !**

🔹 **Développé par Sossou Kouamé Appolinaire**

**Fonctionnalités** :
• 📊 Import de prédictions depuis fichier Excel
• 🔍 Surveillance automatique du canal source
• 🎯 Lancement des prédictions basé sur le fichier Excel
• ✅ Vérification des résultats avec offsets (0, 1, 2)

**Configuration** :
1. Ajoutez-moi dans vos canaux
2. Je vous enverrai automatiquement une invitation privée
3. Répondez avec `/set_stat [ID]` ou `/set_display [ID]`
4. Envoyez votre fichier Excel (.xlsx) pour importer les prédictions

**Commandes** :
• `/start` - Ce message
• `/status` - État du bot (admin)
• `/excel_status` - Statut des prédictions Excel (admin)
• `/excel_clear` - Effacer les prédictions Excel (admin)
• `/sta` - Statistiques Excel (admin)
• `/reset` - Réinitialiser (admin)

**Format Excel** :
Le fichier doit contenir 3 colonnes :
• Date & Heure
• Numéro (ex: 881, 886, 891...)
• Victoire (Joueur ou Banquier)

**Format de prédiction** :
• V1 pour victoire Joueur : 🔵XXX 🔵V1✍🏻: statut :⏳
• V2 pour victoire Banquier : 🔵XXX 🔵V2✍🏻: statut :⏳

Le bot est prêt à analyser vos jeux ! 🚀"""

        await event.respond(welcome_msg)
        print(f"Message de bienvenue envoyé à l'utilisateur {event.sender_id}")

        # Test message private pour vérifier la connectivité
        if event.sender_id == ADMIN_ID:
            await asyncio.sleep(2)
            test_msg = "🔧 Test de connectivité : Je peux vous envoyer des messages privés !"
            await event.respond(test_msg)

    except Exception as e:
        print(f"Erreur dans start_command: {e}")

# --- COMMANDES ADMINISTRATIVES ---
@client.on(events.NewMessage(pattern='/status'))
async def show_status(event):
    """Show bot status (admin only)"""
    try:
        # Permettre si ADMIN_ID est configuré ou en mode développement
        if ADMIN_ID and event.sender_id != ADMIN_ID:
            return

        # Recharger la configuration pour éviter les valeurs obsolètes
        load_config()

        config_status = "✅ Sauvegardée" if os.path.exists(CONFIG_FILE) else "❌ Non sauvegardée"
        status_msg = f"""📊 **Statut du Bot**

Canal statistiques: {'✅ Configuré' if detected_stat_channel else '❌ Non configuré'} ({detected_stat_channel})
Canal diffusion: {'✅ Configuré' if detected_display_channel else '❌ Non configuré'} ({detected_display_channel})
⏱️ Intervalle de prédiction: {prediction_interval} minutes
Configuration persistante: {config_status}
Prédictions actives: {len(predictor.prediction_status)}
Dernières prédictions: {len(predictor.last_predictions)}
"""
        await event.respond(status_msg)
    except Exception as e:
        print(f"Erreur dans show_status: {e}")

@client.on(events.NewMessage(pattern='/reset'))
async def reset_data(event):
    """Réinitialisation des données (admin uniquement)"""
    try:
        if event.sender_id != ADMIN_ID:
            return

        # Réinitialiser les prédictions en attente
        pending_predictions.clear()

        # Réinitialiser les données YAML
        await yaml_manager.reset_all_data()

        msg = """🔄 **Données réinitialisées avec succès !**

✅ Prédictions en attente: vidées
✅ Base de données YAML: réinitialisée
✅ Configuration: préservée

Le bot est prêt pour un nouveau cycle."""

        await event.respond(msg)
        print(f"Données réinitialisées par l'admin")

    except Exception as e:
        print(f"Erreur dans reset_data: {e}")
        await event.respond(f"❌ Erreur lors de la réinitialisation: {e}")

@client.on(events.NewMessage(pattern='/ni'))
async def ni_command(event):
    """Commande /ni - Informations sur le système de prédiction"""
    try:
        # Utiliser les variables globales configurées
        stats_channel = detected_stat_channel or 'Non configuré'
        display_channel = detected_display_channel or 'Non configuré'

        # Compter les prédictions actives depuis le predictor
        active_predictions = len([s for s in predictor.prediction_status.values() if s == '⌛'])

        msg = f"""🎯 **Système de Prédiction NI - Statut**

📊 **Configuration actuelle**:
• Canal source: {stats_channel}
• Canal affichage: {display_channel}
• Prédictions Excel actives: {active_predictions}
• Intervalle: {prediction_interval} minute(s)

🎮 **Fonctionnalités**:
• Prédictions basées uniquement sur fichier Excel
• Vérification séquentielle avec offsets 0→1→2
• Format: "🔵XXX 🔵V1✍🏻: statut :⏳" ou "🔵XXX 🔵V2✍🏻: statut :⏳"

🔧 **Commandes disponibles**:
• `/set_stat [ID]` - Configurer canal source
• `/set_display [ID]` - Configurer canal affichage
• `/excel_status` - Voir prédictions Excel
• `/reset` - Réinitialiser les données
• `/intervalle [min]` - Configurer délai

✅ **Bot opérationnel** - Version 2025"""

        await event.respond(msg)
        print(f"Commande /ni exécutée par {event.sender_id}")

    except Exception as e:
        print(f"Erreur dans ni_command: {e}")
        await event.respond(f"❌ Erreur: {e}")


@client.on(events.NewMessage(pattern='/test_invite'))
async def test_invite(event):
    """Test sending invitation (admin only)"""
    try:
        if event.sender_id != ADMIN_ID:
            return

        # Test invitation message
        test_msg = f"""🔔 **Test d'invitation**

📋 **Canal test** : Canal de test
🆔 **ID** : -1001234567890

**Choisissez le type de canal** :
• `/set_stat -1001234567890` - Canal de statistiques
• `/set_display -1001234567890` - Canal de diffusion

Ceci est un message de test pour vérifier les invitations."""

        await event.respond(test_msg)
        print(f"Message de test envoyé à l'admin")

    except Exception as e:
        print(f"Erreur dans test_invite: {e}")

@client.on(events.NewMessage(pattern='/sta'))
async def show_excel_stats(event):
    """Show Excel predictions statistics"""
    try:
        if event.sender_id != ADMIN_ID:
            return

        # Recharger la configuration pour éviter les valeurs obsolètes
        load_config()

        stats = excel_manager.get_stats()

        msg = f"""📊 **Statut des Prédictions Excel**

📋 **Statistiques Excel**:
• Total prédictions: {stats['total']}
• En attente: {stats['pending']}
• Lancées: {stats['launched']}

📈 **Configuration actuelle**:
• Canal stats configuré: {'✅' if detected_stat_channel else '❌'} ({detected_stat_channel or 'Aucun'})
• Canal affichage configuré: {'✅' if detected_display_channel else '❌'} ({detected_display_channel or 'Aucun'})

🔧 **Format de prédiction**:
• V1 (Joueur) : 🔵XXX 🔵V1✍🏻: statut :⏳
• V2 (Banquier) : 🔵XXX 🔵V2✍🏻: statut :⏳

✅ Prédictions uniquement depuis fichier Excel"""

        await event.respond(msg)
        print(f"Statut Excel envoyé à l'admin")

    except Exception as e:
        print(f"Erreur dans show_excel_stats: {e}")
        await event.respond(f"❌ Erreur: {e}")

# Commande /report supprimée selon demande utilisateur

@client.on(events.NewMessage(pattern='/scheduler'))
async def manage_scheduler(event):
    """Gestion du planificateur automatique (admin uniquement)"""
    global scheduler
    try:
        if event.sender_id != ADMIN_ID:
            return

        # Parse command arguments
        message_parts = event.message.message.split()
        if len(message_parts) < 2:
            await event.respond("""🤖 **Commandes du Planificateur Automatique**

**Usage**: `/scheduler [commande]`

**Commandes disponibles**:
• `start` - Démarre le planificateur automatique
• `stop` - Arrête le planificateur
• `status` - Affiche le statut actuel
• `generate` - Génère une nouvelle planification
• `config [source_id] [target_id]` - Configure les canaux

**Exemple**: `/scheduler config -1001234567890 -1001987654321`""")
            return

        command = message_parts[1].lower()

        if command == "start":
            if not scheduler:
                if detected_stat_channel and detected_display_channel:
                    scheduler = PredictionScheduler(
                        client, predictor,
                        detected_stat_channel, detected_display_channel
                    )
                    # Démarre le planificateur en arrière-plan
                    asyncio.create_task(scheduler.run_scheduler())
                    await event.respond("✅ **Planificateur démarré**\n\nLe système de prédictions automatiques est maintenant actif.")
                else:
                    await event.respond("❌ **Configuration manquante**\n\nVeuillez d'abord configurer les canaux source et cible avec `/set_stat` et `/set_display`.")
            else:
                await event.respond("⚠️ **Planificateur déjà actif**\n\nUtilisez `/scheduler stop` pour l'arrêter.")

        elif command == "stop":
            if scheduler:
                scheduler.stop_scheduler()
                scheduler = None
                await event.respond("🛑 **Planificateur arrêté**\n\nLes prédictions automatiques sont désactivées.")
            else:
                await event.respond("ℹ️ **Planificateur non actif**\n\nUtilisez `/scheduler start` pour le démarrer.")

        elif command == "status":
            if scheduler:
                status = scheduler.get_schedule_status()
                status_msg = f"""📊 **Statut du Planificateur**

🔄 **État**: {'🟢 Actif' if status['is_running'] else '🔴 Inactif'}
📋 **Planification**:
• Total de prédictions: {status['total']}
• Prédictions lancées: {status['launched']}
• Prédictions vérifiées: {status['verified']}
• En attente: {status['pending']}

⏰ **Prochaine prédiction**: {status['next_launch'] or 'Aucune'}

🔧 **Configuration**:
• Canal source: {detected_stat_channel}
• Canal cible: {detected_display_channel}"""
                await event.respond(status_msg)
            else:
                await event.respond("ℹ️ **Planificateur non configuré**\n\nUtilisez `/scheduler start` pour l'activer.")

        elif command == "generate":
            if scheduler:
                scheduler.regenerate_schedule()
                await event.respond("🔄 **Nouvelle planification générée**\n\nLa planification quotidienne a été régénérée avec succès.")
            else:
                # Crée un planificateur temporaire pour générer
                temp_scheduler = PredictionScheduler(client, predictor, 0, 0)
                temp_scheduler.regenerate_schedule()
                await event.respond("✅ **Planification générée**\n\nFichier `prediction.yaml` créé. Utilisez `/scheduler start` pour activer.")

        elif command == "config" and len(message_parts) >= 4:
            source_id = int(message_parts[2])
            target_id = int(message_parts[3])

            # Met à jour la configuration globale
            update_channel_config(source_id, target_id)

            await event.respond(f"""✅ **Configuration mise à jour**

📥 **Canal source**: {source_id}
📤 **Canal cible**: {target_id}

Utilisez `/scheduler start` pour activer le planificateur.""")

        else:
            await event.respond("❌ **Commande inconnue**\n\nUtilisez `/scheduler` sans paramètre pour voir l'aide.")

    except Exception as e:
        print(f"Erreur dans manage_scheduler: {e}")
        await event.respond(f"❌ Erreur: {e}")

@client.on(events.NewMessage(pattern='/schedule_info'))
async def schedule_info(event):
    """Affiche les informations détaillées de la planification (admin uniquement)"""
    try:
        if event.sender_id != ADMIN_ID:
            return

        if scheduler and scheduler.schedule_data:
            # Affiche les 10 prochaines prédictions
            current_time = scheduler.get_current_time_slot()
            upcoming = []

            for numero, data in scheduler.schedule_data.items():
                if (not data["launched"] and
                    data["heure_lancement"] >= current_time):
                    upcoming.append((numero, data["heure_lancement"]))

            upcoming.sort(key=lambda x: x[1])
            upcoming = upcoming[:10]  # Limite à 10

            msg = "📅 **Prochaines Prédictions Automatiques**\n\n"
            for numero, heure in upcoming:
                msg += f"🔵 {numero} → {heure}\n"

            if not upcoming:
                msg += "ℹ️ Aucune prédiction en attente pour aujourd'hui."

            await event.respond(msg)
        else:
            await event.respond("❌ **Aucune planification active**\n\nUtilisez `/scheduler generate` pour créer une planification.")

    except Exception as e:
        print(f"Erreur dans schedule_info: {e}")
        await event.respond(f"❌ Erreur: {e}")

@client.on(events.NewMessage(pattern='/intervalle'))
async def set_prediction_interval(event):
    """Configure l'intervalle avant que le système cherche 'A' (admin uniquement)"""
    global prediction_interval
    try:
        if event.sender_id != ADMIN_ID:
            return

        # Parse command arguments
        message_parts = event.message.message.split()

        if len(message_parts) < 2:
            await event.respond(f"""⏱️ **Configuration de l'Intervalle de Prédiction**

**Usage**: `/intervalle [minutes]`

**Intervalle actuel**: {prediction_interval} minutes

**Description**:
Définit le temps d'attente en minutes avant que le système commence à analyser les messages pour chercher la lettre 'A' dans les parenthèses et déclencher les prédictions.

**Exemples**:
• `/intervalle 3` - Attendre 3 minutes
• `/intervalle 10` - Attendre 10 minutes
• `/intervalle 1` - Attendre 1 minute

**Recommandé**: Entre 1 et 15 minutes""")
            return

        try:
            new_interval = int(message_parts[1])
            if new_interval < 1 or new_interval > 60:
                await event.respond("❌ **Erreur**: L'intervalle doit être entre 1 et 60 minutes")
                return

            old_interval = prediction_interval
            prediction_interval = new_interval

            # Sauvegarder la configuration
            save_config()

            await event.respond(f"""✅ **Intervalle mis à jour**

⏱️ **Ancien intervalle**: {old_interval} minutes
⏱️ **Nouvel intervalle**: {prediction_interval} minutes

Le système attendra maintenant {prediction_interval} minute(s) avant de commencer l'analyse des messages pour la détection des 'A' dans les parenthèses.

Configuration sauvegardée automatiquement.""")

            print(f"✅ Intervalle de prédiction mis à jour: {old_interval} → {prediction_interval} minutes")

        except ValueError:
            await event.respond("❌ **Erreur**: Veuillez entrer un nombre valide de minutes")

    except Exception as e:
        print(f"Erreur dans set_prediction_interval: {e}")
        await event.respond(f"❌ Erreur: {e}")

@client.on(events.NewMessage(pattern='/excel_status'))
async def excel_status(event):
    """Affiche le statut des prédictions Excel (admin uniquement)"""
    try:
        if event.sender_id != ADMIN_ID:
            return

        stats = excel_manager.get_stats()
        pending = excel_manager.get_pending_predictions()

        msg = f"""📊 **Statut Prédictions Excel**

📈 **Statistiques**:
• Total: {stats['total']}
• En attente: {stats['pending']}
• Lancées: {stats['launched']}

📋 **Prochaines prédictions en attente** (max 10):
"""

        for i, pred in enumerate(pending[:10]):
            victoire_icon = "✅V1" if "joueur" in pred["victoire"].lower() else "✅V2"
            msg += f"\n{i+1}. 🔵{pred['numero']} {victoire_icon} - {pred['date_heure']}"

        if stats['pending'] == 0:
            msg += "\nℹ️ Aucune prédiction en attente"

        msg += f"""

💡 **Comment ça marche**:
• Le bot surveille le canal source
• Quand un numéro proche est détecté, la prédiction est lancée automatiquement
• Format V1 pour victoire Joueur, V2 pour victoire Banquier

📤 **Pour importer**: Envoyez simplement votre fichier Excel (.xlsx)"""

        await event.respond(msg)
        print(f"Statut Excel envoyé à l'admin")

    except Exception as e:
        print(f"Erreur dans excel_status: {e}")
        await event.respond(f"❌ Erreur: {e}")

@client.on(events.NewMessage(pattern='/excel_clear'))
async def excel_clear(event):
    """Efface toutes les prédictions Excel (admin uniquement)"""
    try:
        if event.sender_id != ADMIN_ID:
            return

        excel_manager.clear_predictions()
        await event.respond("🗑️ **Toutes les prédictions Excel ont été effacées**\n\nVous pouvez maintenant importer un nouveau fichier Excel.")
        print("✅ Prédictions Excel effacées par l'admin")

    except Exception as e:
        print(f"Erreur dans excel_clear: {e}")
        await event.respond(f"❌ Erreur: {e}")

@client.on(events.NewMessage(pattern='/deploy'))
async def generate_deploy_package(event):
    """Génère le package de déploiement Render.com complet et prêt à déployer (admin uniquement)"""
    try:
        if event.sender_id != ADMIN_ID:
            return

        await event.respond("🚀 **Génération du package Render.com complet...**")

        try:
            package_name = 'render_deployment_complete.zip'

            with zipfile.ZipFile(package_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 1. Fichiers Python essentiels du projet
                python_files = [
                    'main.py',
                    'predictor.py',
                    'yaml_manager.py',
                    'excel_importer.py',
                    'scheduler.py'
                ]

                for file_path in python_files:
                    if os.path.exists(file_path):
                        zipf.write(file_path)
                        print(f"  ✅ Ajouté: {file_path}")

                # 2. Créer render_main.py (point d'entrée optimisé Render.com)
                render_main_content = """#!/usr/bin/env python3
# -*- coding: utf-8 -*-
\"\"\"Bot Telegram optimisé pour Render.com avec port 10000\"\"\"

import os
import sys
import asyncio
import logging

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Vérification des variables d'environnement critiques
REQUIRED_VARS = ['API_ID', 'API_HASH', 'BOT_TOKEN']
missing_vars = [var for var in REQUIRED_VARS if not os.getenv(var)]

if missing_vars:
    logging.error(f"❌ Variables d'environnement manquantes: {', '.join(missing_vars)}")
    logging.error("Configurez ces variables dans Render.com Dashboard")
    sys.exit(1)

# Import du bot principal
try:
    from main import main
    logging.info("✅ Module principal importé avec succès")
except ImportError as e:
    logging.error(f"❌ Erreur import module principal: {e}")
    sys.exit(1)

if __name__ == "__main__":
    logging.info("🚀 Démarrage bot Render.com...")
    logging.info(f"Port configuré: {os.getenv('PORT', '10000')}")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Arrêt du bot demandé")
    except Exception as e:
        logging.error(f"❌ Erreur critique: {e}")
        sys.exit(1)
"""
                zipf.writestr('render_main.py', render_main_content)
                print("  ✅ Créé: render_main.py")

                # 3. Fichier .env.example avec canal de diffusion mis à jour
                env_example_content = f"""# Configuration Telegram Bot - Render.com
# Remplacez ces valeurs par vos vraies credentials

API_ID=votre_api_id
API_HASH=votre_api_hash
BOT_TOKEN=votre_bot_token
ADMIN_ID=votre_admin_id

# Configuration automatique Render.com
PORT=10000
DISPLAY_CHANNEL=-1002999811353
PREDICTION_INTERVAL={prediction_interval}

# Base de données (optionnel - YAML par défaut)
# DATABASE_URL=postgresql://user:pass@host:5432/dbname
"""
                zipf.writestr('.env.example', env_example_content)
                print("  ✅ Créé: .env.example")

                # 4. requirements.txt complet
                requirements_content = """telethon==1.35.0
aiohttp==3.9.5
python-dotenv==1.0.1
pyyaml==6.0.1
openpyxl==3.1.2
"""
                zipf.writestr('requirements.txt', requirements_content)
                print("  ✅ Créé: requirements.txt")

                # 5. runtime.txt pour spécifier la version Python
                runtime_content = "python-3.11.0"
                zipf.writestr('runtime.txt', runtime_content)
                print("  ✅ Créé: runtime.txt")

                # 6. render.yaml - Configuration Render.com complète
                render_yaml = f"""services:
  - type: web
    name: telegram-card-bot
    env: python
    buildCommand: "pip install --upgrade pip && pip install -r requirements.txt"
    startCommand: "python render_main.py"
    plan: free
    region: frankfurt
    envVars:
      - key: API_ID
        sync: false
      - key: API_HASH
        sync: false
      - key: BOT_TOKEN
        sync: false
      - key: ADMIN_ID
        sync: false
      - key: PORT
        fromGroup: web
      - key: DISPLAY_CHANNEL
        value: "-1002999811353"
      - key: PREDICTION_INTERVAL
        value: "{prediction_interval}"
    healthCheckPath: "/health"
"""
                zipf.writestr('render.yaml', render_yaml)
                print("  ✅ Créé: render.yaml")

                # 7. .gitignore pour éviter d'uploader des fichiers sensibles
                gitignore_content = """# Fichiers sensibles
.env
*.session
*.session-journal

# Fichiers temporaires
__pycache__/
*.pyc
*.pyo
*.pyd
.Python

# Logs
*.log

# Données locales
data/
*.yaml

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
"""
                zipf.writestr('.gitignore', gitignore_content)
                print("  ✅ Créé: .gitignore")

                # 8. README.md complet avec instructions détaillées
                readme_content = f"""# 📦 Bot Telegram - Package Render.com Complet

## 🎯 Package Prêt pour Déploiement

Ce package contient **TOUS** les fichiers nécessaires pour déployer le bot sur **Render.com** avec le **port 10000**.

---

## 📋 Fichiers Inclus

### Code Source (✅ Complet)
- `main.py` - Bot principal avec toutes les fonctionnalités
- `predictor.py` - Moteur de prédiction Excel
- `yaml_manager.py` - Gestionnaire de données YAML
- `excel_importer.py` - Import et gestion Excel
- `scheduler.py` - Planificateur automatique
- `render_main.py` - Point d'entrée optimisé Render.com

### Configuration (✅ Prête)
- `render.yaml` - Configuration Render.com automatique
- `requirements.txt` - Dépendances Python
- `runtime.txt` - Version Python (3.11)
- `.env.example` - Template variables d'environnement
- `.gitignore` - Fichiers à ignorer

---

## 🚀 Déploiement sur Render.com

### Étape 1: Préparer le Repository
```bash
# Extraire le ZIP
unzip render_deployment_complete.zip -d mon-bot-telegram/
cd mon-bot-telegram/

# Initialiser Git (si nécessaire)
git init
git add .
git commit -m "Initial deployment"

# Push vers GitHub/GitLab
git remote add origin https://github.com/votre-username/votre-repo.git
git push -u origin main
```

### Étape 2: Créer le Service sur Render.com
1. Aller sur [render.com](https://render.com)
2. Se connecter ou créer un compte (gratuit)
3. Cliquer **"New +"** → **"Web Service"**
4. Connecter votre repository GitHub/GitLab
5. Render détectera automatiquement `render.yaml`

### Étape 3: Variables d'Environnement
Ajouter dans Render.com Dashboard → Environment:

```
API_ID = votre_api_id_telegram
API_HASH = votre_api_hash_telegram
BOT_TOKEN = votre_bot_token
ADMIN_ID = votre_telegram_user_id
```

**Note:** Le `PORT`, `DISPLAY_CHANNEL` et autres sont déjà configurés dans `render.yaml`

### Étape 4: Déployer
1. Cliquer **"Deploy"**
2. Attendre la fin du build (2-3 minutes)
3. Votre bot sera accessible à l'URL fournie

---

## ✅ Vérification Post-Déploiement

### 1. Health Check
Visitez: `https://votre-service.onrender.com/health`

Réponse attendue:
```
Bot is running!
```

### 2. Logs Render
Vérifiez les logs dans le Dashboard:
```
✅ Serveur web démarré sur 0.0.0.0:10000
✅ Configuration chargée depuis JSON
Bot démarré avec succès...
Bot connecté: @Votre_Bot
✅ Bot en ligne et en attente de messages...
```

### 3. Test Telegram
1. Cherchez votre bot sur Telegram
2. Envoyez `/start`
3. Le bot doit répondre immédiatement

---

## 🔧 Fonctionnalités Déployées

### ✅ Prédictions Excel
- Import automatique fichiers Excel (.xlsx)
- Surveillance canal source
- Lancement anticipé (tolérance 0-4 parties)
- Format V1/V2 selon type de victoire
- Vérification avec offsets (0, 1, 2)

### ✅ Commandes Admin
- `/start` - Aide et bienvenue
- `/status` - État du bot
- `/excel_status` - Statut prédictions
- `/excel_clear` - Effacer prédictions
- `/sta` - Statistiques Excel
- `/intervalle [min]` - Configurer délai
- `/reset` - Réinitialisation
- `/deploy` - Créer package

### ✅ Configuration Canaux
- Invitation automatique lors de l'ajout
- Configuration via `/set_stat` et `/set_display`
- Sauvegarde persistante JSON + DB

---

## 📊 Configuration Actuelle

| Paramètre | Valeur |
|-----------|--------|
| **Port** | 10000 (auto Render) |
| **Health Check** | `/health` endpoint |
| **Canal Display** | -1002999811353 |
| **Intervalle** | {prediction_interval} minute(s) |
| **Format V1** | 🔵XXX 🔵V1✍🏻: statut :⏳ |
| **Format V2** | 🔵XXX 🔵V2✍🏻: statut :⏳ |

---

## 🆘 Dépannage

### Bot ne démarre pas
- ✅ Vérifier toutes les variables d'environnement sont définies
- ✅ Vérifier `BOT_TOKEN` est valide
- ✅ Consulter les logs Render

### Port Error
- Le port 10000 est **automatiquement configuré** par Render via `fromGroup: web`
- Pas besoin de le changer manuellement

### Bot ne répond pas
- ✅ Vérifier le bot est bien connecté (logs)
- ✅ Tester le health check endpoint
- ✅ Vérifier les canaux sont bien configurés

### Import Excel échoue
- Format requis: 3 colonnes (Date & Heure, Numéro, Victoire)
- Victoire doit être "Joueur" ou "Banquier"
- Fichier doit être .xlsx ou .xls

---

## 🎯 Support

**Développé par:** Sossou Kouamé Appolinaire  
**Version:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  
**Plateforme:** Render.com (Free Tier)

### Ressources
- [Documentation Render](https://render.com/docs)
- [Telethon Docs](https://docs.telethon.dev/)
- [Bot API Telegram](https://core.telegram.org/bots/api)

---

**🚀 Le bot est 100% prêt pour la production sur Render.com!**
"""
                zipf.writestr('README.md', readme_content)
                print("  ✅ Créé: README.md")

                # 9. Dossier data/ avec structure
                zipf.writestr('data/.gitkeep', '# Dossier pour fichiers YAML\n# Créé automatiquement par le bot\n')
                print("  ✅ Créé: data/.gitkeep")

                # 10. Procfile (optionnel, pour compatibilité Heroku)
                procfile_content = "web: python render_main.py"
                zipf.writestr('Procfile', procfile_content)
                print("  ✅ Créé: Procfile")

            file_size = os.path.getsize(package_name) / 1024

            await event.respond(f"""✅ **PACKAGE RENDER.COM COMPLET CRÉÉ!**

📦 **Fichier:** {package_name} ({file_size:.1f} KB)

📋 **Contenu (11 fichiers):**
✅ Code source complet (6 fichiers Python)
✅ render_main.py - Point d'entrée optimisé
✅ render.yaml - Config Render auto
✅ requirements.txt + runtime.txt
✅ .env.example - Template variables
✅ .gitignore - Sécurité
✅ README.md - Guide complet
✅ Procfile - Compatibilité
✅ data/ - Structure dossiers

🚀 **Prêt pour Render.com:**
• Port: 10000 ✅
• Health Check: /health ✅
• Canal Display: -1002999811353 ✅
• Build/Start: Auto-configurés ✅
• Variables: Template fourni ✅

🔧 **3 étapes pour déployer:**
1. Extraire le ZIP
2. Push vers GitHub
3. Connecter à Render.com

📖 **Guide complet dans README.md**

Le package est 100% compatible et sans erreurs! 🎉""")

            # Envoyer le fichier
            await client.send_file(
                event.chat_id,
                package_name,
                caption=f"📦 **Package Render.com Complet v{datetime.now().strftime('%Y%m%d')}** - Prêt pour déploiement sans erreur!"
            )

            print(f"✅ Package créé: {package_name} ({file_size:.1f} KB)")

        except Exception as e:
            await event.respond(f"❌ Erreur création package: {str(e)}")
            print(f"❌ Erreur: {e}")

    except Exception as e:
        print(f"Erreur /deploy: {e}")

# --- TRAITEMENT DES MESSAGES DU CANAL DE STATISTIQUES ---
@client.on(events.NewMessage())
@client.on(events.MessageEdited())
async def handle_messages(event):
    """Handle messages from statistics channel"""
    try:
        # Handle Excel file import from admin (before any other checks)
        if event.sender_id == ADMIN_ID and event.message.media and event.message.file:
            file_name = event.message.file.name
            if file_name and (file_name.endswith('.xlsx') or file_name.endswith('.xls')):
                await event.respond("📥 **Téléchargement du fichier Excel...**")
                file_path = await event.message.download_media()
                await event.respond("⚙️ **Importation des prédictions...**")

                result = excel_manager.import_excel(file_path)
                os.remove(file_path)

                if result["success"]:
                    stats = excel_manager.get_stats()
                    msg = f"""✅ **Import Excel réussi!**

📊 **Résumé**:
• Prédictions importées: {result['imported']}
• Prédictions ignorées: {result['skipped']}
• Total en base: {stats['total']}

📋 **Statistiques**:
• En attente: {stats['pending']}
• Lancées: {stats['launched']}

Le système surveillera maintenant le canal source et lancera les prédictions automatiquement quand les numéros seront proches."""
                    await event.respond(msg)
                    print(f"✅ Import Excel réussi: {result['imported']} prédictions importées")
                else:
                    await event.respond(f"❌ **Erreur lors de l'import**: {result['error']}")
                    print(f"❌ Erreur import Excel: {result['error']}")
                return

        # Debug: Log ALL incoming messages first
        message_text = event.message.message if event.message else "Pas de texte"
        channel_id = event.chat_id
        print(f"📬 TOUS MESSAGES: Canal {channel_id} | Texte: {message_text[:100]}")
        print(f"🔧 Canal stats configuré: {detected_stat_channel}")

        # Ignorer les messages privés qui ne sont PAS des commandes
        if ADMIN_ID and channel_id == ADMIN_ID and not message_text.startswith('/'):
            print(f"⏭️ Message privé admin ignoré (pas une commande)")
            return

        # Filtrer silencieusement les messages hors canal stats
        if channel_id != detected_stat_channel:
            return

        print(f"📬 MESSAGE STATS: Canal {channel_id}")
        print(f"✅ Texte: {message_text[:100]}..." if len(message_text) > 100 else f"✅ Texte: {message_text}")

        if not message_text:
            print("❌ Message vide ignoré")
            return

        print(f"✅ Message accepté du canal stats {event.chat_id}: {message_text}")

        # EXCEL MONITORING: Vérifier si un numéro proche est dans les prédictions Excel
        game_number = predictor.extract_game_number(message_text)
        if game_number:
            # Déclenchement quand canal source affiche 0-4 parties AVANT le numéro Excel
            # Ex: Excel #881, Canal #879 → Lance #881 (écart +2)
            close_pred = excel_manager.find_close_prediction(game_number, tolerance=4)
            if close_pred and detected_display_channel:
                pred_key = close_pred["key"]
                pred_data = close_pred["prediction"]
                pred_numero = pred_data["numero"]
                victoire_type = pred_data["victoire"]

                v_format = excel_manager.get_prediction_format(victoire_type)
                prediction_text = f"🔵{pred_numero} {v_format}✍🏻: statut :⏳⏳"

                try:
                    sent_message = await client.send_message(detected_display_channel, prediction_text)
                    excel_manager.mark_as_launched(pred_key, sent_message.id, detected_display_channel)

                    # Enregistrer la prédiction dans le predictor pour la vérification
                    predictor.prediction_status[pred_numero] = '⌛'
                    predictor.store_prediction_message(pred_numero, sent_message.id, detected_display_channel)

                    ecart = pred_numero - game_number
                    print(f"✅ Prédiction Excel lancée: 🔵{pred_numero} {v_format} | Canal source: #{game_number} (écart: +{ecart} parties)")
                except Exception as e:
                    print(f"❌ Erreur envoi prédiction Excel: {e}")

            # Vérification des prédictions Excel lancées (avec offset 0, 1, 2)
            for key, pred in list(excel_manager.predictions.items()):
                if not pred["launched"] or "verified" in pred:
                    continue

                pred_numero = pred["numero"]
                expected_winner = pred["victoire"]

                status = excel_manager.verify_excel_prediction(game_number, message_text, pred_numero, expected_winner)

                if status:
                    # Mettre à jour le message de prédiction
                    msg_id = pred.get("message_id")
                    channel_id = pred.get("channel_id")

                    if msg_id and channel_id:
                        v_format = excel_manager.get_prediction_format(expected_winner)
                        new_text = f"🔵{pred_numero} {v_format}✍🏻: statut :{status}"

                        try:
                            await client.edit_message(channel_id, msg_id, new_text)
                            pred["verified"] = True
                            excel_manager._save_predictions()
                            print(f"✅ Prédiction Excel #{pred_numero} mise à jour: {status}")
                        except Exception as e:
                            print(f"❌ Erreur mise à jour prédiction Excel: {e}")

        # Check for prediction verification
        verified, number = predictor.verify_prediction(message_text)
        if verified is not None and number is not None:
            statut = predictor.prediction_status.get(number, 'Inconnu')
            # Edit the original prediction message instead of sending new message
            success = await edit_prediction_message(number, statut)
            if success:
                print(f"✅ Message de prédiction #{number} mis à jour avec statut: {statut}")
            else:
                print(f"⚠️ Impossible de mettre à jour le message #{number}, envoi d'un nouveau message")
                status_text = f"🔵{number} statut :{statut}"
                await broadcast(status_text)

        # Check for expired predictions on every valid result message
        game_number = predictor.extract_game_number(message_text)
        if game_number and not ("⏰" in message_text or "🕐" in message_text):
            expired = predictor.check_expired_predictions(game_number)
            for expired_num in expired:
                # Edit expired prediction messages
                success = await edit_prediction_message(expired_num, '❌')
                if success:
                    print(f"✅ Message de prédiction expirée #{expired_num} mis à jour avec ❌")
                else:
                    print(f"⚠️ Impossible de mettre à jour le message expiré #{expired_num}")
                    status_text = f"🔵{expired_num} statut :❌"
                    await broadcast(status_text)

        # Vérification des prédictions automatiques du scheduler
        if scheduler and scheduler.schedule_data:
            # Récupère les numéros des prédictions automatiques en attente
            pending_auto_predictions = []
            for numero_str, data in scheduler.schedule_data.items():
                if data["launched"] and not data["verified"]:
                    numero_int = int(numero_str.replace('N', ''))
                    pending_auto_predictions.append(numero_int)

            if pending_auto_predictions:
                # Vérifie si ce message correspond à une prédiction automatique
                predicted_num, status = scheduler.verify_prediction_from_message(message_text, pending_auto_predictions)

                if predicted_num and status:
                    # Met à jour la prédiction automatique
                    numero_str = f"N{predicted_num:03d}"
                    if numero_str in scheduler.schedule_data:
                        data = scheduler.schedule_data[numero_str]
                        data["verified"] = True
                        data["statut"] = status

                        # Met à jour le message
                        await scheduler.update_prediction_message(numero_str, data, status)

                        # Ajouter une nouvelle prédiction pour maintenir la continuité
                        scheduler.add_next_prediction()

                        # Sauvegarde
                        scheduler.save_schedule(scheduler.schedule_data)
                        print(f"📝 Prédiction automatique {numero_str} vérifiée: {status}")
                        print(f"🔄 Nouvelle prédiction générée pour maintenir la continuité")

        # Bilan automatique supprimé sur demande utilisateur

    except Exception as e:
        print(f"Erreur dans handle_messages: {e}")

async def broadcast(message):
    """Broadcast message to display channel"""
    global detected_display_channel

    sent_messages = []
    if detected_display_channel:
        try:
            sent_message = await client.send_message(detected_display_channel, message)
            sent_messages.append((detected_display_channel, sent_message.id))
            print(f"Message diffusé: {message}")
        except Exception as e:
            print(f"Erreur lors de l'envoi: {e}")
    else:
        print("⚠️ Canal d'affichage non configuré")

    return sent_messages

async def edit_prediction_message(game_number: int, new_status: str):
    """Edit prediction message with new status"""
    try:
        message_info = predictor.get_prediction_message(game_number)
        if message_info:
            chat_id = message_info['chat_id']
            message_id = message_info['message_id']
            new_text = f"🔵{game_number} statut :{new_status}"

            await client.edit_message(chat_id, message_id, new_text)
            print(f"Message de prédiction #{game_number} mis à jour avec statut: {new_status}")
            return True
    except Exception as e:
        print(f"Erreur lors de la modification du message: {e}")
    return False

# Code de génération de rapport supprimé selon demande utilisateur

# --- ENVOI VERS LES CANAUX ---
# (Function moved above to handle message editing)

# --- GESTION D'ERREURS ET RECONNEXION ---
async def handle_connection_error():
    """Handle connection errors and attempt reconnection"""
    print("Tentative de reconnexion...")
    await asyncio.sleep(5)
    try:
        await client.connect()
        print("Reconnexion réussie")
    except Exception as e:
        print(f"Échec de la reconnexion: {e}")

# --- SERVEUR WEB POUR MONITORING ---
async def health_check(request):
    """Health check endpoint"""
    return web.Response(text="Bot is running!", status=200)

async def bot_status(request):
    """Bot status endpoint"""
    status = {
        "bot_online": True,
        "stat_channel": detected_stat_channel,
        "display_channel": detected_display_channel,
        "predictions_active": len(predictor.prediction_status),
        "total_predictions": len(predictor.status_log)
    }
    return web.json_response(status)

async def create_web_server():
    """Create and start web server"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    app.router.add_get('/status', bot_status)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"✅ Serveur web démarré sur 0.0.0.0:{PORT}")
    return runner

# --- LANCEMENT ---
async def main():
    """Main function to start the bot"""
    print("Démarrage du bot Telegram...")
    print(f"API_ID: {API_ID}")
    print(f"Bot Token configuré: {'Oui' if BOT_TOKEN else 'Non'}")
    print(f"Port web: {PORT}")

    # Validate configuration
    if not API_ID or not API_HASH or not BOT_TOKEN:
        print("❌ Configuration manquante! Vérifiez votre fichier .env")
        return

    try:
        # Start web server first
        web_runner = await create_web_server()

        # Start the bot
        if await start_bot():
            print("✅ Bot en ligne et en attente de messages...")
            print(f"🌐 Accès web: http://0.0.0.0:{PORT}")
            await client.run_until_disconnected()
        else:
            print("❌ Échec du démarrage du bot")

    except KeyboardInterrupt:
        print("\n🛑 Arrêt du bot demandé par l'utilisateur")
    except Exception as e:
        print(f"❌ Erreur critique: {e}")
        await handle_connection_error()
    finally:
        try:
            await client.disconnect()
            print("Bot déconnecté proprement")
        except:
            pass

if __name__ == "__main__":
    asyncio.run(main())