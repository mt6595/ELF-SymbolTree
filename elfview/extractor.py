"""ELF + DWARF 解析器:把调试信息还原为可浏览的变量类型树。

设计要点
--------
* 只解析 DWARF 的"类型定义"层,成员展开在构建变量树时按需递归,
  因此自引用结构体(链表)不会造成无限递归(指针不展开)。
* 地址来源优先级:DW_OP_addr > DW_OP_addrx/GNU_addr_index > 符号表同名符号。
* 位域同时兼容 DWARF4+ 的 DW_AT_data_bit_offset 与旧式
  DW_AT_bit_offset + DW_AT_data_member_location 两种编码。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from elftools.elf.constants import SH_FLAGS
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
from elftools.dwarf.dwarf_expr import DWARFExprParser

from .model import ElfInfo, Kind, Node, ParseResult, Variable


class ElfParseError(Exception):
    """ELF 无法解析或缺少必要调试信息。"""


@dataclass
class TypeDesc:
    """类型的浅描述(不递归成员),用于展示与后续展开。"""

    display: str = "<unknown>"
    kind: str = Kind.BASE
    size: Optional[int] = None
    die_offset: Optional[int] = None
    element: Optional["TypeDesc"] = None      # 数组元素 / 指针目标
    counts: tuple = ()                        # 数组各维长度
    target: Optional["TypeDesc"] = None       # 指针目标
    enum_values: list = field(default_factory=list)
    qualifiers: tuple = ()
    typedefs: tuple = ()
    encoding: Optional[int] = None


def _attr(die, name, default=None):
    a = die.attributes.get(name)
    if a is None:
        return default
    return a.value


def _die_name(die) -> Optional[str]:
    v = _attr(die, "DW_AT_name")
    if v is None:
        return None
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return str(v)


def _as_int(v) -> Optional[int]:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, (list, tuple)) and v:
        # 退化处理:表达式最后一个操作数通常是偏移常量
        for token in reversed(v):
            if isinstance(token, int):
                return token
    return None


class ElfAnalyzer:
    """解析一个 ELF,产出带完整类型树的变量列表。"""

    MAX_DEPTH = 24
    MAX_NODES = 120000

    def __init__(
        self,
        path: str,
        max_array: int = 256,
        include_local_static: bool = True,
    ) -> None:
        self.path = path
        self.max_array = max_array
        self.include_local_static = include_local_static

        self._dw = None
        self.pointer_size = 4
        self._type_cache: dict[int, TypeDesc] = {}
        self._cu_by_die: dict[int, object] = {}
        self._die_cache: dict[int, object] = {}
        self._symbols: dict[str, tuple] = {}
        self._segments: list[tuple[int, int, str]] = []
        self._node_count = 0
        self._warnings: list[str] = []
        self._bits_estimated = 0
        self._arrays_truncated = 0
        self._loclists_pair = False  # False = 尚未初始化
        self._loclist_hits = 0
        self._loclist_misses = 0
        self._symbol_fallbacks = 0
        self._dynamic_skipped = 0
        self._unallocated = 0
        self._elf_type = "ET_EXEC"

    # ------------------------------------------------------------------ 入口
    def analyze(self) -> ParseResult:
        if not os.path.isfile(self.path):
            raise ElfParseError(f"文件不存在: {self.path}")

        with open(self.path, "rb") as fp:
            try:
                elf = ELFFile(fp)
            except Exception as exc:  # noqa: BLE001
                raise ElfParseError(
                    "不是有效的 ELF 文件。注意:IAR 的 .out / KEIL 的 .axf 也可能是 "
                    f"其他格式,请确认使用 ELF 输出。原始错误: {exc}"
                ) from exc

            info = ElfInfo(path=self.path)
            info.arch = elf.get_machine_arch() or ""
            info.bits = elf.elfclass
            info.endian = "little" if elf.little_endian else "big"
            info.elf_type = elf.header["e_type"]
            self._elf_type = info.elf_type
            self.pointer_size = elf.elfclass // 8

            self._collect_segments(elf)
            self._collect_symbols(elf)
            info.sections = [
                {"name": n, "address": a, "size": s}
                for a, s, n in self._segments
            ]

            try:
                dw = elf.get_dwarf_info()
            except Exception as exc:  # noqa: BLE001
                raise ElfParseError(f"读取 DWARF 调试信息失败: {exc}") from exc

            if dw is None or not getattr(dw, "has_debug_info", False):
                raise ElfParseError(
                    "该 ELF 不含 DWARF 调试信息(.debug_info)。\n"
                    "请在工程中开启调试符号后重新编译:\n"
                    "  · STM32CubeIDE / GCC: -g3(不要 strip)\n"
                    "  · IAR: Project > Options > C/C++ Compiler > Output > Generate debug information\n"
                    "  · KEIL: Options for Target > Output > Debug Information + Browse Information"
                )

            self._dw = dw
            self._index_dies(dw)

            info.dwarf_version = None
            cu_list = []
            for cu in dw.iter_CUs():
                cu_list.append(cu)
                if info.dwarf_version is None:
                    info.dwarf_version = cu["version"]
            info.cu_count = len(cu_list)
            info.has_debug_info = True

            variables: list[Variable] = []
            seen: set[tuple[str, int]] = set()
            for cu in cu_list:
                top = cu.get_top_DIE()
                cu_name = _die_name(top) or ""
                self._collect_variables(
                    cu, top, "", in_function=False, out=variables, seen=seen, cu_name=cu_name
                )

            variables.sort(key=lambda v: (v.address if v.address is not None else 1 << 62, v.name))

            if self._bits_estimated:
                self._warnings.append(
                    f"{self._bits_estimated} 个位域实例使用旧式 DW_AT_bit_offset 编码,"
                    "位序为按小端规则推算,已在详情中标注为 estimated"
                )
            if self._arrays_truncated:
                self._warnings.append(
                    f"{self._arrays_truncated} 个数组超过 {self.max_array} 个元素的展示上限,已截断"
                )
            if self._loclist_misses:
                self._warnings.append(
                    f"{self._loclist_misses} 个变量的位置列表无法解析为静态地址,已用符号表兜底"
                )
            if self._unallocated:
                self._warnings.append(
                    f"{self._unallocated} 个变量在调试信息中没有有效地址"
                    "(多为头文件中声明后未使用的变量,已被链接器丢弃),默认隐藏"
                )

            info.variable_count = len(variables)
            info.warnings = list(self._warnings)
            return ParseResult(info=info, variables=variables)

    # -------------------------------------------------------------- ELF 基础
    def _collect_segments(self, elf) -> None:
        for sec in elf.iter_sections():
            try:
                flags = int(sec["sh_flags"])
                addr = int(sec["sh_addr"])
                size = int(sec["sh_size"])
            except Exception:  # noqa: BLE001
                continue
            if flags & SH_FLAGS.SHF_ALLOC and size > 0:
                self._segments.append((addr, size, sec.name))

    def _collect_symbols(self, elf) -> None:
        for sec in elf.iter_sections():
            if not isinstance(sec, SymbolTableSection):
                continue
            for sym in sec.iter_symbols():
                if not sym.name:
                    continue
                try:
                    stype = sym["st_info"]["type"]
                    if stype not in ("STT_OBJECT", "STT_NOTYPE"):
                        continue
                    value = int(sym["st_value"])
                    size = int(sym["st_size"])
                    bind = sym["st_info"]["bind"]
                except Exception:  # noqa: BLE001
                    continue
                prev = self._symbols.get(sym.name)
                if prev is None or (prev[0] == 0 and value != 0):
                    self._symbols[sym.name] = (value, size, bind)

    def section_of(self, address: Optional[int]) -> str:
        if address is None:
            return ""
        for start, size, name in self._segments:
            if start <= address < start + size:
                return name
        return ""

    # ------------------------------------------------------------- DIE 索引
    def _index_dies(self, dw) -> None:
        try:
            units = list(dw.iter_CUs())
        except Exception as exc:  # noqa: BLE001
            raise ElfParseError(f"遍历编译单元失败(可能是 DWARF 版本或格式损坏): {exc}") from exc
        for cu in units:
            for die in cu.iter_DIEs():
                if not die.tag:
                    continue
                self._die_cache[die.offset] = die
                self._cu_by_die[die.offset] = cu

    def _die(self, offset: Optional[int]):
        if offset is None:
            return None
        return self._die_cache.get(offset)

    def _type_die(self, die):
        if "DW_AT_type" not in die.attributes:
            return None
        try:
            return die.get_DIE_from_attribute("DW_AT_type")
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------- 类型解析
    def _type_desc(self, die, depth: int = 0) -> Optional[TypeDesc]:
        if die is None:
            return None
        if depth > 16:
            return TypeDesc(display="<类型递归>", kind=Kind.BASE)
        cached = self._type_cache.get(die.offset)
        if cached is not None:
            return cached

        tag = die.tag
        result: Optional[TypeDesc] = None

        if tag in (
            "DW_TAG_const_type",
            "DW_TAG_volatile_type",
            "DW_TAG_restrict_type",
            "DW_TAG_atomic_type",
        ):
            inner = self._type_die(die)
            inner_desc = self._type_desc(inner, depth + 1) if inner is not None else TypeDesc(
                display="void", kind=Kind.BASE
            )
            qname = {
                "DW_TAG_const_type": "const",
                "DW_TAG_volatile_type": "volatile",
                "DW_TAG_restrict_type": "restrict",
                "DW_TAG_atomic_type": "_Atomic",
            }[tag]
            prefix = f"{qname} "
            qualified_display = (
                inner_desc.display
                if inner_desc.display.startswith(prefix)
                else prefix + inner_desc.display
            )
            result = TypeDesc(
                display=qualified_display,
                kind=inner_desc.kind,
                size=inner_desc.size,
                die_offset=inner_desc.die_offset,
                element=inner_desc.element,
                counts=inner_desc.counts,
                target=inner_desc.target,
                enum_values=inner_desc.enum_values,
                qualifiers=(qname,) + inner_desc.qualifiers,
                typedefs=inner_desc.typedefs,
                encoding=inner_desc.encoding,
            )

        elif tag == "DW_TAG_typedef":
            name = _die_name(die) or "<typedef>"
            inner = self._type_die(die)
            inner_desc = self._type_desc(inner, depth + 1) if inner is not None else TypeDesc(
                display="void", kind=Kind.BASE
            )
            result = TypeDesc(
                display=name,
                kind=inner_desc.kind,
                size=inner_desc.size,
                die_offset=inner_desc.die_offset,
                element=inner_desc.element,
                counts=inner_desc.counts,
                target=inner_desc.target,
                enum_values=inner_desc.enum_values,
                qualifiers=inner_desc.qualifiers,
                typedefs=(name,) + inner_desc.typedefs,
                encoding=inner_desc.encoding,
            )

        elif tag in ("DW_TAG_structure_type", "DW_TAG_class_type", "DW_TAG_union_type"):
            name = _die_name(die)
            kind = Kind.UNION if tag == "DW_TAG_union_type" else Kind.STRUCT
            label = "union" if kind == Kind.UNION else "struct"
            result = TypeDesc(
                display=name if name else f"<anonymous {label}>",
                kind=kind,
                size=_as_int(_attr(die, "DW_AT_byte_size")),
                die_offset=die.offset,
            )

        elif tag == "DW_TAG_enumeration_type":
            name = _die_name(die)
            values = []
            for child in die.iter_children():
                if child.tag == "DW_TAG_enumerator":
                    values.append(
                        (_die_name(child) or "?", _as_int(_attr(child, "DW_AT_const_value")))
                    )
            result = TypeDesc(
                display=name if name else "<anonymous enum>",
                kind=Kind.ENUM,
                size=_as_int(_attr(die, "DW_AT_byte_size")) or 4,
                die_offset=die.offset,
                enum_values=values,
            )

        elif tag == "DW_TAG_array_type":
            inner = self._type_die(die)
            elem = self._type_desc(inner, depth + 1) if inner is not None else TypeDesc(
                display="void", kind=Kind.BASE
            )
            counts = []
            for child in die.iter_children():
                if child.tag != "DW_TAG_subrange_type":
                    continue
                count = _as_int(_attr(child, "DW_AT_count"))
                if count is None:
                    upper = _as_int(_attr(child, "DW_AT_upper_bound"))
                    lower = _as_int(_attr(child, "DW_AT_lower_bound")) or 0
                    if upper is not None:
                        count = upper - lower + 1
                counts.append(int(count or 0))
            total = 1
            for c in counts:
                total *= c
            elem_size = elem.size or 0
            size = total * elem_size if elem_size else _as_int(_attr(die, "DW_AT_byte_size"))
            dims = "".join(f"[{c}]" for c in counts)
            result = TypeDesc(
                display=f"{elem.display}{dims}",
                kind=Kind.ARRAY,
                size=size,
                die_offset=die.offset,
                element=elem,
                counts=tuple(counts),
            )

        elif tag in (
            "DW_TAG_pointer_type",
            "DW_TAG_reference_type",
            "DW_TAG_rvalue_reference_type",
        ):
            inner = self._type_die(die)
            target = self._type_desc(inner, depth + 1) if inner is not None else TypeDesc(
                display="void", kind=Kind.BASE, size=None
            )
            size = _as_int(_attr(die, "DW_AT_byte_size")) or self.pointer_size
            pointer_mark = "&" if tag != "DW_TAG_pointer_type" else "*"
            result = TypeDesc(
                display=f"{target.display} {pointer_mark}",
                kind=Kind.POINTER,
                size=size,
                die_offset=die.offset,
                target=target,
            )

        elif tag == "DW_TAG_subroutine_type":
            result = TypeDesc(
                display="函数",
                kind=Kind.FUNCTION,
                size=_as_int(_attr(die, "DW_AT_byte_size")) or self.pointer_size,
                die_offset=die.offset,
            )

        elif tag in ("DW_TAG_base_type", "DW_TAG_unspecified_type"):
            result = TypeDesc(
                display=_die_name(die) or "void",
                kind=Kind.BASE,
                size=_as_int(_attr(die, "DW_AT_byte_size")),
                die_offset=die.offset,
                encoding=_as_int(_attr(die, "DW_AT_encoding")),
            )

        else:
            result = TypeDesc(
                display=_die_name(die) or tag.replace("DW_TAG_", "").replace("_type", ""),
                kind=Kind.BASE,
                size=_as_int(_attr(die, "DW_AT_byte_size")),
                die_offset=die.offset,
            )

        self._type_cache[die.offset] = result
        return result

    # ------------------------------------------------------------- 变量收集
    def _collect_variables(self, cu, die, scope: str, in_function: bool, out: list, seen: set, cu_name: str = "") -> None:
        for child in die.iter_children():
            tag = child.tag

            if tag == "DW_TAG_subprogram":
                func_name = _die_name(child) or "<function>"
                if _attr(child, "DW_AT_declaration"):
                    continue
                self._collect_variables(
                    cu, child, func_name, in_function=True, out=out, seen=seen, cu_name=cu_name
                )
                continue

            if tag == "DW_TAG_variable":
                if in_function and not self.include_local_static:
                    continue
                var = self._make_variable(cu, child, scope, in_function, cu_name)
                if var is None:
                    continue
                # 同一已分配符号在多个 CU 中重复出现时合并;不同地址的 file-static 保留。
                # 未分配变量没有可比较地址,用 CU/作用域/类型区分,避免全被折叠到 address=0。
                if var.allocated:
                    key = ("allocated", var.name, int(var.address or 0))
                else:
                    key = ("unallocated", var.name, var.cu_name, var.scope, var.type_str)
                if key in seen:
                    continue
                seen.add(key)
                out.append(var)
                continue

            if tag in ("DW_TAG_lexical_block", "DW_TAG_namespace", "DW_TAG_class_type"):
                self._collect_variables(
                    cu, child, scope, in_function=in_function, out=out, seen=seen, cu_name=cu_name
                )

    def _make_variable(self, cu, die, scope: str, in_function: bool, cu_name: str = "") -> Optional[Variable]:
        name = _die_name(die)
        if not name or name.startswith("__"):
            return None
        if _attr(die, "DW_AT_declaration"):
            return None
        if "DW_AT_type" not in die.attributes:
            return None

        address = self._address_of(cu, die, name)
        if address is None:
            return None

        allocated = True
        unallocated_reason = ""
        if self._elf_type == "ET_REL":
            # 可重定位目标文件中的 st_value/DW_OP_addr 不是最终绝对地址。
            allocated = False
            unallocated_reason = "未链接的目标文件(ET_REL),当前只有段内偏移,不是绝对地址"
        elif address == 0 and self.section_of(0) == "":
            # 调试信息里有 DW_OP_addr 0 但落不进任何可分配段:
            # 常见于头文件中定义后在链接阶段被丢弃的变量
            allocated = False
            unallocated_reason = "调试信息未给出有效地址(可能被优化/链接丢弃)"

        if not allocated:
            node_address = None
        else:
            node_address = address

        type_desc = self._type_desc(self._type_die(die))
        if type_desc is None:
            return None

        sym = self._symbols.get(name)
        symbol_size = sym[1] if sym else None
        size = type_desc.size if type_desc.size is not None else symbol_size

        node = self._build_node(name, type_desc, node_address, 0, Kind.VARIABLE, 0)
        node.address = node_address
        if self._elf_type == "ET_REL":
            node.extra["section_offset_unrelocated"] = address
        if node.size is None:
            node.size = size
        node.tag = die.tag
        node.die_offset = die.offset
        node.extra["canonical_type"] = type_desc.display
        if type_desc.typedefs:
            node.extra["typedef_chain"] = " → ".join(type_desc.typedefs)
        if type_desc.qualifiers:
            node.extra["qualifiers"] = " ".join(type_desc.qualifiers)
        if type_desc.kind == Kind.ENUM:
            node.extra["enum_values"] = type_desc.enum_values
        if type_desc.kind == Kind.POINTER and type_desc.target is not None:
            node.extra["pointer_target"] = type_desc.target.display
            node.extra["pointer_target_size"] = type_desc.target.size
        if type_desc.kind == Kind.ARRAY:
            node.extra["array_dims"] = "".join(f"[{c}]" for c in type_desc.counts)
        decl_line = _attr(die, "DW_AT_decl_line")
        if decl_line:
            node.extra["decl_line"] = int(decl_line)

        if in_function:
            linkage = "local-static"
        elif sym is not None and sym[2] == "STB_LOCAL":
            linkage = "static"
        else:
            linkage = "global"

        if not allocated:
            self._unallocated += 1

        return Variable(
            node=node,
            linkage=linkage,
            scope=scope,
            section=self.section_of(node_address),
            symbol_size=symbol_size,
            allocated=allocated,
            unallocated_reason=unallocated_reason,
            cu_name=cu_name,
        )

    # --------------------------------------------------------------- 地址解析
    def _address_of(self, cu, die, name: str) -> Optional[int]:
        kind, address = self._locate(cu, die)
        if kind == "static":
            return address
        if kind == "dynamic":
            # 寄存器/栈帧相对位置:函数内局部变量,静态分析没有确定地址,必须排除
            self._dynamic_skipped += 1
            return None

        # location 缺失或无法解码:用符号表兜底(全局/静态变量通常有符号)
        sym = self._symbols.get(name)
        if sym is not None and sym[0] != 0:
            self._symbol_fallbacks += 1
            return sym[0]
        return None

    def _locate(self, cu, die):
        """返回 (kind, address),kind: static / dynamic / unknown。"""
        loc = die.attributes.get("DW_AT_location")
        if loc is None:
            return "unknown", None

        form = loc.form
        if form == "DW_FORM_exprloc" or form.startswith("DW_FORM_block"):
            return self._expr_location(cu, loc.value)

        if form in ("DW_FORM_sec_offset", "DW_FORM_data4", "DW_FORM_data8"):
            offset = _as_int(loc.value)
            if offset is None:
                return "unknown", None
            kind, address = self._loclist_location(cu, die, offset)
            if kind == "static":
                self._loclist_hits += 1
            elif kind == "unknown":
                self._loclist_misses += 1
            return kind, address

        return "unknown", None

    def _expr_location(self, cu, value):
        if not isinstance(value, (list, tuple)) or not value:
            return "unknown", None
        try:
            ops = DWARFExprParser(cu.structs).parse_expr(value)
        except Exception:  # noqa: BLE001
            return "unknown", None

        for op in ops:
            if op.op_name == "DW_OP_addr":
                return "static", int(op.args[0])
            if op.op_name in ("DW_OP_addrx", "DW_OP_GNU_addr_index"):
                try:
                    return "static", int(self._dw.get_addr(cu, int(op.args[0])))
                except Exception:  # noqa: BLE001
                    return "unknown", None
        if ops:
            # 寄存器 / 栈帧相对 / CFA 等:动态位置
            return "dynamic", None
        return "unknown", None

    def _loclists(self):
        if self._loclists_pair is False:
            try:
                self._loclists_pair = self._dw.location_lists()
            except Exception:  # noqa: BLE001
                self._loclists_pair = None
        return self._loclists_pair

    def _loclist_location(self, cu, die, offset: int):
        pair = self._loclists()
        if pair is None:
            return "unknown", None
        try:
            entries = pair.get_location_list_at_offset(offset, die)
        except Exception:  # noqa: BLE001
            return "unknown", None
        if not entries:
            return "unknown", None

        saw_dynamic = False
        for entry in entries:
            expr = getattr(entry, "loc_expr", None)
            if not expr:
                continue
            kind, address = self._expr_location(cu, expr)
            if kind == "static":
                return "static", address
            if kind == "dynamic":
                saw_dynamic = True
        return ("dynamic", None) if saw_dynamic else ("unknown", None)

    def _expr_address(self, cu, value) -> Optional[int]:
        kind, address = self._expr_location(cu, value)
        return address if kind == "static" else None

    def _expr_address(self, cu, value) -> Optional[int]:
        if not isinstance(value, (list, tuple)) or not value:
            return None
        try:
            ops = DWARFExprParser(cu.structs).parse_expr(value)
        except Exception:  # noqa: BLE001
            return None
        for op in ops:
            if op.op_name == "DW_OP_addr":
                return int(op.args[0])
            if op.op_name in ("DW_OP_addrx", "DW_OP_GNU_addr_index"):
                try:
                    return int(self._dw.get_addr(cu, int(op.args[0])))
                except Exception:  # noqa: BLE001
                    return None
            if op.op_name in ("DW_OP_constu", "DW_OP_const4u", "DW_OP_const8u"):
                return int(op.args[0])
        return None

    # --------------------------------------------------------------- 树构建
    def _build_node(
        self,
        name: str,
        type_desc: TypeDesc,
        address: Optional[int],
        offset: Optional[int],
        kind: str,
        depth: int,
    ) -> Node:
        node = Node(
            name=name or "<anonymous>",
            type_str=type_desc.display,
            kind=kind,
            offset=offset,
            address=address,
            size=type_desc.size,
            die_offset=type_desc.die_offset,
        )
        self._node_count += 1

        if depth >= self.MAX_DEPTH or self._node_count > self.MAX_NODES:
            node.extra["truncated"] = True
            return node

        if type_desc.kind in (Kind.STRUCT, Kind.UNION):
            self._fill_members(node, type_desc, depth)
        elif type_desc.kind == Kind.ARRAY:
            self._fill_array(node, type_desc, depth)
        elif type_desc.kind == Kind.ENUM:
            node.extra["enum_values"] = type_desc.enum_values
        elif type_desc.kind == Kind.POINTER and type_desc.target is not None:
            node.extra["pointer_target"] = type_desc.target.display
            if type_desc.target.size is not None:
                node.extra["pointer_target_size"] = type_desc.target.size

        return node

    def _fill_members(self, node: Node, type_desc: TypeDesc, depth: int) -> None:
        die = self._die(type_desc.die_offset)
        if die is None:
            return
        cu = self._cu_by_die.get(die.offset)

        is_union = type_desc.kind == Kind.UNION
        for child in die.iter_children():
            if child.tag != "DW_TAG_member":
                continue
            member_name = _die_name(child)
            if member_name is None:
                member_name = f"<anonymous+0x{0:x}>"

            member_offset = self._member_offset(cu, child)
            if member_offset is None:
                member_offset = 0 if is_union else 0

            member_type_die = self._type_die(child)
            member_type = self._type_desc(member_type_die)
            if member_type is None:
                continue

            bit_size = _as_int(_attr(child, "DW_AT_bit_size"))
            bit_offset = None
            if bit_size is not None:
                bit_offset = self._bit_offset(cu, child, member_type, member_offset)

            member_address = (
                node.address + member_offset if node.address is not None else None
            )
            child_node = self._build_node(
                member_name,
                member_type,
                member_address,
                member_offset,
                member_type.kind,
                depth + 1,
            )
            child_node.tag = child.tag
            child_node.die_offset = child.offset

            if bit_size is not None:
                child_node.kind = Kind.BITFIELD
                child_node.bit_size = int(bit_size)
                child_node.bit_offset = bit_offset
                child_node.size = member_type.size
                child_node.extra["bit_container"] = member_type.display
                if node.address is not None and bit_offset is not None:
                    child_node.extra["abs_bit"] = node.address * 8 + bit_offset
                if bit_offset is None:
                    child_node.extra["bit_offset_unknown"] = True

            decl_line = _attr(child, "DW_AT_decl_line")
            if decl_line:
                child_node.extra["decl_line"] = int(decl_line)

            node.children.append(child_node)

        if node.size is None and node.children:
            end = 0
            for c in node.children:
                end = max(end, (c.offset or 0) + (c.size or 0))
            node.size = end

    def _fill_array(self, node: Node, type_desc: TypeDesc, depth: int) -> None:
        counts = list(type_desc.counts)
        if not counts:
            return
        count = counts[0]
        elem = type_desc.element
        if elem is None:
            return

        if len(counts) > 1:
            rest_counts = tuple(counts[1:])
            rest_size = 1
            for c in rest_counts:
                rest_size *= c
            rest_size *= elem.size or 0
            dims = "".join(f"[{c}]" for c in rest_counts)
            elem_type = TypeDesc(
                display=f"{elem.display}{dims}",
                kind=Kind.ARRAY,
                size=rest_size,
                die_offset=type_desc.die_offset,
                element=elem,
                counts=rest_counts,
            )
        else:
            elem_type = elem

        elem_size = elem_type.size or 0
        limit = min(count, self.max_array)
        if count > limit:
            self._arrays_truncated += 1
            node.extra["truncated_array"] = (count, limit)

        for index in range(limit):
            base = node.address
            child_address = base + index * elem_size if base is not None and elem_size else None
            child = self._build_node(
                f"[{index}]",
                elem_type,
                child_address,
                index * elem_size,
                Kind.ELEMENT,
                depth + 1,
            )
            child.extra["index"] = index
            node.children.append(child)

        if count > limit:
            node.children.append(
                Node(
                    name=f"… 其余 {count - limit} 项已省略",
                    type_str="",
                    kind=Kind.ELEMENT,
                    offset=limit * elem_size,
                    size=(count - limit) * elem_size,
                    extra={"truncated": True},
                )
            )

    # --------------------------------------------------------------- 位域辅助
    def _member_offset(self, cu, die) -> Optional[int]:
        value = _attr(die, "DW_AT_data_member_location")
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, (list, tuple)):
            if cu is not None:
                try:
                    ops = DWARFExprParser(cu.structs).parse_expr(value)
                    for op in ops:
                        if op.op_name in (
                            "DW_OP_plus_uconst",
                            "DW_OP_constu",
                            "DW_OP_consts",
                        ):
                            return int(op.args[0])
                except Exception:  # noqa: BLE001
                    pass
            return _as_int(value)
        return 0

    def _bit_offset(self, cu, die, member_type: TypeDesc, member_offset: int) -> Optional[int]:
        """返回位域相对父结构体起始、按 LSB 计的位偏移。"""
        data_bit_offset = _as_int(_attr(die, "DW_AT_data_bit_offset"))
        if data_bit_offset is not None:
            return data_bit_offset

        bit_size = _as_int(_attr(die, "DW_AT_bit_size")) or 0
        bit_offset = _as_int(_attr(die, "DW_AT_bit_offset"))
        if bit_offset is None:
            return member_offset * 8

        # 旧式编码:相对存储单元的 MSB,按小端换算到 LSB
        container_bits = (member_type.size or 0) * 8
        if container_bits <= 0:
            self._bits_estimated += 1
            return member_offset * 8
        lsb = container_bits - bit_offset - bit_size
        if lsb < 0:
            lsb = bit_offset
        self._bits_estimated += 1
        return member_offset * 8 + lsb
