# 📦 Package Render.com - Bot Telegram

## 🎯 Package Optimisé Render.com

Ce package contient tous les fichiers pour déployer le bot sur **Render.com** avec le **PORT 10000**.

### 📋 Fichiers Inclus

**Code Source:**
- `main.py` - Bot principal
- `predictor.py` - Moteur de prédiction
- `yaml_manager.py` - Gestionnaire YAML
- `excel_importer.py` - Import Excel
- `render_main.py` - Point d'entrée Render.com

**Configuration:**
- `render.yaml` - Configuration Render.com
- `requirements.txt` - Dépendances Python
- `.env.example` - Template variables

### 🚀 Déploiement Render.com

#### 1. Créer un Compte Render.com
1. Aller sur https://render.com
2. Créer un compte gratuit

#### 2. Nouveau Web Service
1. Cliquer "New +" → "Web Service"
2. Connecter votre repository Git OU uploader ce ZIP
3. Sélectionner "Python" comme environnement

#### 3. Configuration Automatique
Le fichier `render.yaml` configure automatiquement:
- **Type:** Web Service
- **Port:** 10000 (automatique via fromGroup: web)
- **Build:** pip install -r requirements.txt
- **Start:** python render_main.py
- **Health Check:** /health endpoint

#### 4. Variables d'Environnement
Dans Render.com, ajouter ces variables:
- `API_ID` - Votre API ID Telegram
- `API_HASH` - Votre API Hash Telegram
- `BOT_TOKEN` - Votre Bot Token
- `ADMIN_ID` - Votre ID Telegram (optionnel)

Le PORT et autres variables sont auto-configurées.

### ✅ Fonctionnalités

- 📊 Import prédictions Excel
- 🔍 Surveillance canal automatique
- 🎯 Lancement auto prédictions
- ✅ Vérification offsets (0, 1, 2)
- 🌐 Health check endpoint /health
- 💾 Stockage YAML
- 🚀 Optimisé Render.com

### 🔧 Configuration Actuelle

- **Port:** 10000 (fromGroup: web)
- **Health Check:** /health
- **Intervalle:** 1 minute(s)
- **Canal display:** -1002299981135

### 📊 Après Déploiement

1. Le bot démarre sur port 10000
2. URL: https://votre-service.onrender.com
3. Health check: /health
4. Tester /start sur Telegram
5. Voir logs dans Render dashboard

### 🆘 Support

- **Port Error:** Le port 10000 est auto-configuré par Render
- **Variables manquantes:** Vérifier les env vars dans Render
- **Bot ne répond pas:** Vérifier BOT_TOKEN

**Package:** 2025-10-04 04:56
**Plateforme:** Render.com
