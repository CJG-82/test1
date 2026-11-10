"""쇼핑 리스트 저장소.

UI(app.py)는 Storage 인터페이스에만 의존한다. 저장 방식을 바꿀 때는
이 인터페이스를 따르는 새 구현체를 만들고 get_storage()만 바꾸면 된다.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar

from models import Item

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).parent / "data" / "shopping_list.json"

# Streamlit은 한 프로세스 안에서 세션마다 스레드를 띄운다. 읽기-수정-쓰기가
# 겹치면 한쪽 변경이 사라지므로, 모든 저장소 작업을 이 잠금으로 직렬화한다.
_LOCK = threading.RLock()

# Windows에서는 다른 곳이 파일을 잠깐 열고 있으면 교체/읽기가 PermissionError로 실패한다.
_RETRIES = 10
_RETRY_DELAY = 0.05

T = TypeVar("T")


class ItemNotFoundError(KeyError):
    """대상 아이템이 저장소에 없다 (다른 탭에서 삭제된 경우 등)."""


class Storage(Protocol):
    def list_items(self) -> list[Item]: ...
    def add_item(self, item: Item) -> None: ...
    def update_item(self, item: Item) -> None: ...
    def update_fields(self, item_id: str, fields: dict[str, Any]) -> Item: ...
    def delete_item(self, item_id: str) -> None: ...
    def delete_checked(self) -> int: ...
    def recovery_notices(self) -> list[str]: ...


def _retry(func: Callable[[], T]) -> T:
    for attempt in range(_RETRIES):
        try:
            return func()
        except PermissionError:
            if attempt == _RETRIES - 1:
                raise
            time.sleep(_RETRY_DELAY * (attempt + 1))
    raise AssertionError("unreachable")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


class JsonStorage:
    """로컬 JSON 파일 저장소 (MVP용)."""

    # 경로는 기본값 없이 꼭 받는다. 실제 데이터 경로는 get_storage()만 정해서,
    # 스크립트나 테스트가 실수로 data/shopping_list.json에 쓰지 않게 한다.
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self._write([])

    # ------------------------------------------------------------ 내부

    def _read(self) -> list[Item]:
        try:
            raw = _retry(lambda: self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        if not raw.strip():
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._backup_corrupt()
            return []
        if not isinstance(data, list):
            self._backup_corrupt()
            return []

        items: list[Item] = []
        invalid: list[Any] = []
        for entry in data:
            try:
                items.append(Item.from_dict(entry))
            except (KeyError, TypeError, ValueError, AttributeError):
                invalid.append(entry)
        if invalid:
            # 읽지 못한 항목은 버리지 않고 따로 보관한 뒤, 본 파일에서는 뺀다.
            backup = self._backup_path("invalid")
            backup.write_text(json.dumps(invalid, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.warning("읽지 못한 아이템 %d개를 %s 에 보관했습니다.", len(invalid), backup)
            self._write(items)
        return items

    def _write(self, items: list[Item]) -> None:
        # 임시 파일에 쓴 뒤 교체해서, 쓰는 도중 실패해도 기존 파일이 깨지지 않게 한다.
        payload = json.dumps([i.to_dict() for i in items], ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            _retry(lambda: os.replace(tmp, self.path))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _backup_path(self, kind: str) -> Path:
        # 시각을 붙여서 이전 백업을 덮어쓰지 않는다.
        return self.path.with_name(f"{self.path.stem}.{kind}-{_timestamp()}.json")

    def _backup_corrupt(self) -> None:
        backup = self._backup_path("corrupt")
        logger.warning("저장 파일이 손상되어 %s 로 백업합니다.", backup)
        _retry(lambda: os.replace(self.path, backup))
        self._write([])

    # ------------------------------------------------------------ 공개 API

    def list_items(self) -> list[Item]:
        with _LOCK:
            return self._read()

    def add_item(self, item: Item) -> None:
        with _LOCK:
            items = self._read()
            items.append(item)
            self._write(items)

    def update_item(self, item: Item) -> None:
        with _LOCK:
            items = self._read()
            if not any(i.id == item.id for i in items):
                raise ItemNotFoundError(item.id)
            self._write([item if i.id == item.id else i for i in items])

    def update_fields(self, item_id: str, fields: dict[str, Any]) -> Item:
        """저장소의 최신 상태를 기준으로 지정한 필드만 바꾼다.

        화면이 들고 있던 오래된 Item을 통째로 쓰면 다른 탭의 변경을 덮어쓰므로,
        수정·체크는 이 메서드를 쓴다.
        """
        with _LOCK:
            items = self._read()
            target = next((i for i in items if i.id == item_id), None)
            if target is None:
                raise ItemNotFoundError(item_id)
            for key, value in fields.items():
                setattr(target, key, value)
            target.touch()
            self._write(items)
            return target

    def delete_item(self, item_id: str) -> None:
        with _LOCK:
            items = self._read()
            self._write([i for i in items if i.id != item_id])

    def delete_checked(self) -> int:
        with _LOCK:
            items = self._read()
            remaining = [i for i in items if not i.checked]
            self._write(remaining)
            return len(items) - len(remaining)

    def recovery_notices(self) -> list[str]:
        """손상 파일이나 읽지 못한 항목을 보관한 백업 파일 이름 목록."""
        patterns = (f"{self.path.stem}.corrupt-*.json", f"{self.path.stem}.invalid-*.json")
        return sorted(p.name for pattern in patterns for p in self.path.parent.glob(pattern))


def get_storage() -> Storage:
    # 테스트는 SHOPPING_LIST_PATH로 임시 파일을 지정해서 실제 데이터를 건드리지 않는다.
    return JsonStorage(Path(os.environ.get("SHOPPING_LIST_PATH", DEFAULT_PATH)))
