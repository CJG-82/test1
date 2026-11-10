"""쇼핑 리스트 Streamlit 앱."""

from __future__ import annotations

import re

import streamlit as st

from models import (
    CATEGORIES,
    DEFAULT_CATEGORY,
    MEMO_MAX,
    NAME_MAX,
    STATUS_ALL,
    STATUSES,
    Item,
    ValidationError,
    filter_items,
    find_duplicate,
    sort_items,
    validate_fields,
)
from storage import ItemNotFoundError, get_storage

st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")

storage = get_storage()

ALL_CATEGORIES = "모든 분류"
# 한 번에 그리는 아이템 수. 필터를 바꾸면 브라우저가 카드를 새로 그리는데,
# 200개 기준 50개는 약 1초, 30개는 PRD 기준(1초 이내) 안에 들어온다.
PAGE_SIZE = 30

# 추가 폼 위젯 key와 초기값. 성공했을 때만 이 값으로 되돌린다.
ADD_DEFAULTS = {"add_name": "", "add_qty": 1, "add_cat": DEFAULT_CATEGORY, "add_memo": ""}

# 분류별 이모지와 배지 색 (Streamlit 배지 색 이름)
CATEGORY_STYLE: dict[str, tuple[str, str]] = {
    "채소": ("🥬", "green"),
    "과일": ("🍎", "red"),
    "육류": ("🥩", "orange"),
    "유제품": ("🥛", "blue"),
    "생활용품": ("🧻", "violet"),
    "기타": ("📦", "gray"),
}


# ---------------------------------------------------------------- 스타일

# 커스텀 CSS는 여기 한곳에만 둔다. 색은 테마 변수(config.toml)를 따르게 해서
# 라이트/다크 모드 모두에서 자연스럽게 보이도록 한다.
CSS = """
<style>
[data-testid="stMainBlockContainer"] {
    max-width: 720px;
    padding-top: 2.5rem;
    padding-bottom: 4rem;
}

/* 아이템 카드: 분류·메모 줄을 체크박스 글자 위치에 맞춰 들여쓰기 */
[class*="st-key-meta_"] {
    padding-left: 1.85rem;
}
/* 완료된 아이템 카드는 흐리게 */
[class*="st-key-row-done_"] {
    opacity: 0.6;
}
[class*="st-key-row-"] {
    transition: opacity 0.2s ease;
}
/* 수정·삭제 버튼: 손가락으로 누르기 쉬운 크기 (44px 이상) */
[class*="st-key-row-"] button {
    min-width: 2.75rem;
    min-height: 2.75rem;
    justify-content: center;
}
/* 삭제 확인 팝오버 버튼의 펼침 화살표 숨김 (아이콘 버튼처럼 보이게) */
[class*="st-key-delpop_"] [data-testid="stPopoverButton"] [data-testid="stIconMaterial"] {
    display: none;
}

/* 요약 카드: 좁은 화면에서도 세 칸이 한 줄에 들어가도록 최소 폭 해제 */
.st-key-summary [data-testid="stColumn"] {
    min-width: 0;
}
.st-key-summary [data-testid="stMetricLabel"] * {
    overflow: visible;
    text-overflow: clip;
}

/* 빈 화면 안내 */
.empty-state {
    text-align: center;
    padding: 2.5rem 1rem;
    border: 1px dashed var(--st-border-color, rgba(128, 128, 128, 0.35));
    border-radius: 0.75rem;
}
.empty-state .icon { font-size: 2.75rem; line-height: 1; }
.empty-state .title { font-weight: 700; margin-top: 0.75rem; font-size: 1.05rem; }
.empty-state .desc { opacity: 0.7; margin-top: 0.25rem; font-size: 0.9rem; }

/* 모바일 */
@media (max-width: 640px) {
    [data-testid="stMainBlockContainer"] {
        padding-top: 1.5rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    [data-testid="stMetricValue"] { font-size: 1.6rem; }
    [data-testid="stMetric"] { padding: 0.6rem 0.7rem; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem; }
}
</style>
"""


