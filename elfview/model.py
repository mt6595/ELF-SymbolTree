"""ELF 变量/类型树的数据模型。

解析层与界面层共享这一套轻量结构:解析器把 DWARF 类型图还原成 Node 树,
每个节点自带偏移、绝对地址、大小、位域信息,GUI 只负责渲染。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class Kind:
    VARIABLE = "variable"
    STRUCT = "struct"
    UNION = "union"
    ENUM = "enum"
    ARRAY = "array"
    ELEMENT = "element"
    POINTER = "pointer"
    BASE = "base"
    TYPEDEF = "typedef"
    BITFIELD = "bitfield"
    FUNCTION = "function"


@dataclass
class Node:
    """类型树中的一个节点。

    offset   相对父节点起始地址的字节偏移
    address  绝对地址(None 表示无法静态确定,例如指针目标)
    size     该节点占用的字节数(数组为总大小,位域为容器字节大小)
    bit_offset  位域:相对父结构体起始的绝对位偏移
    bit_size    位域:位宽
    """

    name: str
    type_str: str = ""
    kind: str = Kind.BASE
    offset: Optional[int] = None
    address: Optional[int] = None
    size: Optional[int] = None
    bit_offset: Optional[int] = None
    bit_size: Optional[int] = None
    children: list["Node"] = field(default_factory=list)

    # 调试/DWARF 追溯信息
    die_offset: Optional[int] = None
    tag: str = ""
    extra: dict = field(default_factory=dict)

    # ---- 展示辅助 ----
    @property
    def is_bitfield(self) -> bool:
        return self.bit_size is not None and self.bit_offset is not None

    @property
    def bit_range_str(self) -> str:
        if not self.is_bitfield:
            return ""
        start = self.bit_offset
        end = start + self.bit_size - 1
        if start == end:
            return f"bit {start}"
        return f"bit {start}..{end}"

    @property
    def end_address(self) -> Optional[int]:
        if self.address is None or self.size is None:
            return None
        return self.address + self.size - 1

    def walk(self):
        """深度优先迭代自身及全部子孙。"""
        yield self
        for child in self.children:
            yield from child.walk()

    def count_nodes(self) -> int:
        return sum(1 for _ in self.walk())


@dataclass
class Variable:
    """一个带静态地址的变量(全局/文件静态/函数内静态)。"""

    node: Node
    linkage: str = "global"          # global / static / local-static
    scope: str = ""                  # 函数内静态变量所属函数
    section: str = ""                # .data / .bss / .rodata ...
    symbol_size: Optional[int] = None
    allocated: bool = True           # False: 调试信息存在但未分配地址(被优化/仅声明)
    unallocated_reason: str = ""
    cu_name: str = ""                # 所属编译单元(区分同名 static 变量)

    @property
    def name(self) -> str:
        return self.node.name

    @property
    def address(self) -> Optional[int]:
        return self.node.address

    @property
    def size(self) -> Optional[int]:
        return self.node.size

    @property
    def type_str(self) -> str:
        return self.node.type_str


@dataclass
class ElfInfo:
    """ELF 文件级摘要,用于界面顶部展示。"""

    path: str = ""
    arch: str = ""
    bits: int = 0
    endian: str = ""
    elf_type: str = ""
    dwarf_version: Optional[int] = None
    cu_count: int = 0
    variable_count: int = 0
    has_debug_info: bool = False
    sections: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def arch_str(self) -> str:
        if not self.arch:
            return "未知架构"
        bits = f"{self.bits}-bit" if self.bits else ""
        endian = "LE" if self.endian == "little" else ("BE" if self.endian else "")
        return " ".join(x for x in (self.arch, bits, endian) if x)


@dataclass
class ParseResult:
    info: ElfInfo
    variables: list[Variable] = field(default_factory=list)
