/**
 * Official block-file-icons plugin for Block (blockmd).
 */
import * as std from 'qjs:std';
import { HostRPCError, callHost, serve } from '/runtime/block-sdk.js';

const STORAGE_KEY = 'prefs';
const SETTINGS_PAGE_SURFACE = 'settings_page';
const SUPPORTED_SURFACES = new Set([SETTINGS_PAGE_SURFACE]);
const ICON_PACK_PATH = '/plugin/icons.json';
const CHINESE_TEXT = /[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]/;
const PREF_KEYS = ['picker', 'sync_tabs'];

const TINT_LABELS = {
  none: ['原色', 'Default'],
  blue: ['海蓝', 'Blue'],
  teal: ['青绿', 'Teal'],
  green: ['森绿', 'Green'],
  amber: ['琥珀', 'Amber'],
  red: ['朱红', 'Red'],
  purple: ['紫罗兰', 'Purple'],
};

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasOwn(obj, key) {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

function pathBasename(rawPath) {
  const trimmed = String(rawPath || '').trim().replace(/[/\\]+$/, '');
  if (!trimmed) {
    return '';
  }
  const idx = Math.max(trimmed.lastIndexOf('/'), trimmed.lastIndexOf('\\'));
  return idx >= 0 ? trimmed.slice(idx + 1) : trimmed;
}

/**
 * Load icon display labels from the read-only /plugin/icons.json pack.
 */
function loadIconCatalog() {
  try {
    const raw = std.loadFile(ICON_PACK_PATH);
    if (!raw) {
      return Object.create(null);
    }
    const data = JSON.parse(raw);
    const icons = Array.isArray(data && data.icons) ? data.icons : [];
    const catalog = Object.create(null);
    for (const item of icons) {
      if (!isPlainObject(item)) {
        continue;
      }
      const id = String(item.id || '').trim();
      if (!id) {
        continue;
      }
      const name = isPlainObject(item.name) ? item.name : {};
      catalog[id] = {
        zh: String(name.zh || id),
        en: String(name.en || id),
      };
    }
    return catalog;
  } catch (_err) {
    return Object.create(null);
  }
}

function cleanPrefs(raw, fallback = { picker: true, sync_tabs: true }) {
  const base = {
    picker: Boolean(fallback.picker),
    sync_tabs: Boolean(fallback.sync_tabs),
  };
  if (isPlainObject(raw)) {
    for (const key of PREF_KEYS) {
      if (hasOwn(raw, key)) {
        base[key] = Boolean(raw[key]);
      }
    }
  }
  return base;
}

function isHostMethodNotFound(err) {
  return err instanceof HostRPCError && err.code === -32601;
}

/**
 * Manages custom sidebar file/folder icons and preferences for Block.
 */
class FileIconsPlugin {
  constructor() {
    this.pluginId = 'block-file-icons';
    this.dataDir = '';
    this.locale = 'zh';
    this.kvTooltip = false;
    this.prefs = { picker: true, sync_tabs: true };
    this.iconCatalog = loadIconCatalog();
  }

  isEn() {
    return String(this.locale || '').toLowerCase().startsWith('en');
  }

  tr(zh, en) {
    return this.isEn() ? en : zh;
  }

  localizeError(message) {
    const text = String(message ?? '').trim();
    if (this.isEn() && CHINESE_TEXT.test(text)) {
      return 'Operation failed';
    }
    return text || this.tr('操作失败', 'Operation failed');
  }

  validateSurface(params) {
    const raw = params && params.surface != null ? String(params.surface).trim() : '';
    const surface = raw || SETTINGS_PAGE_SURFACE;
    if (!SUPPORTED_SURFACES.has(surface)) {
      throw new Error(this.tr(`不支持的界面: ${surface}`, `Unsupported surface: ${surface}`));
    }
    return surface;
  }

  syncPrefsToHost() {
    try {
      callHost('host.sidebar.set_file_icons', { prefs: { ...this.prefs } });
    } catch (err) {
      if (!isHostMethodNotFound(err)) {
        throw err;
      }
    }
  }

  getSidebarState() {
    try {
      const res = callHost('host.sidebar.get_file_icons', {});
      if (isPlainObject(res)) {
        return res;
      }
    } catch (err) {
      if (!isHostMethodNotFound(err)) {
        throw err;
      }
    }
    return {
      entries: {},
      recent: [],
      prefs: { ...this.prefs },
      notebook_root: '',
    };
  }

  iconLabel(iconId) {
    const info = this.iconCatalog[iconId];
    if (info) {
      return this.isEn() ? info.en : info.zh;
    }
    return iconId;
  }

  tintLabel(tint) {
    const key = String(tint || 'none').trim().toLowerCase();
    const pair = hasOwn(TINT_LABELS, key) ? TINT_LABELS[key] : TINT_LABELS.none;
    return this.isEn() ? pair[1] : pair[0];
  }

  buildPage(state, status = '') {
    const entries = isPlainObject(state.entries) ? state.entries : {};
    const notebookRoot = String(state.notebook_root || '').trim();
    const notebookMeta = pathBasename(notebookRoot);

    const displayCard = {
      id: 'display',
      title: this.tr('交互与显示', 'Display'),
      items: [
        {
          kind: 'switch',
          id: 'picker',
          label: this.tr('点击笔记本与侧栏图标更换', 'Click notebook and sidebar icons to change'),
          value: Boolean(this.prefs.picker),
        },
        {
          kind: 'switch',
          id: 'sync_tabs',
          label: this.tr('顶栏标签页同步显示自定义图标', 'Show custom icons on tabs'),
          value: Boolean(this.prefs.sync_tabs),
        },
      ],
    };

    const entryKeys = Object.keys(entries);
    const packCount = Object.keys(this.iconCatalog).length || 96;
    const notebookItems = [
      {
        kind: 'metrics',
        metrics: [
          {
            label: this.tr('已自定义', 'Customized'),
            value: String(entryKeys.length),
            tone: 'notes',
          },
          {
            label: this.tr('图标库', 'Icon Pack'),
            value: String(packCount),
            tone: 'assets',
          },
        ],
      },
    ];

    if (entryKeys.length > 0) {
      const sortedPaths = entryKeys.slice().sort((a, b) => {
        if (a === '.' && b !== '.') return -1;
        if (b === '.' && a !== '.') return 1;
        return a < b ? -1 : a > b ? 1 : 0;
      });
      const limit = 12;
      let shownPaths = sortedPaths;
      let remaining = 0;
      if (sortedPaths.length > limit) {
        shownPaths = sortedPaths.slice(0, limit - 1);
        remaining = sortedPaths.length - shownPaths.length;
      }

      const rows = [];
      for (const relPath of shownPaths) {
        const item = isPlainObject(entries[relPath]) ? entries[relPath] : {};
        const iconId = String(item.icon || '').trim();
        const tint = String(item.tint || 'none').trim();
        const valText = `${this.iconLabel(iconId)} · ${this.tintLabel(tint)}`;
        let label;
        let tip;
        if (relPath === '.') {
          label = this.tr('笔记本图标', 'Notebook icon');
          tip = notebookMeta || notebookRoot || label;
        } else {
          label = relPath;
          tip = relPath;
        }
        const row = { label, value: valText };
        if (this.kvTooltip) {
          row.tooltip = tip;
        }
        rows.push(row);
      }

      if (remaining > 0) {
        rows.push({
          label: this.tr('其余条目', 'Remaining'),
          value: this.tr(`${remaining} 项`, `${remaining} more`),
        });
      }

      notebookItems.push({ kind: 'kv', rows });
      notebookItems.push({
        kind: 'actions',
        buttons: [
          {
            id: 'reset_notebook',
            label: this.tr('清空当前笔记本图标', 'Reset Notebook Icons'),
            variant: 'danger',
          },
        ],
      });
    } else {
      notebookItems.push({
        kind: 'log_list',
        empty_text: this.tr(
          '当前笔记本尚未设置自定义图标，点击侧栏或顶栏中的笔记本、文件或文件夹图标即可更换。',
          'No custom icons set in this notebook. Click any notebook, file, or folder icon in the sidebar or titlebar to customize it.',
        ),
        entries: [],
      });
    }

    const notebookCard = {
      id: 'notebook',
      title: this.tr('当前笔记本', 'Current Notebook'),
      items: notebookItems,
    };
    if (notebookMeta) {
      notebookCard.meta = notebookMeta;
    }

    const page = {
      title: this.tr('自定义图标', 'Custom Icons'),
      cards: [displayCard, notebookCard],
    };
    if (status) {
      page.status = status;
    }
    return page;
  }

  handle(method, params) {
    if (method === 'plugin.initialize') {
      this.pluginId = String(params.plugin_id || 'block-file-icons');
      this.dataDir = String(params.data_dir || '');
      this.locale = String(params.locale || 'zh');
      const caps = new Set(Array.isArray(params.ui_capabilities) ? params.ui_capabilities : []);
      this.kvTooltip = caps.has('kv_tooltip');

      const stored = callHost('host.storage.get', { key: STORAGE_KEY });
      if (isPlainObject(stored) && stored.found && isPlainObject(stored.value)) {
        this.prefs = cleanPrefs(stored.value, this.prefs);
      }
      this.syncPrefsToHost();
      return { ready: true };
    }

    if (method === 'plugin.render') {
      this.validateSurface(params);
      const values = params.values;
      let accepted;
      if (isPlainObject(values) && Object.keys(values).length > 0) {
        const nextPrefs = { ...this.prefs };
        let changed = false;
        for (const key of PREF_KEYS) {
          if (hasOwn(values, key)) {
            const val = Boolean(values[key]);
            if (nextPrefs[key] !== val) {
              changed = true;
            }
            nextPrefs[key] = val;
          }
        }
        if (changed) {
          this.prefs = nextPrefs;
          callHost('host.storage.set', { key: STORAGE_KEY, value: { ...this.prefs } });
          this.syncPrefsToHost();
        }
        accepted = {};
        for (const key of PREF_KEYS) {
          if (hasOwn(values, key)) {
            accepted[key] = Boolean(this.prefs[key]);
          }
        }
      } else {
        accepted = { ...this.prefs };
      }

      const state = this.getSidebarState();
      return { page: this.buildPage(state), values: accepted };
    }

    if (method === 'plugin.action') {
      this.validateSurface(params);
      const actionId = String(params.action_id || '');
      if (actionId === 'reset_notebook') {
        try {
          callHost('host.sidebar.set_file_icons', { clear: true });
        } catch (err) {
          if (!isHostMethodNotFound(err)) {
            throw err;
          }
        }
        const state = this.getSidebarState();
        const status = this.tr('已清空当前笔记本自定义图标', 'Cleared custom icons for this notebook');
        return {
          ok: true,
          tone: 'success',
          values: { ...this.prefs },
          page: this.buildPage(state, status),
          status,
        };
      }
      const state = this.getSidebarState();
      const status = this.tr('未知操作', 'Unknown action');
      return {
        ok: false,
        tone: 'warning',
        values: { ...this.prefs },
        page: this.buildPage(state),
        status,
      };
    }

    if (method === 'plugin.event') {
      const eventName = String(params.event || '');
      if (eventName === 'locale.changed' && params.locale) {
        this.locale = String(params.locale);
        return { handled: true };
      }
      return { handled: false };
    }

    if (method === 'plugin.shutdown') {
      return { ok: true };
    }

    throw new Error(this.tr(`不支持的方法: ${method}`, `Unsupported method: ${method}`));
  }
}

const plugin = new FileIconsPlugin();

serve((method, params) => {
  try {
    return plugin.handle(method, params);
  } catch (err) {
    const code = err && typeof err.code === 'number' ? err.code : -32000;
    const rawMsg = err && err.message !== undefined ? err.message : err;
    throw new HostRPCError(code, plugin.localizeError(rawMsg));
  }
});
