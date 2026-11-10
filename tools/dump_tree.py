"""命令行树形输出,用于校验解析结果或批量导出。

用法:
    python tools/dump_tree.py <xxx.elf> [变量名过滤]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elfview import ElfAnalyzer, ElfParseError, Kind  # noqa: E402

MARK = {
    Kind.STRUCT: "struct",
    Kind.UNION: "union",
    Kind.ARRAY: "array",
    Kind.BITFIELD: "bitfield",
    Kind.POINTER: "ptr",
    Kind.ENUM: "enum",
}


def fmt_addr(value) -> str:
    return f"0x{value:08X}" if value is not None else "-"


def fmt_size(value) -> str:
    return f"{value}" if value is not None else "-"


def print_node(node, prefix="", is_last=True) -> None:
    branch = "" if not prefix else ("└─ " if is_last else "├─ ")
    kind = MARK.get(node.kind, node.kind)
    extra = ""
    if node.is_bitfield:
        extra = f"  [{node.bit_range_str}, {node.size * 8 if node.size else '?'} bit container]"
    print(
        f"{prefix}{branch}{node.name:<24} {node.type_str:<28} "
        f"off={fmt_addr(node.offset)} addr={fmt_addr(node.address)} "
        f"size={fmt_size(node.size):>4} {kind}{extra}"
    )
    child_prefix = prefix + ("" if not prefix else ("   " if is_last else "│  "))
    for i, child in enumerate(node.children):
        print_node(child, child_prefix, i == len(node.children) - 1)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    keyword = sys.argv[2].lower() if len(sys.argv) > 2 else None

    try:
        result = ElfAnalyzer(path).analyze()
    except ElfParseError as exc:
        print(f"[错误] {exc}")
        return 1

    info = result.info
    print("=" * 100)
    print(f"文件     : {info.path}")
    print(f"架构     : {info.arch_str}  类型: {info.elf_type}")
    print(f"DWARF    : v{info.dwarf_version}  编译单元: {info.cu_count}  变量: {info.variable_count}")
    for warning in info.warnings:
        print(f"[提示] {warning}")
    print("=" * 100)

    for var in result.variables:
        if keyword and keyword not in var.name.lower():
            continue
        node = var.node
        print()
        flag = "" if var.allocated else "  [未分配]"
        print(
            f"● {node.name}  |  {node.type_str}  |  addr={fmt_addr(node.address)}  "
            f"size={fmt_size(node.size)}  |  {var.section or '-'}  |  {var.linkage}{flag}"
            + (f"  (in {var.scope})" if var.scope else "")
        )
        if node.extra.get("typedef_chain"):
            print(f"  typedef: {node.extra['typedef_chain']}")
        for i, child in enumerate(node.children):
            print_node(child, "  ", i == len(node.children) - 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
