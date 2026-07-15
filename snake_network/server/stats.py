import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List


class StatsStore:
    """שומר שיאים והיסטוריית משחקים בקבצי JSON."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._save({"high_scores": {}, "matches": []})

    def record_match(self, room_name: str, winner: str, players: List[Dict[str, object]]) -> None:
        with self._lock:
            data = self._load()
            data["matches"].append({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "room": room_name,
                "winner": winner,
                "players": players,
            })
            data["matches"] = data["matches"][-50:]

            high_scores = data["high_scores"]
            for player in players:
                username = str(player["username"])
                if username.startswith("Bot "):
                    continue
                score = int(player["score"])
                record = high_scores.setdefault(username, {"best_score": 0, "wins": 0, "games": 0})
                record["best_score"] = max(int(record["best_score"]), score)
                record["games"] = int(record["games"]) + 1
                if username == winner:
                    record["wins"] = int(record["wins"]) + 1
            self._save(data)

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            data = self._load()
            high_scores = [
                {"username": username, **record}
                for username, record in data["high_scores"].items()
            ]
            high_scores.sort(key=lambda item: (int(item["wins"]), int(item["best_score"])), reverse=True)
            return {
                "type": "stats",
                "high_scores": high_scores[:10],
                "matches": list(reversed(data["matches"][-10:])),
            }

    def _load(self) -> Dict[str, object]:
        with self._path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save(self, data: Dict[str, object]) -> None:
        with self._path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