def inject_css() -> None:
    st.html(CSS)


def empty_state(icon: str, title: str, desc: str) -> None:
    # 고정 문구만 넣는다 (사용자 입력 금지).
    st.html(
        f'<div class="empty-state"><div class="icon">{icon}</div>'
        f'<div class="title">{title}</div><div class="desc">{desc}</div></div>'
    )


# ---------------------------------------------------------------- 도우미


def md_escape(text: str) -> str:
    """사용자 입력이 마크다운으로 해석되지 않게 한다.

    마크다운 특수문자는 백슬래시로 이스케이프한다. ':'는 백슬래시로 막히지 않는
    Streamlit 문법(:material/icon:, :red[...], 이모지 단축코드)이 있어서
    뒤에 폭 없는 공백을 넣어 패턴을 끊는다.
    """
    escaped = re.sub(r"([\\`*_{}\[\]()#+\-.!|~<>$])", r"\\\1", text)
    return escaped.replace(":", ":​")


def category_badge(category: str) -> str:
    emoji, color = CATEGORY_STYLE.get(category, CATEGORY_STYLE[DEFAULT_CATEGORY])
    return f":{color}-badge[{emoji} {category}]"


def category_label(category: str) -> str:
    emoji, _ = CATEGORY_STYLE.get(category, CATEGORY_STYLE[DEFAULT_CATEGORY])
    return f"{emoji} {category}"


def flash(message: str, icon: str = "✅") -> None:
    """콜백이나 st.rerun() 뒤에도 보이도록 알림을 다음 실행으로 넘긴다.

    message에 사용자 입력을 넣을 때는 md_escape()를 거친다.
    """
    st.session_state.setdefault("flash", []).append((message, icon))


def show_flash() -> None:
    for message, icon in st.session_state.pop("flash", []):
        st.toast(message, icon=icon)


def reset_page() -> None:
    st.session_state["visible_limit"] = PAGE_SIZE


# ---------------------------------------------------------------- 콜백


def on_add() -> None:
    ss = st.session_state
    try:
        fields = validate_fields(ss["add_name"], ss["add_qty"], ss["add_cat"], ss["add_memo"])
    except ValidationError as e:
        # 입력값은 그대로 두고 오류만 보여준다.
        ss["add_errors"] = e.errors
        return

    duplicate = find_duplicate(storage.list_items(), fields["name"])
    storage.add_item(Item(**fields))
    flash(f"'{md_escape(fields['name'])}'을(를) 추가했습니다.", "✅")
    if duplicate:
        ss["add_warning"] = (
            f"'{md_escape(duplicate.name)}'은(는) 이미 리스트에 있어요 "
            f"(수량 {duplicate.quantity}). 새 항목으로 추가했습니다."
        )
    ss.update(ADD_DEFAULTS)


def on_toggle(item_id: str) -> None:
    try:
        storage.update_fields(item_id, {"checked": st.session_state[f"chk_{item_id}"]})
    except ItemNotFoundError:
        flash("이미 삭제된 아이템입니다.", "⚠️")


def on_delete(item_id: str, name: str) -> None:
    storage.delete_item(item_id)
    flash(f"'{md_escape(name)}'을(를) 삭제했습니다.", "🗑️")


def on_delete_checked() -> None:
    count = storage.delete_checked()
    flash(f"완료 항목 {count}개를 삭제했습니다.", "🧹")


def on_dismiss_notice(name: str) -> None:
    st.session_state.setdefault("dismissed_notices", set()).add(name)


def on_show_more() -> None:
    st.session_state["visible_limit"] = st.session_state.get("visible_limit", PAGE_SIZE) + PAGE_SIZE


# ---------------------------------------------------------------- 수정 다이얼로그


