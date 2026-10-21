import logging
import time
import os  # <--- ДОБАВЛЕН ИМПОРТ ДЛЯ ЧТЕНИЯ СЕКРЕТОВ
from typing import Optional, Callable
from pathlib import Path

from .auth import Auth, load_auth, env
from .streak import Streaks, as_code, SEND, RESTORE, NUDGE
from .messaging import Inbox
from .config import BotConfig

class StreakBot:
    def __init__(self, config: Optional[BotConfig] = None, auth: Optional[Auth] = None):
        if isinstance(config, Auth):
            auth, config = config, None
        self.config = config or (BotConfig.load() if Path("data/config.json").exists() else BotConfig())
        self.auth = auth or load_auth(cookie_path=self.config.cookies_file)
        self.streaks = Streaks(self.auth)
        self.inbox = Inbox(self.auth)
        self.msg = self.config.message_to_send or env("STREAK_MESSAGE", "🔥")
        self.ok_at = {}
        self.fail = {}

    def ready(self) -> str:
        if not self.auth.ok_sess():
            return "no session"
        if not self.auth.login():
            return "bad session"
        return ""

    def run_oneshot(self, note: Callable[[str], None] = logging.info, force: bool = False) -> int:
        status = self.ready()
        if status:
            note(f"Authentication failed: {status}")
            return 0

        user_info = self.auth.user
        who = user_info.get("username") or user_info.get("id") or "?"
        note(f"Authenticated as @{who}")

        try:
            rows = self.streaks.fetch()
        except Exception as e:
            note(f"Failed to fetch streaks: {e}")
            return 0

        note(f"Found {len(rows)} streak contact(s).")

        # =========================================================================
        # БЛОК ОДНОРАЗОВОГО СООБЩЕНИЯ
        # =========================================================================
        one_off_target = os.getenv("ONE_OFF_TARGET")
        one_off_message = os.getenv("ONE_OFF_MESSAGE")
        skip_streaks = os.getenv("SKIP_STREAKS") == "true"  # <-- НОВЫЙ ПЕРЕКЛЮЧАТЕЛЬ
        
        if one_off_target and one_off_message:
            note(f"⚠️ ОБНАРУЖЕНА ЦЕЛЬ ДЛЯ ОДНОРАЗОВОГО СООБЩЕНИЯ: {one_off_target}")
            note(f"Отправляем текст: '{one_off_message}'...")
            
            res = self.inbox.send(one_off_target, one_off_message, "", 1)
            
            if res.get("ok"):
                note(f"✓ Одноразовое сообщение успешно отправлено {one_off_target}")
            else:
                note(f"✗ Ошибка отправки одноразового сообщения: {res.get('msg')}")
            
            if skip_streaks:
                note("Режим 'Только одно сообщение'. Завершаем работу.")
                return 1  # <-- Останавливаем скрипт, чтобы он не пошел рассылать стрики
            time.sleep(1.5)
        # =========================================================================
        # =========================================================================

        if force:
            note(f"Force dispatch enabled. Sending '{self.msg}' to all {len(rows)} streak contacts...")
            action_count = 0
            for row in rows:
                uid = str(row.get("id") or "")
                note(f"Sending to {uid} ({row.get('streak')}d, status={row.get('status')})...")
                res = self.inbox.send(uid, self.msg, row.get("conversation_id") or "", row.get("conv_type") or 1)
                if res.get("ok"):
                    note(f"✓ Message delivered to {uid}")
                    self.streaks.touch(uid)
                    action_count += 1
                else:
                    note(f"✗ Delivery failed for {uid}: {res.get('msg')}")
                time.sleep(1.5)
            note(f"Force dispatch completed: {action_count}/{len(rows)} messages delivered.")
            return action_count

        due_items = self.streaks.due()
        note(f"{len(due_items)} streak(s) require action right now.")

        action_count = 0
        for item in due_items:
            row = item["row"]
            uid = str(row.get("id") or "")
            for act in item["acts"]:
                if act == RESTORE:
                    note(f"Restoring lost streak for {uid}...")
                    res = self.streaks.restore(uid)
                    if res.get("ok"):
                        note(f"✓ Restored streak for {uid}")
                        action_count += 1
                    else:
                        note(f"✗ Restore failed for {uid}: {res.get('msg')}")
                elif act in (SEND, NUDGE):
                    text = self.msg if act == SEND else f"{self.msg}?"
                    note(f"Sending streak message ({act}) to {uid}...")
                    res = self.inbox.send(uid, text, row.get("conversation_id") or "", row.get("conv_type") or 1)
                    if res.get("ok"):
                        note(f"✓ Message delivered to {uid}")
                        self.streaks.touch(uid)
                        action_count += 1
                    else:
                        note(f"✗ Delivery failed for {uid}: {res.get('msg')}")
                time.sleep(1.5)

        note(f"Streak cycle completed: {action_count} actions performed.")
        return action_count

    def run_cycle(self, force: bool = False) -> int:
        """Alias for compatibility with existing runner."""
        return self.run_oneshot(force=force)
