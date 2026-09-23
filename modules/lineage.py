# modules/lineage.py
# Betta Farm Management System
# Session 16 — Lineage tree traversal + Graphviz rendering.
#
# Builds nested tree dicts by walking fish.sire_id / fish.dam_id
# upward (ancestors) or downward (descendants).
#
# Node shape:
#   {
#       "fish":      {…fish row…} or None,
#       "sire":      {…node…} or None,
#       "dam":       {…node…} or None,
#       "generation": int,      # 0 = focal fish, 1 = parents, 2 = grandparents…
#       "is_unknown": bool,     # True if this node is a placeholder
#   }

from __future__ import annotations

from typing import Optional

from database import get_all_fish, get_all_spawns


# ============================================================
# NODE HELPERS
# ============================================================

def _unknown_node(generation: int) -> dict:
    return {
        "fish": None,
        "sire": None,
        "dam": None,
        "generation": generation,
        "is_unknown": True,
    }


def _fish_node(fish: dict, generation: int) -> dict:
    return {
        "fish": fish,
        "sire": None,
        "dam": None,
        "generation": generation,
        "is_unknown": False,
    }


# ============================================================
# ANCESTORS (walk up via sire_id / dam_id)
# ============================================================

def get_ancestors(fish_id: str, depth: int = 4) -> Optional[dict]:
    """
    Return nested tree of ancestors for a fish, up to `depth` generations.

    - If a fish has a known parent, that parent's node is built recursively.
    - If a parent is unknown, an `is_unknown` node is created.
    - Unknown nodes are NOT recursed further (Q4=A4: show "Unknown" once).
    """
    fish_by_id = {f["id"]: f for f in get_all_fish()}
    return _build_ancestor_node(fish_id, fish_by_id, gen=0, depth=depth)


def _build_ancestor_node(
    fish_id: Optional[str],
    fish_by_id: dict,
    gen: int,
    depth: int,
) -> Optional[dict]:
    # Base cases
    if gen > depth:
        return None
    if not fish_id or fish_id not in fish_by_id:
        # Unknown once, don't recurse
        return _unknown_node(gen)

    fish = fish_by_id[fish_id]
    node = _fish_node(fish, gen)

    if gen == depth:
        return node

    sire_id = fish.get("sire_id")
    dam_id = fish.get("dam_id")

    node["sire"] = _build_ancestor_node(sire_id, fish_by_id, gen + 1, depth) if sire_id else _unknown_node(gen + 1)
    node["dam"]  = _build_ancestor_node(dam_id, fish_by_id, gen + 1, depth) if dam_id  else _unknown_node(gen + 1)

    return node


# ============================================================
# DESCENDANTS (walk down via sire_id / dam_id and spawn links)
# ============================================================

def get_descendants(fish_id: str, depth: int = 4) -> Optional[dict]:
    """
    Return nested tree of descendants for a fish, up to `depth` generations.

    Children are discovered by finding fish whose sire_id or dam_id
    equals this fish. Each child becomes a node; each node's children are
    the next generation.

    Unlike ancestors, descendants are NOT binary (a fish can have many
    children). We store them in a list under the "children" key.
    """
    fish_by_id = {f["id"]: f for f in get_all_fish()}

    # Build reverse index: parent_id -> list of child fish
    children_by_parent: dict[str, list[dict]] = {}
    for f in fish_by_id.values():
        if f.get("sire_id"):
            children_by_parent.setdefault(f["sire_id"], []).append(f)
        if f.get("dam_id"):
            children_by_parent.setdefault(f["dam_id"], []).append(f)

    return _build_descendant_node(
        fish_id, fish_by_id, children_by_parent, gen=0, depth=depth
    )


def _build_descendant_node(
    fish_id: Optional[str],
    fish_by_id: dict,
    children_by_parent: dict,
    gen: int,
    depth: int,
) -> Optional[dict]:
    if gen > depth:
        return None
    if not fish_id or fish_id not in fish_by_id:
        return None

    fish = fish_by_id[fish_id]
    node = _fish_node(fish, gen)
    node["children"] = []

    if gen == depth:
        return node

    for child in children_by_parent.get(fish_id, []):
        child_node = _build_descendant_node(
            child["id"], fish_by_id, children_by_parent, gen + 1, depth
        )
        if child_node:
            node["children"].append(child_node)

    return node


# ============================================================
# SUMMARY HELPERS
# ============================================================

def count_ancestors(node: Optional[dict]) -> int:
    """Total known ancestor nodes (excludes unknowns)."""
    if not node:
        return 0
    if node.get("is_unknown"):
        return 0
    total = 1
    total += count_ancestors(node.get("sire"))
    total += count_ancestors(node.get("dam"))
    return total


def count_descendants(node: Optional[dict]) -> int:
    """Total known descendant nodes."""
    if not node:
        return 0
    total = 1
    for child in node.get("children") or []:
        total += count_descendants(child)
    return total


def has_any_lineage(fish_id: str) -> bool:
    """True if the fish has at least one known parent or child."""
    fish_by_id = {f["id"]: f for f in get_all_fish()}
    fish = fish_by_id.get(fish_id)
    if not fish:
        return False
    if fish.get("sire_id") or fish.get("dam_id"):
        return True
    for f in fish_by_id.values():
        if f.get("sire_id") == fish_id or f.get("dam_id") == fish_id:
            return True
    return False