# on_dismiss="rerun": X나 Esc로 닫을 때도 다시 실행해서, 버린 입력값이
# 다음에 팝업을 열 때 남아 있지 않게 한다.
@st.dialog("아이템 수정", on_dismiss="rerun")
def edit_dialog(item: Item) -> None:
    with st.form(f"edit_form_{item.id}", border=False):
        name = st.text_input("이름", value=item.name, max_chars=NAME_MAX)
        qty_col, cat_col = st.columns([1, 2])
        # 범위는 validate_fields가 한국어 메시지로 검사한다 (위젯 자체 검사는 영어).
        quantity = qty_col.number_input("수량", value=item.quantity, step=1, format="%d")
        category = cat_col.selectbox(
            "분류",
            CATEGORIES,
            index=CATEGORIES.index(item.category) if item.category in CATEGORIES else 0,
            format_func=category_label,
        )
        memo = st.text_input("메모", value=item.memo, max_chars=MEMO_MAX)
        save_col, cancel_col = st.columns(2)
        saved = save_col.form_submit_button("저장", type="primary", width="stretch")
        canceled = cancel_col.form_submit_button("취소", width="stretch")

    if canceled:
        st.rerun()

    if saved:
        try:
            fields = validate_fields(name, quantity, category, memo)
        except ValidationError as e:
            for err in e.errors:
                st.error(err)
            return

        # 팝업을 연 뒤 다른 탭에서 바뀐 값(체크 등)을 덮어쓰지 않도록, 고친 필드만 저장한다.
        try:
            storage.update_fields(item.id, fields)
        except ItemNotFoundError:
            flash("이미 삭제된 아이템이라 수정하지 못했습니다.", "⚠️")
        else:
            flash(f"'{md_escape(fields['name'])}'을(를) 수정했습니다.", "✏️")
        st.rerun()


# ---------------------------------------------------------------- 화면 조각


def render_recovery_notices() -> None:
    dismissed = st.session_state.get("dismissed_notices", set())
    for name in storage.recovery_notices():
        if name in dismissed:
            continue
        with st.container(key=f"notice_{name}"):
            st.warning(
                f"저장 파일에 문제가 있어 원본을 `data/{name}` 에 백업했어요. "
                "필요한 내용이 있으면 이 파일에서 확인해 주세요.",
                icon="⚠️",
            )
            st.button("확인", key=f"dismiss_{name}", on_click=on_dismiss_notice, args=(name,))


def render_summary(items: list[Item]) -> None:
    total = len(items)
    done = sum(1 for i in items if i.checked)
    remaining = total - done

    # wrap=False: 모바일에서도 세 카드를 한 줄에 같은 폭으로 둔다.
    with st.container(key="summary"):
        total_col, remaining_col, done_col = st.columns(3, gap="small", wrap=False)
        total_col.metric("전체", total, border=True)
        remaining_col.metric("남음", remaining, border=True)
        done_col.metric("완료", done, border=True)
    if total:
        st.progress(done / total, text=f"구매 진행률 {done}/{total}")


def render_add_form() -> None:
    for key, value in ADD_DEFAULTS.items():
        st.session_state.setdefault(key, value)

    with st.form("add_item"):
        st.markdown("**:material/add_shopping_cart: 아이템 추가**")
        name_col, qty_col = st.columns([3, 1])
        name_col.text_input("이름", max_chars=NAME_MAX, placeholder="예: 우유", key="add_name")
        # 범위는 validate_fields가 한국어 메시지로 검사한다 (위젯 자체 검사는 영어).
        qty_col.number_input("수량", step=1, format="%d", key="add_qty")
        cat_col, memo_col = st.columns([1, 2])
        cat_col.selectbox("분류", CATEGORIES, format_func=category_label, key="add_cat")
        memo_col.text_input("메모", max_chars=MEMO_MAX, placeholder="예: 저지방", key="add_memo")
        st.form_submit_button(
            "추가", type="primary", icon=":material/add:", width="stretch", on_click=on_add
        )

    for err in st.session_state.pop("add_errors", []):
        st.error(err)
    if warning := st.session_state.pop("add_warning", None):
        st.warning(warning, icon="⚠️")


