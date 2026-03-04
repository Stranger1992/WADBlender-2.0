#!/usr/bin/env python3
"""
Generate resources/trcatalog.xml from Tomb Editor Engine catalog XML files.

Usage: python tools/generate_catalog.py

Reads from:  C:/Github/Tomb-Editor/TombLib/TombLib/Catalogs/Engines/<game>/*.xml
Writes to:   resources/trcatalog.xml
"""

import os
import xml.etree.ElementTree as ET

TE_CATALOGS = r"C:\Github\Tomb-Editor\TombLib\TombLib\Catalogs\Engines"
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "resources", "trcatalog.xml")

# WADBlender game ID  →  TE Engine folder (None = reuse another game's folder)
# TRNG shares TR4's catalog but gets game_version=16
GAMES = [
    ("TR1",  "TR1"),
    ("TR2",  "TR2"),
    ("TR3",  "TR3"),
    ("TR4",  "TR4"),
    ("TRNG", "TR4"),          # TRNG reuses TR4 catalog
    ("TR5",  "TR5"),
    ("TEN",  "TombEngine"),
]


def read_root(folder, filename):
    path = os.path.join(folder, filename)
    if not os.path.exists(path):
        return None
    return ET.parse(path).getroot()


def build_game_section(game_id, engine_folder):
    folder = os.path.join(TE_CATALOGS, engine_folder)
    lines = [f'  <game id="{game_id}">']

    # ---- Moveables ----
    mov_root = read_root(folder, "Moveables.xml")
    if mov_root is not None:
        lines.append("    <moveables>")
        for mov in mov_root.findall("moveable"):
            mid  = mov.get("id")
            name = mov.get("name", "")
            attrs = f'id="{mid}" name="{name}"'
            for attr in ("use_body_from", "show_with", "hidden", "essential"):
                val = mov.get(attr)
                if val is not None:
                    attrs += f' {attr}="{val}"'
            lines.append(f"      <moveable {attrs} />")
        lines.append("    </moveables>")

    # ---- Statics ----
    static_root = read_root(folder, "Statics.xml")
    if static_root is not None:
        lines.append("    <statics>")
        for s in static_root.findall("static"):
            sid  = s.get("id")
            name = s.get("name", "")
            attrs = f'id="{sid}" name="{name}"'
            if s.get("shatter"):
                attrs += f' shatter="{s.get("shatter")}"'
            lines.append(f"      <static {attrs} />")
        lines.append("    </statics>")

    # ---- Animations ----
    anim_root = read_root(folder, "Animations.xml")
    if anim_root is not None:
        lines.append("    <animations>")
        for a in anim_root.findall("anim"):
            item = a.get("item")
            aid  = a.get("id")
            name = a.get("name", "")
            lines.append(f'      <anim item="{item}" id="{aid}" name="{name}" />')
        lines.append("    </animations>")

    # ---- States ----
    states_root = read_root(folder, "States.xml")
    if states_root is not None:
        lines.append("    <states>")
        for s in states_root.findall("state"):
            item = s.get("item")
            sid  = s.get("id")
            name = s.get("name", "")
            lines.append(f'      <state item="{item}" id="{sid}" name="{name}" />')
        lines.append("    </states>")

    lines.append("  </game>")
    return "\n".join(lines)


def main():
    sections = [
        '<?xml version="1.0" encoding="UTF-8" ?>',
        "<!-- Generated from Tomb Editor Engine catalogs -->",
        "<!-- Source: TombLib/TombLib/Catalogs/Engines/ -->",
        "<xml>",
    ]
    for game_id, engine_folder in GAMES:
        print(f"  Building {game_id} from {engine_folder}/...")
        sections.append(build_game_section(game_id, engine_folder))
    sections.append("</xml>")

    content = "\n".join(sections) + "\n"
    with open(OUTPUT, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"\nWrote {OUTPUT}")
    print(f"  Size: {len(content):,} bytes")


if __name__ == "__main__":
    main()
