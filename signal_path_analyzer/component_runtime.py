"""External research/CAD runtimes; subprocess arguments are never shell commands."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

SETTINGS = Path(os.environ.get("APPDATA", Path.home())) / "TraceForge/components.json"


def settings():
    data = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    root = Path(__file__).resolve().parents[1]
    browser = root.parent.parent / "TraceForgerouter/component-browser"
    helpers = root.parent / "pcb/skills/kicad-3d-models/scripts"
    data.setdefault("browser", str(browser) if (browser / "desktop/tool.cjs").exists() else "")
    data.setdefault(
        "helpers", str(helpers) if (helpers / "download_easyeda_cad.py").exists() else ""
    )
    data.setdefault("python", shutil.which("python") or sys.executable)
    data.setdefault("node", shutil.which("node") or "")
    return data


def save_settings(data):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class Cancelled(RuntimeError):
    pass


def export_cad_previews(worker, stage):
    cli = shutil.which("kicad-cli") or str(Path(sys.executable).with_name("kicad-cli.exe"))
    out = Path(stage["staging"]) / "preview"
    out.mkdir(exist_ok=True)
    if stage.get("symbol"):
        worker.run([cli, "sym", "export", "svg", "-o", str(out), stage["symbol"]])
    if stage.get("footprint"):
        footprint = Path(stage["footprint"])
        with tempfile.TemporaryDirectory(dir=stage["staging"]) as temp:
            library = Path(temp) / "preview.pretty"
            library.mkdir()
            shutil.copy2(footprint, library / footprint.name)
            worker.run([cli, "fp", "export", "svg", "-o", str(out), "-l", "F.Cu,F.SilkS,F.Fab",
                        "--sp", "--footprint", footprint.stem, str(library)])
    return sorted(out.glob("*.svg"))


class Worker:
    def __init__(self, config=None):
        self.config = dict(config or settings())
        self.cancel = threading.Event()

    def run(self, command, payload=None, timeout=150):
        if self.cancel.is_set():
            raise Cancelled("Cancelled before starting the operation")
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        started = time.monotonic()
        input_text = json.dumps(payload) if payload is not None else None
        try:
            while True:
                if self.cancel.is_set():
                    raise Cancelled("Cancelled; staged files remain separate from active libraries")
                if time.monotonic() - started > timeout:
                    raise TimeoutError("Component operation timed out")
                try:
                    out, err = process.communicate(input_text, timeout=0.15)
                    break
                except subprocess.TimeoutExpired:
                    input_text = None
            if process.returncode:
                # CLI error envelopes are useful, but never expose environment/connection secrets.
                raise RuntimeError((out or err)[-2200:])
            try:
                return json.loads(out)
            except ValueError:
                return {"output": out[-4000:]}
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def browser(self, operation, **arguments):
        node = self.config.get("node")
        script = Path(self.config.get("browser", "")) / "desktop/tool.cjs"
        if not node or not script.is_file():
            raise RuntimeError("Configure the Component Research folder and Node executable first")
        result = self.run([node, str(script), operation, "--stdin"], arguments)
        if not isinstance(result, dict) or result.get("schema_version") != "1.0":
            raise RuntimeError("Unsupported Component Research helper protocol; use schema 1.0.")
        if result.get("status") == "error":
            raise RuntimeError(result.get("error", "Component Research operation failed"))
        return result

    def readiness(self):
        helpers = Path(self.config.get("helpers", ""))
        browser_ready = bool(
            self.config.get("node")
            and (Path(self.config.get("browser", "")) / "desktop/tool.cjs").is_file()
        )
        if browser_ready:
            try:
                browser_ready = self.browser("capabilities").get("status") == "ok"
            except (OSError, RuntimeError):
                browser_ready = False
        return dict(
            browser=browser_ready,
            cad=(helpers / "download_easyeda_cad.py").is_file(),
            step=(helpers / "download_easyeda_step.py").is_file(),
            converter=self.run(
                [
                    self.config["python"],
                    "-c",
                    'import importlib.util,json; print(json.dumps({"available":'
                    'bool(importlib.util.find_spec("easyeda2kicad"))}))',
                ]
            ).get("available", False),
        )

    def stage(self, project, lcsc, mpn, mode="both", step=False):
        import re

        if not re.fullmatch(r"C[0-9]{2,}", lcsc, re.I) or not mpn.strip():
            raise ValueError("An exact LCSC code and MPN are required")
        if mode not in ("both", "symbol", "footprint", "none"):
            raise ValueError("Unknown asset request")
        root = Path(project).resolve()
        operation = root / "review/component-imports" / ("stage-" + uuid.uuid4().hex)
        operation.mkdir(parents=True)
        helpers = Path(self.config.get("helpers", ""))
        report = dict(
            project=str(root),
            staging=str(operation),
            lcsc=lcsc.upper(),
            mpn=mpn,
            symbol=None,
            footprint=None,
            model=None,
            issues=[],
        )
        if mode != "none":
            try:
                script = helpers / "download_easyeda_cad.py"
                if not script.is_file():
                    raise RuntimeError("Configure the PCB download-helper folder first")
                self.run(
                    [
                        self.config["python"],
                        str(script),
                        lcsc,
                        "--mpn",
                        mpn,
                        "--project",
                        str(operation),
                        "--mode",
                        mode,
                    ]
                )
                imports = operation / "libraries/imports" / lcsc.upper()
                syms, fps = list(imports.glob("*.kicad_sym")), list(imports.glob("*.kicad_mod"))
                report.update(
                    symbol=str(syms[0]) if syms else None, footprint=str(fps[0]) if fps else None
                )
                source = imports / "source.json"
                if source.exists():
                    report["source"] = json.loads(source.read_text())
            except Cancelled:
                raise
            except (OSError, RuntimeError) as exc:
                report["issues"].append("CAD unavailable: " + str(exc))
        if step:
            try:
                self.run(
                    [
                        self.config["python"],
                        str(helpers / "download_easyeda_step.py"),
                        lcsc,
                        "--mpn",
                        mpn,
                        "--project",
                        str(operation),
                    ]
                )
                models = list((operation / "3dmodels").glob("*.step"))
                if models:
                    report["model"] = str(models[0])
            except (OSError, RuntimeError) as exc:
                report["issues"].append("STEP unavailable: " + str(exc))
        (operation / "stage.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
