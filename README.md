# 📦 Bot Telegram - Package  Complet

## 🎯 Package Prêt pour Déploiement

Ce package contient **TOUS** les fichiers nécessaires pour déployer le bot sur ***.

---

## 📋 Fichiers Inclus

### Code Source (✅ Complet)
- `main.py` - Bot principal avec toutes les fonctionnalités
- `predictor.py` - Moteur de prédiction Excel
- `yaml_manager.py` - Gestionnaire de données YAML
- `excel_importer.py` - Import et gestion Excel

### Configuration (✅ Prête)
- `.replit` - Configuration Replit
- `replit.nix` - Dépendances système
- `requirements.txt` - Dépendances Python
- `.env.example` - Template variables d'environnement
- `.gitignore` - Fichiers à ignorer

---

## 🚀 Déploiement sur Replit

### Étape 1: Créer un nouveau Repl
1. Aller sur [replit.com](https://replit.com)
2. Créer un nouveau Repl Python
3. Uploader tous les fichiers du ZIP

### Étape 2: Configurer les Secrets
1. Cliquer sur l'icône "🔒 Secrets" dans le panneau de gauche
2. Ajouter ces variables:
```
API_ID = votre_api_id_telegram
API_HASH = votre_api_hash_telegram
BOT_TOKEN = votre_bot_token
ADMIN_ID = votre_telegram_user_id
```

### Étape 3: Lancer le Bot
1. Cliquer sur le bouton **Run** vert en haut
2. Le bot démarrera automatiquement
3. Vérifier les logs pour confirmation

---

## 🔧 Fonctionnalités Déployées

### ✅ Prédictions Excel Automatiques
- Import fichiers Excel (.xlsx)
- Surveillance du canal source
- Lancement anticipé (tolérance 0-4 parties)
- **Filtrage automatique des numéros consécutifs**
- Format V1 (Joueur) / V2 (Banquier)
- Vérification avec offsets (0, 1, 2)

### 📋 Format des Messages de Prédiction

**Au lancement:**
- Victoire Joueur: `🔵XXX 🔵V1✍🏻: statut :⏳⏳`
- Victoire Banquier: `🔵XXX 🔵V2✍🏻: statut :⏳⏳`

**Après vérification:**
- Exact (offset 0): `🔵XXX 🔵V1✍🏻: statut :✅0️⃣`
- Offset +1: `🔵XXX 🔵V1✍🏻: statut :✅1️⃣`
- Offset +2: `🔵XXX 🔵V1✍🏻: statut :✅2️⃣`
- Échec: `🔵XXX 🔵V1✍🏻: statut :⭕✍🏻`

### ✅ Commandes Admin
- `/start` - Aide et bienvenue
- `/status` - État du bot
- `/excel_status` - Statut prédictions Excel
- `/excel_clear` - Effacer prédictions
- `/sta` - Statistiques Excel
- `/intervalle [min]` - Configurer délai
- `/reset` - Réinitialisation
- `/deploy` - Créer package

---

## 📊 Configuration Actuelle

| Paramètre | Valeur |
|-----------|--------|
| **Port** | 10000 |
| **Canal Display** | -1002999811353 |
| **Intervalle** | 1 minute(s) |
| **Format V1** | 🔵XXX 🔵V1✍🏻: statut :⏳⏳ |
| **Format V2** | 🔵XXX 🔵V2✍🏻: statut :⏳⏳ |

---

## 📥 Format Excel Requis

| Date & Heure | Numéro | Victoire (Joueur/Banquier) |
|--------------|--------|----------------------------|
| 03/01/2025 - 14:20 | 881 | Banquier |
| 03/01/2025 - 14:26 | 886 | Joueur |
| 03/01/2025 - 14:40 | 891 | Joueur |

**Note:** Les numéros consécutifs (ex: 23→24) sont automatiquement filtrés à l'import.

---

## 🎯 Support

**Développé par:** Sossou Kouamé Appolinaire  
**Version:** 2025-10-04 05:38  
**Plateforme:** Replit

**🚀 Le bot est 100% prêt pour !**
