"""쇼핑 리스트 아이템 데이터 모델과 비즈니스 규칙 (검증, 정렬, 필터)."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable

CATEGORIES = ["채소", "과일", "육류", "유제품", "생활용품", "기타"]
DEFAULT_CATEGORY = "기타"

NAME_MAX = 50
MEMO_MAX = 100
QUANTITY_MIN = 1
QUANTITY_MAX = 999

STATUS_ALL = "전체"
STATUS_TODO = "미완료"
STATUS_DONE = "완료"
STATUSES = [STATUS_ALL, STATUS_TODO, STATUS_DONE]


def _now() -> datetime:
    return datetime.now()


@dataclass
class Item:
    name: str
    quantity: int = 1
    category: str = DEFAULT_CATEGORY
    memo: str = ""
    checked: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Item:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            quantity=int(data.get("quantity", 1)),
            category=str(data.get("category", DEFAULT_CATEGORY)),
            memo=str(data.get("memo", "")),
            checked=bool(data.get("checked", False)),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


# ---------------------------------------------------------------- 검증


class ValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def validate_fields(name: str, quantity: Any, category: str, memo: str) -> dict[str, Any]:
    """입력값을 정리하고 검증한다. 문제가 있으면 ValidationError를 던진다."""
    errors: list[str] = []

    name = (name or "").strip()
    if not name:
        errors.append("이름을 입력해 주세요.")
    elif len(name) > NAME_MAX:
        errors.append(f"이름은 {NAME_MAX}자 이하로 입력해 주세요. (현재 {len(name)}자)")

    try:
        qty = int(quantity)
        if qty != quantity:  # 1.5 같은 소수 거부
            raise ValueError
    except (TypeError, ValueError):
        errors.append("수량은 정수로 입력해 주세요.")
        qty = 0
    else:
        if not QUANTITY_MIN <= qty <= QUANTITY_MAX:
            errors.append(f"수량은 {QUANTITY_MIN}~{QUANTITY_MAX} 사이로 입력해 주세요.")

    if category not in CATEGORIES:
        errors.append("분류를 목록에서 선택해 주세요.")

    memo = (memo or "").strip()
    if len(memo) > MEMO_MAX:
        errors.append(f"메모는 {MEMO_MAX}자 이하로 입력해 주세요. (현재 {len(memo)}자)")

    if errors:
        raise ValidationError(errors)
    return {"name": name, "quantity": qty, "category": category, "memo": memo}


# ---------------------------------------------------------------- 조회 규칙


def sort_items(items: Iterable[Item]) -> list[Item]:
    """미완료 먼저, 그다음 최신 등록순."""
    # 등록 시각이 같으면 나중에 저장된 것이 먼저 오도록 역순으로 넣고 안정 정렬한다.
    return sorted(reversed(list(items)), key=lambda i: (i.checked, -i.created_at.timestamp()))


def filter_items(items: Iterable[Item], status: str = STATUS_ALL, category: str | None = None) -> list[Item]:
    result = list(items)
    if status == STATUS_TODO:
        result = [i for i in result if not i.checked]
    elif status == STATUS_DONE:
        result = [i for i in result if i.checked]
    if category:
        result = [i for i in result if i.category == category]
    return result


def find_duplicate(items: Iterable[Item], name: str, exclude_id: str | None = None) -> Item | None:
    """같은 이름(대소문자·앞뒤 공백 무시)의 미완료 아이템을 찾는다."""
    key = name.strip().casefold()
    for item in items:
        if item.id != exclude_id and not item.checked and item.name.strip().casefold() == key:
            return item
    return None
