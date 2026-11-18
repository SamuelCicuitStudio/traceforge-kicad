"""Project-local library discovery and recoverable, hash-checked import transactions."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import component_schema as schema


@dataclass
class Node:
    value: object
    start: int
    end: int

    @property
    def head(self):
        return self.value[0].value if isinstance(self.value, list) and self.value else ""

    def children(self, name):
        return [n for n in self.value[1:] if n.head == name]

    def arg(self, index=1):
        return self.value[index].value


def parse(text, cancel=None):
    def check():
        if cancel is not None and cancel.is_set():
            from .cancellation import OperationCancelled

            raise OperationCancelled("Assignment cancelled before writing component information")

    check()
    tokens = []
    for token in re.finditer(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text):
        if len(tokens) % 2048 == 0:
            check()
        tokens.append(token)
    index = 0

    def node(depth=0):
        nonlocal index
        if index % 2048 == 0:
            check()
        if depth > 120 or index >= len(tokens):
            raise ValueError("Invalid or excessively nested KiCad document")
        token = tokens[index]
        index += 1
        word = token.group()
        if word == "(":
            values = []
            while index < len(tokens) and tokens[index].group() != ")":
                values.append(node(depth + 1))
            if index >= len(tokens):
                raise ValueError("Truncated KiCad document")
            end = tokens[index].end()
            index += 1
            return Node(values, token.start(), end)
        if word == ")":
            raise ValueError("Unexpected closing parenthesis")
        return Node(
            json.loads(word, strict=False) if word.startswith('"') else word,
            token.start(),
            token.end(),
        )

    result = node()
    if index != len(tokens):
        raise ValueError("Trailing KiCad document content")
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def within(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Library destination is outside this project") from exc
    return path


def read_bytes(path):
    return path.read_bytes() if path.exists() else None


def json_bytes(data):
    return (json.dumps(data, indent=2, ensure_ascii=True) + "\n").encode()


def entry_bytes(entry):
    if entry.get("encoding") == "base64":
        return base64.b64decode(entry["data"], validate=True)
    return entry["data"].encode("utf-8")


def table_libraries(root, filename):
    path = root / filename
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig")
    result = []
    for entry in parse(text).children("lib"):
        fields = {
            x.head: x.arg()
            for x in entry.value[1:]
            if isinstance(x.value, list) and len(x.value) > 1
        }
        uri = fields.get("uri", "").replace("${KIPRJMOD}", str(root))
        if "${" in uri:
            continue
        try:
            path = within(root, Path(uri) if Path(uri).is_absolute() else root / uri)
        except ValueError:
            continue
        result.append(dict(nickname=fields["name"], path=str(path), type=fields.get("type")))
    return result


def discover(board_file):
    if not board_file or Path(board_file).suffix.lower() not in (
        ".kicad_pcb",
        ".kicad_sch",
        ".kicad_pro",
    ):
        raise ValueError(
            "Choose a saved KiCad schematic, PCB or project before choosing project libraries"
        )
    board = Path(board_file).resolve()
    root = board.parent
    if not root.is_dir():
        raise ValueError("Choose a saved design in an existing project")
    symbols = table_libraries(root, "sym-lib-table")
    footprints = table_libraries(root, "fp-lib-table")
    settings = root / "libraries/traceforge-library.json"
    saved = json.loads(settings.read_text()) if settings.exists() else {}
    common = set(x["nickname"] for x in symbols) & set(x["nickname"] for x in footprints)
    nickname = next(iter(common)) if len(common) == 1 else None
    if nickname is None and board.is_file():
        # Prefer the registered library actually used by most placed instances.
        # Auxiliary capture libraries must not force a question on every import.
        used = Counter(
            re.findall(
                r'\((?:footprint|lib_id)\s+"([^:"]+):', board.read_text(encoding="utf-8-sig")
            )
        )
        ranked = sorted(((used[n], n) for n in common if used[n]), reverse=True)
        if ranked and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
            nickname = ranked[0][1]
    name = re.sub(r"[^A-Za-z0-9_]+", "_", board.stem).strip("_")
    symbol = next((x for x in symbols if x["nickname"] == saved.get("symbol_nickname")), None)
    footprint = next(
        (x for x in footprints if x["nickname"] == saved.get("footprint_nickname")), None
    )
    symbol = symbol or next((x for x in symbols if x["nickname"] == nickname), None)
    footprint = footprint or next((x for x in footprints if x["nickname"] == nickname), None)
    if not symbols:
        symbol = dict(nickname=name, path=str(root / "libraries" / (name + "_Symbols.kicad_sym")))
        symbols = [symbol]
    if not footprints:
        footprint = dict(nickname=name, path=str(root / "libraries" / (name + ".pretty")))
        footprints = [footprint]
    if len(symbols) == 1:
        symbol = symbols[0]
    if len(footprints) == 1:
        footprint = footprints[0]
    return dict(
        board=str(board),
        root=str(root),
        symbols=symbols,
        footprints=footprints,
        symbol=symbol,
        footprint=footprint,
        ambiguous=symbol is None or footprint is None,
    )


def symbol_names(path):
    path = Path(path)
    if not path.exists():
        return []
    return [n.arg() for n in parse(path.read_text(encoding="utf-8-sig")).children("symbol")]


def footprint_names(path):
    return sorted(p.stem for p in Path(path).glob("*.kicad_mod"))


def catalog(project):
    path = Path(project) / "libraries/traceforge-parts.json"
    return json.loads(path.read_text()) if path.exists() else {"version": 1, "parts": {}}


def part_key(manufacturer, mpn):
    return manufacturer.strip().casefold() + ":" + mpn.strip().casefold()


def existing_part(project, manufacturer, mpn):
    record = catalog(project)["parts"].get(part_key(manufacturer, mpn))
    if record:
        return record
    matches = []
    for library in table_libraries(Path(project), "sym-lib-table"):
        path = Path(library["path"])
        if not path.is_file():
            continue
        for symbol in parse(path.read_text(encoding="utf-8-sig")).children("symbol"):
            props = {p.arg().casefold(): p.arg(2) for p in symbol.children("property")}
            identity = props.get("mpn") or props.get("manufacturer part number", "")
            maker = props.get("manufacturer") or props.get("mfr", "")
            if part_key(maker, identity) != part_key(manufacturer, mpn):
                continue
            matches.append(
                dict(
                    manufacturer=maker,
                    mpn=identity,
                    symbol=library["nickname"] + ":" + symbol.arg(),
                    footprint=props.get("footprint", ""),
                    origin="existing registered project symbol",
                )
            )
    if len(matches) > 1:
        return dict(status="ambiguous", matches=matches)
    return matches[0] if matches else None


def suggest_generic(names, category):
    """Suggest only a uniquely named small symbol; package geometry stays explicit."""
    aliases = {
        "resistor": {"r_small", "r_0402", "r_0603", "r_0805"},
        "capacitor": {"c_small", "c_0402", "c_0603", "c_0805"},
        "inductor": {"l_small"},
        "bead": {"ferrite_bead_small", "ferritebead_small"},
        "led": {"led_small"},
    }
    options = [n for n in names if n.split(":")[-1].casefold() in aliases.get(category, set())]
    return options[0] if len(options) == 1 else ""


def table_update(root, filename, nickname, path, kind):
    target = root / filename
    data = read_bytes(target)
    text = data.decode("utf-8-sig") if data else f"({kind} (version 7))"
    node = parse(text)
    for lib in node.children("lib"):
        fields = {x.head: x.arg() for x in lib.value[1:] if isinstance(x.value, list)}
        if fields.get("name") == nickname:
            uri = fields["uri"].replace("${KIPRJMOD}", str(root))
            old = within(root, Path(uri) if Path(uri).is_absolute() else root / uri)
            if old != path:
                raise ValueError("Library nickname already maps to another destination")
            return text.encode()
    rel = path.relative_to(root).as_posix()
    entry = (
        f' (lib (name {json.dumps(nickname)}) (type "KiCad") '
        f'(uri "${{KIPRJMOD}}/{rel}") (options "") '
        '(descr "TraceForge project-local assets"))'
    )
    return (text[: node.end - 1] + entry + text[node.end - 1 :]).encode()


def _replace_string(text, node, value):
    return text[: node.start] + json.dumps(value) + text[node.end :]


def footprint_display(text):
    """Normalize identifying fields on a new asset, preserving assembly/polarity marks."""
    changes = []
    for node in parse(text).value[1:]:
        if node.head not in ("fp_text", "property"):
            continue
        label = str(node.arg()).casefold()
        value = str(node.arg(2))
        reference = label == "reference"
        hidden = label == "value" or "${REFERENCE}" in value or "%R" == value
        if not reference and not hidden:
            continue
        fragment = text[node.start : node.end]
        for child in sorted(
            node.children("layer") + node.children("hide"), key=lambda n: n.start, reverse=True
        ):
            start, end = child.start - node.start, child.end - node.start
            if child.head == "layer" and reference:
                fragment = fragment[:start] + '(layer "F.SilkS")' + fragment[end:]
            elif child.head == "hide":
                fragment = fragment[:start] + fragment[end:]
        # Legacy fp_text hide is an atom; modern property uses (hide yes).
        fragment = re.sub(r"(?<=\s)hide(?=\s|\))", "", fragment)
        if hidden:
            insertion = " hide" if node.head == "fp_text" else " (hide yes)"
            fragment = fragment[:-1] + insertion + ")"
        changes.append((node.start, node.end, fragment))
    for start, end, fragment in reversed(changes):
        text = text[:start] + fragment + text[end:]
    return text


def _part_symbol(text, part, category="custom"):
    """Apply the shared field contract to a NEW exact-part symbol only."""
    props = schema.properties(part)
    visible = schema.visible_fields(category)
    for key, value in props.items():
        if key == "Reference":
            continue
        symbol = parse(text).children("symbol")[0]
        aliases = {schema.fold(x) for x in [key] + schema.SCHEMA["fields"][key]["aliases"]}
        matches = [p for p in symbol.children("property") if schema.fold(p.arg()) in aliases]
        if key == "Value" and matches:
            text = _replace_string(text, matches[0].value[2], value)
            continue
        show = key in visible
        y = 2.54 - visible.index(key) * 1.778 if show else 0
        hide = "" if show else " (hide yes)"
        justify = " (justify left)" if show else ""
        prop = (
            f"\n(property {json.dumps(key)} {json.dumps(value)} "
            f"(at {2.54 if show else 0} {y:g} 0) "
            f"(effects (font (size 1.27 1.27)){justify}{hide}))\n"
        )
        if matches:
            for old in reversed(matches):
                text = text[: old.start] + (prop if old is matches[0] else "") + text[old.end :]
        else:
            text = text[: symbol.end - 1] + prop + text[symbol.end - 1 :]
    return text


def passive_template(root, symbol_id, symbol_library):
    nickname, name = symbol_id.split(":", 1)
    registered = table_libraries(root, "sym-lib-table")
    row = next((r for r in registered if r["nickname"] == nickname), None)
    if row:
        path = Path(row["path"])
    elif nickname == "Device":
        folders = [
            Path(os.environ.get("KICAD10_SYMBOL_DIR", "")),
            Path(sys.executable).parent.parent / "share/kicad/symbols",
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "KiCad/10.0/share/kicad/symbols",
        ]
        path = next(
            (p / "Device.kicad_sym" for p in folders if (p / "Device.kicad_sym").is_file()), None
        )
        if path is None:
            raise ValueError("KiCad Device library not found; choose a project small symbol")
    elif nickname == symbol_library["nickname"]:
        path = Path(symbol_library["path"])
    else:
        raise ValueError("Small passive template library is not registered")
    raw = path.read_text(encoding="utf-8-sig")
    symbol = next((n for n in parse(raw).children("symbol") if n.arg() == name), None)
    if symbol is None or symbol.children("extends"):
        raise ValueError("Choose a self-contained small passive symbol")
    return raw[symbol.start : symbol.end]


def exact_passive(root, template_id, symbol_library, part):
    definition = passive_template(root, template_id, symbol_library)
    old = parse(definition).arg()
    name = re.sub(r"[^A-Za-z0-9_.+#-]", "_", part["mpn"])[:40]
    if not name:
        raise ValueError("Part needs a short symbol name")
    nodes = parse(definition)
    replacements = [(nodes.value[1], name)]
    replacements += [
        (n.value[1], name + n.arg()[len(old) :])
        for n in nodes.children("symbol")
        if n.arg().startswith(old + "_")
    ]
    for node, value in sorted(replacements, key=lambda pair: pair[0].start, reverse=True):
        definition = _replace_string(definition, node, value)
    return '(kicad_symbol_lib (version 20250114) (generator "TraceForge")\n' + definition + ")"


def pin_numbers(node):
    result = set()
    if not isinstance(node.value, list):
        return result
    if node.head == "pin":
        for number in node.children("number"):
            result.add(str(number.arg()))
    for child in node.value:
        result.update(pin_numbers(child))
    return result


def plan_import(
    project,
    part,
    symbol_library,
    footprint_library,
    *,
    candidate_symbol=None,
    candidate_footprint=None,
    reuse_symbol="",
    reuse_footprint="",
    category="custom",
    model=None,
    placement_symbol=False,
):
    """Build a concrete write set. Never change active libraries in this function."""
    root = Path(project).resolve()
    if not part.get("mpn") or not part.get("manufacturer"):
        raise ValueError("Exact MPN and manufacturer are required")
    for key in ("mpn", "manufacturer", "lcsc"):
        if len(str(part.get(key, ""))) > 200:
            raise ValueError("Part identity is too long")
    sym = dict(symbol_library)
    fp = dict(footprint_library)
    sym_path = within(root, sym["path"])
    fp_path = within(root, fp["path"])
    writes = {}
    summary = []

    def add(path, data):
        path = within(root, path)
        try:
            content, encoding = data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            content, encoding = base64.b64encode(data).decode("ascii"), "base64"
        writes[str(path.relative_to(root))] = {
            "before": digest(read_bytes(path)),
            "data": content,
            "encoding": encoding,
        }

    if (
        category != "custom"
        and not (
            placement_symbol
            and schema.passive_symbol(category)
            and (reuse_footprint or candidate_footprint)
        )
        and (not reuse_symbol or not reuse_footprint)
    ):
        raise ValueError("Passives require explicit compatible generic symbol and footprint")
    symbol_id = reuse_symbol
    footprint_id = reuse_footprint
    if reuse_symbol and not (placement_symbol and schema.passive_symbol(category)):
        nick, name = reuse_symbol.split(":", 1)
        if nick != sym["nickname"] or name not in symbol_names(sym_path):
            raise ValueError("Selected generic symbol does not exist in destination library")
    if reuse_footprint:
        nick, name = reuse_footprint.split(":", 1)
        if nick != fp["nickname"] or name not in footprint_names(fp_path):
            raise ValueError("Selected footprint does not exist in destination library")
    if candidate_footprint and not reuse_footprint:
        text = Path(candidate_footprint).read_text(encoding="utf-8-sig")
        node = parse(text)
        if node.head not in ("footprint", "module"):
            raise ValueError("Candidate is not a KiCad footprint")
        name = node.arg()
        if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,80}", name):
            raise ValueError("Unsafe footprint asset name")
        pads = node.children("pad")
        if not pads:
            raise ValueError("Footprint has no pads")
        if node.children("model"):
            raise ValueError("Candidate has unreviewed model links")
        text = footprint_display(text)
        target = within(root, fp_path / (name + ".kicad_mod"))
        old = read_bytes(target)
        if old is not None and old.decode("utf-8-sig").strip() != text.strip():
            raise ValueError(
                "Existing customized footprint preserved; conflicting candidate staged"
            )
        if old is None:
            add(target, text.encode())
        footprint_id = fp["nickname"] + ":" + name
        summary.append(f"Footprint {footprint_id}: {len(pads)} pads")
    passive_text = None
    if placement_symbol and schema.passive_symbol(category):
        template = reuse_symbol or schema.passive_symbol(category)
        passive_text = exact_passive(root, template, sym, part)
        part = dict(part, generic_template=template)
        reuse_symbol = symbol_id = ""
    if (candidate_symbol or passive_text) and not reuse_symbol:
        text = passive_text or Path(candidate_symbol).read_text(encoding="utf-8-sig")
        parsed = parse(text)
        candidates = parsed.children("symbol")
        if parsed.head != "kicad_symbol_lib" or len(candidates) != 1:
            raise ValueError("Expected exactly one symbol in candidate library")
        source = candidates[0]
        name = source.arg()
        if not re.fullmatch(r"[A-Za-z0-9_.+#-]{1,100}", name):
            raise ValueError("Unsafe symbol name")
        for prop in source.children("property"):
            if prop.arg() == "Footprint":
                # A symbol-only acquisition must not retain the converter's
                # unresolved footprint nickname. Mapping can be added later.
                text = _replace_string(text, prop.value[2], footprint_id)
                break
        else:
            if footprint_id:
                raise ValueError("Candidate symbol has no footprint property to retarget")
        text = _part_symbol(text, dict(part, Footprint=footprint_id), category)
        source = parse(text).children("symbol")[0]
        definition = text[source.start : source.end]
        old = read_bytes(sym_path)
        library = (
            old.decode("utf-8-sig")
            if old
            else ('(kicad_symbol_lib (version 20250114) (generator "TraceForge"))')
        )
        root_node = parse(library)
        existing = [n for n in root_node.children("symbol") if n.arg() == name]
        if existing and library[existing[0].start : existing[0].end].strip() != definition.strip():
            raise ValueError("Existing customized symbol preserved; conflicting candidate staged")
        if not existing:
            add(
                sym_path,
                (
                    library[: root_node.end - 1]
                    + "\n"
                    + definition
                    + "\n"
                    + library[root_node.end - 1 :]
                ).encode(),
            )
        symbol_id = sym["nickname"] + ":" + name
        summary.append("Symbol " + symbol_id)
    if not symbol_id and not footprint_id and not model:
        raise ValueError("Select at least one asset or compatible existing mapping")
    if symbol_id and footprint_id and (candidate_symbol or candidate_footprint or passive_text):
        sym_key = str(sym_path.relative_to(root))
        sym_text = writes[sym_key]["data"] if sym_key in writes else sym_path.read_text()
        definition = next(
            n for n in parse(sym_text).children("symbol") if n.arg() == symbol_id.split(":", 1)[1]
        )
        asset = fp_path / (footprint_id.split(":", 1)[1] + ".kicad_mod")
        fp_key = str(asset.relative_to(root))
        fp_text = writes[fp_key]["data"] if fp_key in writes else asset.read_text()
        pins = pin_numbers(definition)
        pads = {str(n.arg()) for n in parse(fp_text).children("pad") if n.arg()}
        if pins and pins != pads:
            raise ValueError(
                "Symbol pin / footprint pad mismatch: "
                f"symbol-only {sorted(pins - pads)}, pad-only {sorted(pads - pins)}"
            )
        summary.append(f"Pin/pad comparison: {len(pins)} symbol numbers, {len(pads)} pad numbers")
    model_record = None
    if model:
        candidate = Path(model["path"] if isinstance(model, dict) else model)
        source_path = candidate.with_suffix(".source.json")
        if not source_path.is_file():
            raise ValueError("STEP candidate needs its source and identity record")
        evidence = json.loads(source_path.read_text())
        if evidence.get("expected_mpn", "").casefold() != part["mpn"].casefold():
            raise ValueError("STEP candidate belongs to a different MPN")
        raw_model = candidate.read_bytes()
        if (
            candidate.suffix.lower() not in (".step", ".stp")
            or not raw_model.lstrip().startswith(b"ISO-10303-21;")
            or b"END-ISO-10303-21;" not in raw_model
        ):
            raise ValueError("Invalid STEP candidate")
        if evidence.get("sha256") != digest(raw_model):
            raise ValueError("STEP candidate changed after download")
        target = within(root, root / "3dmodels" / candidate.name)
        if target.exists() and target.read_bytes() != raw_model:
            raise ValueError("Existing different STEP preserved; choose a distinct short name")
        add(target, raw_model)
        add(target.with_suffix(".source.json"), json_bytes(evidence))
        checked = isinstance(model, dict) and model.get("checked", False)
        model_record = dict(path=target.relative_to(root).as_posix(), checked=bool(checked))
        if checked:
            import math

            transform = model.get("rotation", [0, 0, 0])
            offset = model.get("offset", [0, 0, 0])
            if (
                len(transform) != 3
                or len(offset) != 3
                or not all(math.isfinite(float(x)) for x in transform + offset)
            ):
                raise ValueError("Model transform must contain finite XYZ values")
            if not footprint_id:
                raise ValueError("Choose a footprint before linking the checked model")
            asset = within(root, fp_path / (footprint_id.split(":", 1)[1] + ".kicad_mod"))
            key_path = str(asset.relative_to(root))
            fp_text = writes[key_path]["data"] if key_path in writes else asset.read_text()
            fp_root = parse(fp_text)
            if fp_root.children("model"):
                raise ValueError("Existing model link preserved; compare it before replacement")
            rel = "${KIPRJMOD}/" + target.relative_to(root).as_posix()
            link = (
                f"\n(model {json.dumps(rel)} (offset (xyz {' '.join(map(str, offset))})) "
                f"(scale (xyz 1 1 1)) (rotate (xyz {' '.join(map(str, transform))})))\n"
            )
            add(asset, (fp_text[: fp_root.end - 1] + link + fp_text[fp_root.end - 1 :]).encode())
            model_record.update(rotation=transform, offset=offset)
            summary.append("Checked STEP linked with project-relative path")
        else:
            summary.append("STEP installed as unlinked candidate; geometry/orientation not checked")
    if symbol_id:
        add(
            root / "sym-lib-table",
            table_update(root, "sym-lib-table", sym["nickname"], sym_path, "sym_lib_table"),
        )
    if footprint_id:
        add(
            root / "fp-lib-table",
            table_update(root, "fp-lib-table", fp["nickname"], fp_path, "fp_lib_table"),
        )
    parts = catalog(root)
    key = part_key(part["manufacturer"], part["mpn"])
    record = dict(
        part, symbol=symbol_id, footprint=footprint_id, category=category, model=model_record
    )
    record["reuse"] = dict(symbol=bool(reuse_symbol), footprint=bool(reuse_footprint))
    hashes = {}
    for label, asset in (
        ("symbol_library", sym_path),
        ("footprint", fp_path / (footprint_id.split(":", 1)[-1] + ".kicad_mod")),
    ):
        rel = str(asset.relative_to(root))
        data = entry_bytes(writes[rel]) if rel in writes else read_bytes(asset)
        if data is not None:
            hashes[label] = digest(data)
    record["asset_hashes_at_import"] = hashes
    prior = parts["parts"].get(key)
    if prior:
        for field, value in prior.items():
            if field not in record or record[field] in ("", None):
                record[field] = value
        for asset in ("symbol", "footprint"):
            old, new = prior.get(asset), record.get(asset)
            if old and new and old != new:
                raise ValueError("Existing part mapping differs; current mapping preserved")
            record[asset] = new or old or ""
        if model_record is None:
            record["model"] = prior.get("model")
    parts["parts"][key] = record
    add(root / "libraries/traceforge-parts.json", json_bytes(parts))
    add(
        root / "libraries/traceforge-library.json",
        json_bytes(
            {"version": 1, "symbol_nickname": sym["nickname"], "footprint_nickname": fp["nickname"]}
        ),
    )
    return dict(
        version=1,
        operation=uuid.uuid4().hex,
        project=str(root),
        writes=writes,
        summary=summary,
        part=record,
    )


def install(plan):
    """CAS check every file; journal original bytes; restore on any failure."""
    root = Path(plan["project"]).resolve()
    if not re.fullmatch(r"[0-9a-f]{32}", plan["operation"]):
        raise ValueError("Invalid import operation identity")
    changes = [(within(root, root / rel), entry) for rel, entry in plan["writes"].items()]
    for path, entry in changes:
        if digest(read_bytes(path)) != entry["before"]:
            raise ValueError("Project changed since preview; rebuild the import plan")
    operation = root / "review/component-imports" / plan["operation"]
    operation.mkdir(parents=True, exist_ok=False)
    originals = {str(path.relative_to(root)): read_bytes(path) for path, _ in changes}
    for index, (_rel, data) in enumerate(originals.items()):
        if data is not None:
            (operation / f"{index}.backup").write_bytes(data)
    journal = dict(state="prepared", files=list(originals), plan=plan)
    (operation / "plan.json").write_bytes(json_bytes(plan))
    (operation / "validation.json").write_bytes(
        json_bytes(
            dict(
                state="destination_hashes_checked",
                files={str(path.relative_to(root)): entry["before"] for path, entry in changes},
                package_pin_map_reviewed=plan["part"].get("package_pin_map_reviewed", False),
                summary=plan["summary"],
            )
        )
    )
    (operation / "source.json").write_bytes(json_bytes(plan["part"].get("provenance", {})))
    (operation / "journal.json").write_bytes(json_bytes(journal))
    changed = []
    try:
        for path, entry in changes:
            if digest(read_bytes(path)) != entry["before"]:
                raise ValueError("Concurrent library change; import rolled back")
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + ".traceforge-" + plan["operation"])
            temp.write_bytes(entry_bytes(entry))
            os.replace(temp, path)
            changed.append(path)
        journal["state"] = "installed"
        (operation / "journal.json").write_bytes(json_bytes(journal))
    except Exception:
        recover(operation / "journal.json")
        raise
    finally:
        for path, _entry in changes:
            temp = path.with_name(path.name + ".traceforge-" + plan["operation"])
            if temp.exists():
                temp.unlink()
    return dict(
        status="installed",
        files=[str(p.relative_to(root)) for p in changed],
        symbol=plan["part"]["symbol"],
        footprint=plan["part"]["footprint"],
        journal=str(operation / "journal.json"),
    )


def recover(journal_path):
    """Restore an interrupted import, preserving files edited after the import wrote them."""
    journal_path = Path(journal_path).resolve()
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    plan = journal["plan"]
    root = Path(plan["project"]).resolve()
    expected = within(root, root / "review/component-imports" / plan["operation"] / "journal.json")
    if journal_path != expected or not re.fullmatch(r"[0-9a-f]{32}", plan["operation"]):
        raise ValueError("Journal does not belong to this project operation")
    if journal["state"] == "installed":
        raise ValueError("Installed imports are not interrupted transactions")
    conflicts = []
    for index, rel in reversed(list(enumerate(journal["files"]))):
        entry = plan["writes"][rel]
        target = within(root, root / rel)
        current = digest(read_bytes(target))
        if current == entry["before"]:
            continue
        if current != digest(entry_bytes(entry)):
            conflicts.append(rel)
            continue
        if entry["before"] is None:
            target.unlink()
        else:
            original = (journal_path.parent / f"{index}.backup").read_bytes()
            if digest(original) != entry["before"]:
                raise ValueError("Import backup failed integrity check")
            temp = target.with_name(target.name + ".traceforge-recovery")
            temp.write_bytes(original)
            os.replace(temp, target)
    journal["state"] = "recovery_conflict" if conflicts else "rolled_back"
    journal["conflicts"] = conflicts
    journal_path.write_bytes(json_bytes(journal))
    return journal["state"]
