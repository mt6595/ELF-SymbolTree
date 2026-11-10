"""探测 pyelftools 0.33 API 与本样本 DWARF 形态。"""
import sys
from elftools.elf.elffile import ELFFile

path = r"C:/Users/Atomiz/WorkBuddy/2026-11-06-00-02-57/samples/demo.elf"

with open(path, "rb") as f:
    elf = ELFFile(f)
    print("== ELF header ==")
    print(" arch:", elf.get_machine_arch(), "| bitness:", elf.elfclass, "| endian:", elf.little_endian and "LE" or "BE")
    print(" sections:", [s.name for s in elf.iter_sections() if s.name.startswith(".debug")])
    dw = elf.get_dwarf_info()
    print(" dwarf versions by CU:", [cu["version"] for cu in dw.iter_CUs()])
    print(" class:", type(dw).__name__, "| attrs:", [a for a in dir(dw) if "addr" in a.lower() or "section" in a.lower()])

    from elftools.dwarf.descriptions import describe_form_class
    from elftools.dwarf.locationlists import LocationParser

    stat_counts = {}
    bitfield_example = None
    var_examples = []
    loc_examples = []
    for cu in dw.iter_CUs():
        top = cu.get_top_DIE()
        atrs = {a: describe_form_class(top.attributes[a].form) for a in top.attributes}
        if "DW_AT_addr_base" in top.attributes:
            print(" CU addr_base attr form:", atrs.get("DW_AT_addr_base"))
        for die in cu.iter_DIEs():
            tag = die.tag or "<null>"
            stat_counts[tag] = stat_counts.get(tag, 0) + 1
            if tag in ("DW_TAG_member",) and "DW_AT_bit_size" in die.attributes:
                if bitfield_example is None and "DW_AT_name" in die.attributes:
                    nm = die.attributes["DW_AT_name"].value
                    nm = nm.decode() if isinstance(nm, bytes) else str(nm)
                    attrs = {k: describe_form_class(v.form) for k, v in die.attributes.items()}
                    raw = {k: v.value for k, v in die.attributes.items()
                           if k in ("DW_AT_data_member_location", "DW_AT_data_bit_offset",
                                    "DW_AT_bit_offset", "DW_AT_bit_size", "DW_AT_byte_size")}
                    bitfield_example = (nm, attrs, raw)
            if tag == "DW_TAG_variable":
                nm = die.attributes.get("DW_AT_name")
                nm = nm.value if nm else b"?n"
                if isinstance(nm, bytes):
                    nm = nm.decode(errors="replace")
                loc = die.attributes.get("DW_AT_location")
                var_examples.append((nm, loc.form if loc else None,
                                     describe_form_class(loc.form) if loc else None))
    print()
    print("== DIE tag 统计 ==")
    for k in sorted(stat_counts):
        print(f"  {k}: {stat_counts[k]}")
    print()
    print("== 位域成员示例 ==")
    if bitfield_example:
        nm, attrs, raw = bitfield_example
        print("  name:", nm)
        print("  attr forms:", attrs)
        print("  raw values:", {k: (v if isinstance(v, int) else repr(v)) for k, v in raw.items()})
    print()
    print("== 变量 location 示例(前 12 个)==")
    for e in var_examples[:12]:
        print("  ", e)