# ============================================================
# GRAPHVIZ DOT GENERATION
# ============================================================

def _node_label(fish: Optional[dict], is_unknown: bool, fallback: str = "Unknown") -> str:
    if is_unknown or not fish:
        return fallback
    sid = fish.get("system_id") or "?"
    variety = fish.get("variety") or "—"
    gen = fish.get("generation") or "P1"
    gender = fish.get("gender") or "?"
    symbol = "♂" if gender.lower() == "male" else ("♀" if gender.lower() == "female" else "•")
    return f"{sid}\\n{variety}\\n{gen} {symbol}"


def _node_attrs(fish: Optional[dict], is_unknown: bool, is_focal: bool = False) -> str:
    """Return Graphviz attribute string for a node."""
    if is_unknown or not fish:
        return 'shape=box, style="rounded,dashed", color="#888888", fontcolor="#666666"'

    if is_focal:
        fill = "#c8e6c9"  # green
    else:
        gender = (fish.get("gender") or "").lower()
        if gender == "male":
            fill = "#bbdefb"  # blue
        elif gender == "female":
            fill = "#f8bbd0"  # pink
        else:
            fill = "#e0e0e0"  # grey

    return f'shape=box, style="rounded,filled", fillcolor="{fill}", color="#333333"'


def tree_to_dot_ancestors(root: Optional[dict]) -> str:
    """
    Convert an ancestor tree to a Graphviz DOT string.
    Layout: focal fish at bottom, ancestors above.
    """
    if not root:
        return "digraph G {}"

    lines = [
        "digraph Ancestors {",
        "  rankdir=TB;",
        '  node [fontname="Helvetica", fontsize=11, margin="0.15,0.10"];',
        '  edge [color="#666666"];',
    ]

    counter = {"n": 0}

    def emit(node: dict, is_focal: bool = False) -> str:
        if node is None:
            return ""
        counter["n"] += 1
        nid = f"n{counter['n']}"
        fish = node.get("fish")
        is_unk = node.get("is_unknown", False)
        label = _node_label(fish, is_unk, fallback="♂ Unknown" if not is_unk else "Unknown")
        attrs = _node_attrs(fish, is_unk, is_focal)
        lines.append(f'  {nid} [label="{label}", {attrs}];')

        # Sire child
        sire = node.get("sire")
        if sire:
            sid = emit(sire)
            if sid:
                lines.append(f"  {sid} -> {nid};")

        # Dam child
        dam = node.get("dam")
        if dam:
            did = emit(dam)
            if did:
                lines.append(f"  {did} -> {nid};")

        return nid

    emit(root, is_focal=True)
    lines.append("}")
    return "\n".join(lines)


def tree_to_dot_descendants(root: Optional[dict]) -> str:
    """
    Convert a descendant tree to a Graphviz DOT string.
    Layout: focal fish at top, descendants below.
    """
    if not root:
        return "digraph G {}"

    lines = [
        "digraph Descendants {",
        "  rankdir=TB;",
        '  node [fontname="Helvetica", fontsize=11, margin="0.15,0.10"];',
        '  edge [color="#666666"];',
    ]

    counter = {"n": 0}

    def emit(node: dict, is_focal: bool = False) -> str:
        if node is None:
            return ""
        counter["n"] += 1
        nid = f"n{counter['n']}"
        fish = node.get("fish")
        is_unk = node.get("is_unknown", False)
        label = _node_label(fish, is_unk)
        attrs = _node_attrs(fish, is_unk, is_focal)
        lines.append(f'  {nid} [label="{label}", {attrs}];')

        for child in node.get("children") or []:
            cid = emit(child)
            if cid:
                lines.append(f"  {nid} -> {cid};")

        return nid

    emit(root, is_focal=True)
    lines.append("}")
    return "\n".join(lines)


# ============================================================
# TEXT TREE (fallback / mobile-friendly)
# ============================================================

def tree_to_text_ancestors(node: Optional[dict], prefix: str = "", is_root: bool = True) -> list[str]:
    """Render ancestors as indented lines."""
    if not node:
        return []
    out = []
    fish = node.get("fish")
    is_unk = node.get("is_unknown", False)

    label = _node_label(fish, is_unk, fallback="Unknown")
    label = label.replace("\\n", " | ")
    out.append(f"{prefix}{label}")

    if is_unk:
        return out

    sire = node.get("sire")
    dam = node.get("dam")
    if sire:
        out.append(f"{prefix}├─ Sire:")
        out.extend(tree_to_text_ancestors(sire, prefix + "│  ", is_root=False))
    if dam:
        out.append(f"{prefix}├─ Dam:")
        out.extend(tree_to_text_ancestors(dam, prefix + "│  ", is_root=False))
    return out


def tree_to_text_descendants(node: Optional[dict], prefix: str = "") -> list[str]:
    """Render descendants as indented lines."""
    if not node:
        return []
    out = []
    fish = node.get("fish")
    label = _node_label(fish, False).replace("\\n", " | ")
    out.append(f"{prefix}{label}")
    for child in node.get("children") or []:
        out.extend(tree_to_text_descendants(child, prefix + "  "))
    return out
