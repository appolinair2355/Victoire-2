import os
import yaml
import re
from datetime import datetime
from typing import Dict, Any, Optional, List
from openpyxl import load_workbook

class ExcelPredictionManager:
    def __init__(self):
        self.predictions_file = "excel_predictions.yaml"
        self.predictions = {}  # {key: {numero, date_heure, victoire, launched, message_id, channel_id}}
        self.last_launched_numero = None  # Dernier numéro lancé pour éviter les consécutifs
        self.load_predictions()

    def import_excel(self, file_path: str) -> Dict[str, Any]:
        try:
            workbook = load_workbook(file_path, data_only=True)
            sheet = workbook.active

            imported_count = 0
            skipped_count = 0
            consecutive_skipped = 0
            predictions = {}
            last_numero = None

            for row in sheet.iter_rows(min_row=2, values_only=True):
                if not row[0] or not row[1] or not row[2]:
                    continue

                date_heure = row[0]
                numero = row[1]
                victoire = row[2]

                if isinstance(date_heure, datetime):
                    date_str = date_heure.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    date_str = str(date_heure)

                numero_int = int(numero)
                victoire_type = str(victoire).strip()

                prediction_key = f"{numero_int}"

                # Vérifier si déjà lancé
                if prediction_key in self.predictions and self.predictions[prediction_key].get("launched"):
                    skipped_count += 1
                    continue

                # Vérifier si consécutif au précédent (ignorer si numéro actuel = précédent + 1)
                if last_numero is not None and numero_int == last_numero + 1:
                    consecutive_skipped += 1
                    print(f"⚠️ Numéro {numero_int} ignoré à l'import (consécutif à {last_numero})")
                    continue

                predictions[prediction_key] = {
                    "numero": numero_int,
                    "date_heure": date_str,
                    "victoire": victoire_type,
                    "launched": False,
                    "message_id": None,
                    "chat_id": None,
                    "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                imported_count += 1
                last_numero = numero_int  # Mémoriser le dernier numéro valide

            self.predictions.update(predictions)
            self.save_predictions()

            return {
                "success": True,
                "imported": imported_count,
                "skipped": skipped_count,
                "consecutive_skipped": consecutive_skipped,
                "total": len(self.predictions)
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def save_predictions(self):
        try:
            with open(self.predictions_file, "w", encoding="utf-8") as f:
                yaml.dump(self.predictions, f, allow_unicode=True, default_flow_style=False)
            print(f"✅ Prédictions Excel sauvegardées: {len(self.predictions)} entrées")
        except Exception as e:
            print(f"❌ Erreur sauvegarde prédictions: {e}")

    def load_predictions(self):
        try:
            if os.path.exists(self.predictions_file):
                with open(self.predictions_file, "r", encoding="utf-8") as f:
                    self.predictions = yaml.safe_load(f) or {}
                print(f"✅ Prédictions chargées: {len(self.predictions)} entrées")
            else:
                self.predictions = {}
                print("ℹ️ Aucun fichier de prédictions Excel existant")
        except Exception as e:
            print(f"❌ Erreur chargement prédictions: {e}")
            self.predictions = {}

    def find_close_prediction(self, current_number: int, tolerance: int = 4):
        """
        Trouve une prédiction à lancer quand le canal source affiche un numéro proche AVANT le numéro cible.
        Exemple: Excel #881, Canal source #879 → Lance #881 (diff = +2)
        Tolérance: 0 à 4 parties d'écart
        """
        try:
            closest_pred = None
            min_diff = float('inf')

            for key, pred in self.predictions.items():
                if pred["launched"]:
                    continue

                pred_numero = pred["numero"]
                # Calculer la différence: pred_numero - current_number
                # Si canal=879 et pred=881, diff=+2 (canal est 2 parties AVANT)
                diff = pred_numero - current_number

                # Vérifier si le canal source est entre 0 et 4 parties AVANT le numéro cible
                if 0 <= diff <= tolerance:
                    # Vérifier si ce n'est pas un numéro consécutif du dernier prédit
                    if self.last_launched_numero and abs(pred_numero - self.last_launched_numero) == 1:
                        print(f"⚠️ Numéro {pred_numero} ignoré (consécutif à {self.last_launched_numero})")
                        continue

                    # Garder la prédiction la plus proche (priorité au plus petit écart)
                    if diff < min_diff:
                        min_diff = diff
                        closest_pred = {"key": key, "prediction": pred}
                        print(f"✅ Prédiction trouvée: #{pred_numero} (canal #{current_number}, écart +{diff})")

            return closest_pred
        except Exception as e:
            print(f"Erreur find_close_prediction: {e}")
            return None

    def mark_as_launched(self, key: str, message_id: int, channel_id: int):
        """Marque une prédiction comme lancée"""
        if key in self.predictions:
            self.predictions[key]["launched"] = True
            self.predictions[key]["message_id"] = message_id
            self.predictions[key]["channel_id"] = channel_id
            self.last_launched_numero = self.predictions[key]["numero"]
            self.save_predictions()

    def verify_excel_prediction(self, game_number: int, message_text: str, predicted_numero: int, expected_winner: str):
        """Vérifie une prédiction Excel avec offsets 0, 1, 2"""
        try:
            # Vérifier si le message contient un résultat valide
            if not any(tag in message_text for tag in ["✅", "🔰"]):
                return None

            # Extraire les groupes de cartes
            groups = re.findall(r"\(([^)]*)\)", message_text)
            if len(groups) < 2:
                return None

            # Vérifier 2+2 cartes
            first_count = message_text.count('♠') + message_text.count('♥') + message_text.count('♦') + message_text.count('♣')
            if first_count != 4:
                return None

            # Déterminer le gagnant réel
            actual_winner = None
            if "🔰" in message_text:
                actual_winner = "banquier"
            elif "✅" in message_text:
                actual_winner = "joueur"

            if not actual_winner:
                return None

            # Comparer avec le gagnant attendu
            expected = "banquier" if "banquier" in expected_winner.lower() else "joueur"

            if actual_winner != expected:
                print(f"❌ Prédiction Excel #{predicted_numero}: gagnant incorrect (attendu {expected}, obtenu {actual_winner})")
                return None

            # Vérifier les offsets (0, 1, 2 uniquement)
            for offset in range(3):  # 0, 1, 2
                if game_number == predicted_numero + offset:
                    if offset == 0:
                        return '✅0️⃣'
                    elif offset == 1:
                        return '✅1️⃣'
                    else:  # offset == 2
                        return '✅2️⃣'

            # Si dépassé prédit+2, c'est un échec
            if game_number > predicted_numero + 2:
                return '⭕✍🏻'

            return None

        except Exception as e:
            print(f"Erreur verify_excel_prediction: {e}")
            return None

    def get_prediction_format(self, victoire: str) -> str:
        victoire_lower = victoire.lower()

        if "joueur" in victoire_lower or "player" in victoire_lower:
            return "V1"
        elif "banquier" in victoire_lower or "banker" in victoire_lower:
            return "V2"
        else:
            return "V1"

    def get_pending_predictions(self) -> List[Dict[str, Any]]:
        pending = []
        for key, pred in self.predictions.items():
            if not pred["launched"]:
                pending.append({
                    "key": key,
                    "numero": pred["numero"],
                    "victoire": pred["victoire"],
                    "date_heure": pred["date_heure"]
                })
        return sorted(pending, key=lambda x: x["numero"])

    def get_stats(self) -> Dict[str, int]:
        total = len(self.predictions)
        launched = sum(1 for p in self.predictions.values() if p["launched"])
        pending = total - launched

        return {
            "total": total,
            "launched": launched,
            "pending": pending
        }

    def clear_predictions(self):
        self.predictions = {}
        self.save_predictions()
        print("🗑️ Toutes les prédictions Excel ont été effacées")