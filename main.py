#!/usr/bin/env python3
"""Official block-file-icons plugin for Block (blockmd)."""

import json
import os
import re
import sys

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.flush()
    sys.stdout.reconfigure(encoding="utf-8")


STORAGE_KEY = "prefs"
SETTINGS_PAGE_SURFACE = "settings_page"
SUPPORTED_SURFACES = {SETTINGS_PAGE_SURFACE}
CHINESE_TEXT = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")

TINT_LABELS = {
    "none": ("原色", "Default"),
    "blue": ("海蓝", "Blue"),
    "teal": ("青绿", "Teal"),
    "green": ("森绿", "Green"),
    "amber": ("琥珀", "Amber"),
    "red": ("朱红", "Red"),
    "purple": ("紫罗兰", "Purple"),
}


class HostRPCError(RuntimeError):
    """JSON-RPC error returned by the Block host."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class HostBridge:
    """Line-delimited JSON-RPC 2.0 bridge between plugin and Block host."""

    def __init__(self):
        self._seq = 1000

    def send(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def call_host(self, method, params=None):
        self._seq += 1
        req_id = f"p-{self._seq}"
        self.send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
        while True:
            line = sys.stdin.readline()
            if not line:
                raise RuntimeError("stdin closed while awaiting host response")
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if str(msg.get("id")) == req_id:
                if msg.get("error"):
                    err = msg["error"]
                    raise HostRPCError(int(err.get("code", -32000)), str(err.get("message", "host error")))
                return msg.get("result", {})

    def serve(self, handler, localize_error):
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            method = req.get("method")
            req_id = req.get("id")
            try:
                result = handler(self, method, req.get("params") or {})
                if req_id is not None:
                    self.send({"jsonrpc": "2.0", "id": req_id, "result": result})
                if method == "plugin.shutdown":
                    break
            except Exception as exc:
                if req_id is not None:
                    self.send({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32000, "message": localize_error(str(exc))},
                    })


def _load_icon_catalog():
    pack_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons.json")
    try:
        with open(pack_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        icons = data.get("icons") or []
        catalog = {}
        for item in icons:
            if not isinstance(item, dict):
                continue
            iid = str(item.get("id") or "").strip()
            name = item.get("name") or {}
            if iid:
                catalog[iid] = {
                    "zh": str(name.get("zh") or iid),
                    "en": str(name.get("en") or iid),
                }
        return catalog
    except Exception:
        return {}


class FileIconsPlugin:
    """Manages custom sidebar file/folder icons and preferences for Block."""

    def __init__(self):
        self.plugin_id = "block-file-icons"
        self.data_dir = ""
        self.locale = "zh"
        self.kv_tooltip = False
        self.prefs = {"picker": True, "sync_tabs": True}
        self.icon_catalog = _load_icon_catalog()

    def _is_en(self):
        return str(self.locale or "").lower().startswith("en")

    def _tr(self, zh, en):
        return en if self._is_en() else zh

    def _localize_error(self, message):
        text = str(message or "").strip()
        if self._is_en() and CHINESE_TEXT.search(text):
            return "Operation failed"
        return text or self._tr("操作失败", "Operation failed")

    @staticmethod
    def _clean_prefs(raw, fallback=None):
        base = dict(fallback or {"picker": True, "sync_tabs": True})
        if isinstance(raw, dict):
            if "picker" in raw:
                base["picker"] = bool(raw["picker"])
            if "sync_tabs" in raw:
                base["sync_tabs"] = bool(raw["sync_tabs"])
        return base

    def _validate_surface(self, params):
        surface = str((params or {}).get("surface") or SETTINGS_PAGE_SURFACE).strip() or SETTINGS_PAGE_SURFACE
        if surface not in SUPPORTED_SURFACES:
            raise RuntimeError(self._tr(f"不支持的界面: {surface}", f"Unsupported surface: {surface}"))
        return surface

    def _sync_prefs_to_host(self, bridge):
        try:
            bridge.call_host("host.sidebar.set_file_icons", {"prefs": dict(self.prefs)})
        except HostRPCError as exc:
            if exc.code != -32601:
                raise

    def _get_sidebar_state(self, bridge):
        try:
            res = bridge.call_host("host.sidebar.get_file_icons", {})
            if isinstance(res, dict):
                return res
        except HostRPCError as exc:
            if exc.code != -32601:
                raise
        return {
            "entries": {},
            "recent": [],
            "prefs": dict(self.prefs),
            "notebook_root": "",
        }

    def _icon_label(self, icon_id):
        info = self.icon_catalog.get(icon_id)
        if info:
            return info["en"] if self._is_en() else info["zh"]
        return icon_id

    def _tint_label(self, tint):
        key = str(tint or "none").strip().lower()
        pair = TINT_LABELS.get(key, TINT_LABELS["none"])
        return pair[1] if self._is_en() else pair[0]

    def _build_page(self, state, status=""):
        entries = state.get("entries")
        if not isinstance(entries, dict):
            entries = {}
        notebook_root = str(state.get("notebook_root") or "").strip()
        notebook_meta = os.path.basename(notebook_root.rstrip("/\\")) if notebook_root else ""

        display_card = {
            "id": "display",
            "title": self._tr("交互与显示", "Display"),
            "items": [
                {
                    "kind": "switch",
                    "id": "picker",
                    "label": self._tr("点击笔记本与侧栏图标更换", "Click notebook and sidebar icons to change"),
                    "value": bool(self.prefs.get("picker", True)),
                },
                {
                    "kind": "switch",
                    "id": "sync_tabs",
                    "label": self._tr("顶栏标签页同步显示自定义图标", "Show custom icons on tabs"),
                    "value": bool(self.prefs.get("sync_tabs", True)),
                },
            ],
        }

        pack_count = len(self.icon_catalog) or 96
        notebook_items = [
            {
                "kind": "metrics",
                "metrics": [
                    {
                        "label": self._tr("已自定义", "Customized"),
                        "value": str(len(entries)),
                        "tone": "notes",
                    },
                    {
                        "label": self._tr("图标库", "Icon Pack"),
                        "value": str(pack_count),
                        "tone": "assets",
                    },
                ],
            }
        ]

        if entries:
            sorted_paths = sorted(entries.keys(), key=lambda p: (0 if p == "." else 1, p))
            limit = 12
            if len(sorted_paths) > limit:
                shown_paths = sorted_paths[: limit - 1]
                remaining = len(sorted_paths) - len(shown_paths)
            else:
                shown_paths = sorted_paths
                remaining = 0

            rows = []
            for rel_path in shown_paths:
                item = entries.get(rel_path) or {}
                icon_id = str(item.get("icon") or "").strip()
                tint = str(item.get("tint") or "none").strip()
                val_text = f"{self._icon_label(icon_id)} · {self._tint_label(tint)}"
                if rel_path == ".":
                    label = self._tr("笔记本图标", "Notebook icon")
                    tip = notebook_meta or notebook_root or label
                else:
                    label = rel_path
                    tip = rel_path
                row = {"label": label, "value": val_text}
                if self.kv_tooltip:
                    row["tooltip"] = tip
                rows.append(row)

            if remaining > 0:
                rows.append({
                    "label": self._tr("其余条目", "Remaining"),
                    "value": self._tr(f"{remaining} 项", f"{remaining} more"),
                })

            notebook_items.append({"kind": "kv", "rows": rows})
            notebook_items.append({
                "kind": "actions",
                "buttons": [
                    {
                        "id": "reset_notebook",
                        "label": self._tr("清空当前笔记本图标", "Reset Notebook Icons"),
                        "variant": "danger",
                    }
                ],
            })
        else:
            notebook_items.append({
                "kind": "log_list",
                "empty_text": self._tr(
                    "当前笔记本尚未设置自定义图标，点击侧栏或顶栏中的笔记本、文件或文件夹图标即可更换。",
                    "No custom icons set in this notebook. Click any notebook, file, or folder icon in the sidebar or titlebar to customize it.",
                ),
                "entries": [],
            })

        notebook_card = {
            "id": "notebook",
            "title": self._tr("当前笔记本", "Current Notebook"),
            "items": notebook_items,
        }
        if notebook_meta:
            notebook_card["meta"] = notebook_meta

        page = {
            "title": self._tr("自定义图标", "Custom Icons"),
            "cards": [display_card, notebook_card],
        }
        if status:
            page["status"] = status
        return page

    def handle(self, bridge, method, params):
        if method == "plugin.initialize":
            self.plugin_id = str(params.get("plugin_id") or "block-file-icons")
            self.data_dir = str(params.get("data_dir") or "")
            self.locale = str(params.get("locale") or "zh")
            caps = set(params.get("ui_capabilities") or [])
            self.kv_tooltip = "kv_tooltip" in caps

            stored = bridge.call_host("host.storage.get", {"key": STORAGE_KEY})
            if isinstance(stored, dict) and stored.get("found") and isinstance(stored.get("value"), dict):
                self.prefs = self._clean_prefs(stored["value"], self.prefs)
            self._sync_prefs_to_host(bridge)
            return {"ready": True}

        if method == "plugin.render":
            self._validate_surface(params)
            values = params.get("values")
            if isinstance(values, dict) and values:
                next_prefs = dict(self.prefs)
                changed = False
                for key in ("picker", "sync_tabs"):
                    if key in values:
                        val = bool(values[key])
                        if next_prefs.get(key) != val:
                            changed = True
                        next_prefs[key] = val
                if changed:
                    self.prefs = next_prefs
                    bridge.call_host("host.storage.set", {"key": STORAGE_KEY, "value": dict(self.prefs)})
                    self._sync_prefs_to_host(bridge)
                accepted = {k: bool(self.prefs[k]) for k in ("picker", "sync_tabs") if k in values}
            else:
                accepted = dict(self.prefs)

            state = self._get_sidebar_state(bridge)
            return {"page": self._build_page(state), "values": accepted}

        if method == "plugin.action":
            self._validate_surface(params)
            action_id = str(params.get("action_id") or "")
            if action_id == "reset_notebook":
                try:
                    bridge.call_host("host.sidebar.set_file_icons", {"clear": True})
                except HostRPCError as exc:
                    if exc.code != -32601:
                        raise
                state = self._get_sidebar_state(bridge)
                status = self._tr("已清空当前笔记本自定义图标", "Cleared custom icons for this notebook")
                return {
                    "ok": True,
                    "tone": "success",
                    "values": dict(self.prefs),
                    "page": self._build_page(state, status=status),
                    "status": status,
                }
            state = self._get_sidebar_state(bridge)
            status = self._tr("未知操作", "Unknown action")
            return {
                "ok": False,
                "tone": "warning",
                "values": dict(self.prefs),
                "page": self._build_page(state),
                "status": status,
            }

        if method == "plugin.event":
            event_name = str(params.get("event") or "")
            if event_name == "locale.changed" and params.get("locale"):
                self.locale = str(params["locale"])
                return {"handled": True}
            return {"handled": False}

        if method == "plugin.shutdown":
            return {"ok": True}

        raise RuntimeError(self._tr(f"不支持的方法: {method}", f"Unsupported method: {method}"))


def main():
    plugin = FileIconsPlugin()
    HostBridge().serve(plugin.handle, plugin._localize_error)


if __name__ == "__main__":
    main()
