"""验证剪贴板原格式恢复和用户新内容优先；不读取系统剪贴板。"""

import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from zzz_od.macos.redemption_pasteboard import temporary_redemption_pasteboard


class Item:
    """模拟一个含多种格式的项目。"""

    def __init__(self, data: dict[str, bytes | str | None] | None = None) -> None:
        self.data = data or {}

    @classmethod
    def alloc(cls) -> 'Item':
        return cls()

    def init(self) -> 'Item':
        return self

    def types(self) -> list[str]:
        return list(self.data)

    def dataForType_(self, key: str) -> bytes | str | None:  # noqa: N802
        return self.data[key]

    def setData_forType_(self, data: bytes, key: str) -> bool:  # noqa: N802
        self.data[key] = data
        return True

    def setString_forType_(self, value: str, key: str) -> bool:  # noqa: N802
        self.data[key] = value
        return True


class Board:
    """保留写入会话代数，模拟 AppKit 清空后不会再次递增。"""

    def __init__(self) -> None:
        self.generation = 1
        self.items = [Item({'public.utf8-plain-text': b'old', 'public.rtf': b'{rtf}'}),
                      Item({'public.png': b'img'})]

    def pasteboardItems(self) -> list[Item]:  # noqa: N802
        return self.items

    def changeCount(self) -> int:  # noqa: N802
        return self.generation

    def clearContents(self) -> int:  # noqa: N802
        self.generation += 1
        self.items = []
        return self.generation

    def writeObjects_(self, items: list[Item]) -> bool:  # noqa: N802
        self.items = items
        return True


@pytest.fixture
def board(monkeypatch: pytest.MonkeyPatch) -> Board:
    pb = Board()
    monkeypatch.setitem(sys.modules, 'AppKit', SimpleNamespace(
        NSData=SimpleNamespace(dataWithData_=bytes), NSPasteboard=SimpleNamespace(generalPasteboard=lambda: pb),
        NSPasteboardItem=Item, NSPasteboardTypeString='public.utf8-plain-text',
    ))
    monkeypatch.setitem(sys.modules, 'objc', SimpleNamespace(autorelease_pool=nullcontext))
    return pb


@pytest.mark.parametrize('exception', [False, True])
def test_restores_every_item_and_type(board: Board, exception: bool) -> None:
    original = [item.data.copy() for item in board.items]
    try:
        with temporary_redemption_pasteboard('TEMP123'):
            assert [item.data for item in board.items] == [{'public.utf8-plain-text': 'TEMP123'}]
            if exception:
                raise LookupError
    except LookupError:
        assert exception
    assert [item.data for item in board.items] == original


def test_preserves_concurrent_user_copy(board: Board) -> None:
    with temporary_redemption_pasteboard('TEMP123'):
        board.clearContents()
        board.writeObjects_([Item({'public.png': b'new user image'})])
    assert board.items[0].data == {'public.png': b'new user image'}


def test_refuses_to_overwrite_unreadable_original(board: Board) -> None:
    board.items = [Item({'public.content': None})]
    with pytest.raises(RuntimeError, match='无损恢复'), temporary_redemption_pasteboard('TEMP123'):
        pytest.fail('must not overwrite existing data')
    assert board.changeCount() == 1
    assert board.items[0].data == {'public.content': None}
