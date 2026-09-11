import { fileIo as fs } from '@kit.CoreFileKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { Settings } from './Settings';

const DOMAIN: number = 0x0000;
const TAG: string = 'KaogongCache';
const DIR_NAME: string = 'content-cache';

/** 缓存对外结构：正文 + 写入时间，便于页面显示「缓存于 x 前」。 */
export interface CacheEntry {
  text: string;
  savedAt: number;
}

/**
 * 内容缓存。
 *
 * 解决两件事：
 * 1. **离线可读**——断网时用上次成功抓到的内容兜底，而不是白屏；
 *    （时政类产品的核心场景是通勤，地铁里断网是常态）
 * 2. **冷启动秒开**——先同步读缓存立刻渲染，再在后台请求刷新。
 *
 * ## 为什么用文件而不是 Preferences
 * `manifest.json` 约 40KB，而 Preferences 对单个 value 有大小限制，
 * 且它是"配置存储"语义，不适合放内容。文件读写也能支持**同步读**——
 * 秒开依赖同步读（异步读会先闪一帧空白）。
 *
 * 缓存失败一律**不阻断功能**：只打日志，网络路径照常工作。
 */
export class Cache {
  private static dir: string | null = null;
  private static resolved: boolean = false;

  /** 缓存根目录；取不到（无 context / 建目录失败）时返回 null。 */
  private static baseDir(): string | null {
    if (Cache.resolved) {
      return Cache.dir;
    }
    Cache.resolved = true;
    const context = Settings.context();
    if (context === null) {
      return null;
    }
    const dir: string = `${context.filesDir}/${DIR_NAME}`;
    try {
      if (!fs.accessSync(dir)) {
        fs.mkdirSync(dir);
      }
      Cache.dir = dir;
    } catch (err) {
      // 并发或残留都可能导致 mkdir 抛错；再确认一次存在性
      try {
        Cache.dir = fs.accessSync(dir) ? dir : null;
      } catch (accessErr) {
        Cache.dir = null;
      }
      if (Cache.dir === null) {
        const cause: Error = err as Error;
        hilog.warn(DOMAIN, TAG, '缓存目录不可用，将退化为纯在线模式：%{public}s', cause.message);
      }
    }
    return Cache.dir;
  }

  /** URL → 稳定且可读的文件名（便于排查，不用 hash）。 */
  private static fileOf(url: string): string | null {
    const dir: string | null = Cache.baseDir();
    if (dir === null) {
      return null;
    }
    const slug: string = url
      .replace('https://', '')
      .replace(/[^A-Za-z0-9._-]/g, '_');
    return `${dir}/${slug}`;
  }

  static read(url: string): CacheEntry | null {
    const path: string | null = Cache.fileOf(url);
    if (path === null) {
      return null;
    }
    try {
      if (!fs.accessSync(path)) {
        return null;
      }
      const wrapper: CacheEntry = JSON.parse(fs.readTextSync(path)) as CacheEntry;
      if (wrapper.text.length === 0) {
        return null;
      }
      return wrapper;
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '读取缓存失败（忽略，走网络）：%{public}s', cause.message);
      return null;
    }
  }

  static write(url: string, text: string): void {
    const path: string | null = Cache.fileOf(url);
    if (path === null) {
      return;
    }
    try {
      const wrapper: CacheEntry = { text: text, savedAt: Date.now() };
      const file: fs.File = fs.openSync(path, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
      try {
        fs.writeSync(file.fd, JSON.stringify(wrapper));
      } finally {
        fs.closeSync(file);
      }
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '写入缓存失败（不影响本次展示）：%{public}s', cause.message);
    }
  }

  /** 缓存体积概览，用于排查（也便于将来做"清理缓存"入口）。 */
  static stats(): string {
    const dir: string | null = Cache.baseDir();
    if (dir === null) {
      return '缓存不可用';
    }
    try {
      const names: string[] = fs.listFileSync(dir);
      return `${names.length} 个文件`;
    } catch (err) {
      return '统计失败';
    }
  }
}
