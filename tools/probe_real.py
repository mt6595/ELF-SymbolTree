"""探测真实样本的 ELF / DWARF 形态差异。"""
import os
import sys

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

FILES = [
    r"C:\Users\Atomiz\Desktop\Test\STM32CubeIDE.elf",
    r"C:\Users\Atomiz\Desktop\Test\IAR.out",
    r"C:\Users\Atomiz\Desktop\Test\KEIL.axf",
]


def probe(path):
    print("=" * 90)
    print(path, "|", os.path.getsize(path), "bytes")
    with open(path, "rb") as fp:
        magic = fp.read(4)
        print("   magic:", magic)
        if magic != b"\x7fELF":
            print("   >>> NOT an ELF file")
            return
        fp.seek(0)
        elf = ELFFile(fp)
        print("   arch:", elf.get_machine_arch(), "| class:", elf.elfclass,
              "| LE" if elf.little_endian else "| BE", "| type:", elf.header["e_type"])
        sections = [s.name for s in elf.iter_sections()]
        print("   debug sections:", [s for s in sections if s.startswith(".debug")])

        symbols = 0
        for sec in elf.iter_sections():
            if isinstance(sec, SymbolTableSection):
                symbols += sum(1 for _ in sec.iter_symbols())
        print("   symbols:", symbols)

        try:
            dw = elf.get_dwarf_info()
        except Exception as exc:  # noqa: BLE001
            print("   >>> DWARF error:", exc)
            return

        if not getattr(dw, "has_debug_info", False):
            print("   >>> NO .debug_info")
            return

        versions = []
        cu_count = 0
        tag_counts = {}
        bitfield_forms = {}
        loc_forms = {}
        type_forms = {}
        addr_kinds = {}
        for cu in dw.iter_CUs():
            cu_count += 1
            versions.append(cu["version"])
            for die in cu.iter_DIEs():
                tag = die.tag
                if not tag:
                    continue
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                if tag == "DW_TAG_member" and "DW_AT_bit_size" in die.attributes:
                    attrs = die.attributes
                    if "DW_AT_data_bit_offset" in attrs:
                        key = "data_bit_offset"
                    elif "DW_AT_bit_offset" in attrs:
                        key = "bit_offset(legacy)"
                    else:
                        key = "none"
                    if "DW_AT_data_member_location" in attrs:
                        key += "+data_member_location"
                    bitfield_forms[key] = bitfield_forms.get(key, 0) + 1
                if tag == "DW_TAG_variable":
                    loc = die.attributes.get("DW_AT_location")
                    if loc is None:
                        loc_forms["<none>"] = loc_forms.get("<none>", 0) + 1
                    else:
                        loc_forms[loc.form] = loc_forms.get(loc.form, 0) + 1
                    t = die.attributes.get("DW_AT_type")
                    if t is not None:
                        type_forms[t.form] = type_forms.get(t.form, 0) + 1
                if "DW_AT_type" in die.attributes:
                    f = die.attributes["DW_AT_type"].form
                    type_forms[f] = type_forms.get(f, 0) + 1

        print("   CU:", cu_count, "| DWARF versions:", sorted(set(versions)))
        print("   DW_AT_type forms:", type_forms)
        print("   variable location forms:", loc_forms)
        print("   bitfield encodings:", bitfield_forms)
        keys = ["DW_TAG_variable", "DW_TAG_structure_type", "DW_TAG_union_type",
                "DW_TAG_member", "DW_TAG_array_type", "DW_TAG_enumeration_type",
                "DW_TAG_typedef", "DW_TAG_pointer_type", "DW_TAG_subprogram",
                "DW_TAG_compile_unit", "DW_TAG_base_type"]
        print("   tags:", {k: tag_counts.get(k, 0) for k in keys})


if __name__ == "__main__":
    for f in (sys.argv[1:] or FILES):
        try:
            probe(f)
        except Exception as exc:  # noqa: BLE001
            print("   >>> FAILED:", type(exc).__name__, exc)