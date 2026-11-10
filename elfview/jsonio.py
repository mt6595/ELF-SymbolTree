"""把解析结果序列化为 JSON,便于外部程序/脚本复用。"""
from __future__ import annotations

from .model import Node, ParseResult


def node_to_dict(node: Node) -> dict:
    data = {
        "name": node.name,
        "type": node.type_str,
        "kind": node.kind,
        "offset": node.offset,
        "address": node.address,
        "size": node.size,
        "bit_offset": node.bit_offset,
        "bit_size": node.bit_size,
    }
    if node.children:
        data["children"] = [node_to_dict(c) for c in node.children]
    if node.extra:
        data["extra"] = {k: v for k, v in node.extra.items() if not callable(v)}
    return data


def result_to_dict(result: ParseResult) -> dict:
    info = result.info
    elf = {
        "path": info.path,
        "arch": info.arch,
        "bits": info.bits,
        "endian": info.endian,
        "elf_type": info.elf_type,
        "dwarf_version": info.dwarf_version,
        "cu_count": info.cu_count,
        "sections": info.sections,
        "warnings": list(info.warnings),
    }
    variables = []
    for var in result.variables:
        node = var.node
        variables.append(
            {
                "name": var.name,
                "type": node.type_str,
                "address": node.address,
                "size": node.size,
                "section": var.section,
                "linkage": var.linkage,
                "scope": var.scope,
                "tree": node_to_dict(node),
            }
        )
    return {"elf": elf, "variable_count": len(variables), "variables": variables}