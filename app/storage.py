"""
@File: storage.py
@Author: Dominik Vondruška
@Project: Bakalářská práce — Systém pro monitorování otevřených dat v reálném čase
@Description: Třída pro správu přijatých NDIC zpráv a obsluhu WebSocket klientů.
"""
from typing import Optional, List
from threading import Lock
from fastapi import WebSocket

class DatexStorage:
    def __init__(self):
        self._latest_raw = None
        self._lock = Lock()
        self._clients: List[WebSocket] = []

    def save(self, raw_xml: str):
        with self._lock:
            self._latest_raw = raw_xml

    def get_latest(self) -> Optional[str]:
        with self._lock:
            return self._latest_raw

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._clients.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self._clients:
            self._clients.remove(websocket)

    async def broadcast(self, message: str):
        for client in self._clients:
            try:
                await client.send_text(message)
            except Exception:
                self.disconnect(client)

storage = DatexStorage()