def render_item(item: Item) -> None:
    state = "done" if item.checked else "todo"
    with st.container(border=True, key=f"row-{state}_{item.id}", gap=None):
        with st.container(horizontal=True, wrap=False, vertical_alignment="center", gap="small"):
            with st.container(width="stretch"):
                text = f"{md_escape(item.name)} ×{item.quantity}"
                st.checkbox(
                    f":gray[~~{text}~~]" if item.checked else f"**{text}**",
                    value=item.checked,
                    key=f"chk_{item.id}",
                    on_change=on_toggle,
                    args=(item.id,),
                )
            if st.button("✏️", key=f"edit_{item.id}", help="수정", type="tertiary"):
                edit_dialog(item)
            # 삭제는 한 번 더 확인한다 (모바일에서 잘못 누르는 것 방지).
            with st.popover("🗑️", type="tertiary", help="삭제", key=f"delpop_{item.id}"):
                st.markdown(f"**{md_escape(item.name)}** 을(를) 삭제할까요?")
                st.button(
                    "삭제",
                    key=f"del_{item.id}",
                    type="primary",
                    icon=":material/delete:",
                    on_click=on_delete,
                    args=(item.id, item.name),
                )
        with st.container(key=f"meta_{item.id}"):
            meta = category_badge(item.category)
            if item.memo:
                meta += f" {md_escape(item.memo)}"
            st.caption(meta)


def render_list(items: list[Item]) -> None:
    st.subheader("내 리스트")

    if not items:
        empty_state("🧺", "리스트가 비어 있습니다", "위에서 살 물건을 추가해 보세요.")
        return

    status_col, cat_col = st.columns([3, 2], vertical_alignment="bottom")
    with status_col:
        status = st.segmented_control(
            "보기",
            STATUSES,
            default=STATUS_ALL,
            required=True,
            key="filter_status",
            width="stretch",
            on_change=reset_page,
        )
    with cat_col:
        cat_choice = st.selectbox(
            "분류",
            [ALL_CATEGORIES, *CATEGORIES],
            key="filter_category",
            format_func=lambda c: c if c == ALL_CATEGORIES else category_label(c),
            on_change=reset_page,
        )

    visible = sort_items(
        filter_items(items, status, None if cat_choice == ALL_CATEGORIES else cat_choice)
    )
    if not visible:
        empty_state("🔍", "조건에 맞는 아이템이 없습니다", "보기나 분류 필터를 바꿔 보세요.")

    limit = st.session_state.get("visible_limit", PAGE_SIZE)
    for item in visible[:limit]:
        render_item(item)
    if len(visible) > limit:
        st.button(
            f"더 보기 ({len(visible) - limit}개 남음)",
            key="show_more",
            on_click=on_show_more,
            width="stretch",
        )

    done = sum(1 for i in items if i.checked)
    with st.container(horizontal=True, horizontal_alignment="right"):
        with st.popover(
            f"완료 항목 모두 삭제 ({done}개)",
            icon=":material/delete_sweep:",
            disabled=done == 0,
            key="delete_checked_pop",
        ):
            st.markdown(f"완료한 아이템 **{done}개**를 모두 삭제할까요?")
            st.button(
                "모두 삭제",
                key="delete_checked",
                type="primary",
                icon=":material/delete_sweep:",
                on_click=on_delete_checked,
            )


# ---------------------------------------------------------------- 화면

inject_css()
show_flash()

# 추가·체크·삭제는 모두 콜백에서 화면을 그리기 전에 처리되므로, 여기서 읽는 목록은 항상 최신이다.
# 파일 손상은 읽는 순간 발견되므로, 복구 안내보다 먼저 읽어야 같은 화면에 안내가 나온다.
items = storage.list_items()

st.title("🛒 쇼핑 리스트")
st.caption("살 것을 적고, 담은 것은 체크하세요.")
render_recovery_notices()
render_summary(items)
render_add_form()
st.divider()
render_list(items)
