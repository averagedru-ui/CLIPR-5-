import {
  listDriveFolder, driveMediaUrl, downloadDriveFile, getDriveFileMeta,
  DRIVE_INLINE_MAX_BYTES, type DriveItem, type DriveDownloadResult,
} from "../drive";
import { iconFolder, iconFilm } from "./icons";

interface Crumb {
  id: string;
  name: string;
}

export class DriveBrowser {
  private backdrop: HTMLDivElement;
  private crumbEl: HTMLDivElement;
  private listEl: HTMLDivElement;
  private statusEl: HTMLDivElement;
  private statusTextEl: HTMLSpanElement;
  private cancelEl: HTMLSpanElement;
  private path: Crumb[] = [{ id: "root", name: "My Drive" }];
  private resolvePick: ((r: DriveDownloadResult | null) => void) | null = null;
  private downloadAbort: AbortController | null = null;

  constructor(private token: string, private onDownloadStart: () => void) {
    this.backdrop = document.createElement("div");
    this.backdrop.className = "modal-backdrop";
    this.backdrop.innerHTML = `
      <div class="modal">
        <div class="modal-head">
          <span>Google Drive</span>
          <span class="del" data-close>✕</span>
        </div>
        <div class="drive-crumbs" data-crumbs></div>
        <div class="modal-body" data-list></div>
        <div class="drive-status hidden" data-status>
          <span data-status-text></span>
          <span class="drive-cancel hidden" data-cancel>Cancel</span>
        </div>
      </div>
    `;
    this.crumbEl = this.backdrop.querySelector("[data-crumbs]")!;
    this.listEl = this.backdrop.querySelector("[data-list]")!;
    this.statusEl = this.backdrop.querySelector("[data-status]")!;
    this.statusTextEl = this.backdrop.querySelector("[data-status-text]")!;
    this.cancelEl = this.backdrop.querySelector("[data-cancel]")!;
    this.cancelEl.addEventListener("click", () => this.downloadAbort?.abort());
    this.backdrop.querySelector("[data-close]")!.addEventListener("click", () => this.close(null));
    this.backdrop.addEventListener("click", (e) => { if (e.target === this.backdrop) this.close(null); });
  }

  // Resolves with a downloaded Blob for the auto-import path (small files),
  // or null when the modal was dismissed / a large file was handed off to
  // Safari's own downloader instead (see onItemClick).
  open(): Promise<DriveDownloadResult | null> {
    document.body.appendChild(this.backdrop);
    this.renderCrumbs();
    this.loadFolder(this.path[this.path.length - 1].id);
    return new Promise((resolve) => { this.resolvePick = resolve; });
  }

  private close(result: DriveDownloadResult | null) {
    this.backdrop.remove();
    this.resolvePick?.(result);
    this.resolvePick = null;
  }

  private renderCrumbs() {
    this.crumbEl.innerHTML = "";
    this.path.forEach((crumb, i) => {
      const isLast = i === this.path.length - 1;
      const el = document.createElement("span");
      el.className = "drive-crumb" + (isLast ? " current" : "");
      el.textContent = crumb.name;
      if (!isLast) {
        el.addEventListener("click", () => {
          this.path = this.path.slice(0, i + 1);
          this.renderCrumbs();
          this.loadFolder(crumb.id);
        });
      }
      this.crumbEl.appendChild(el);
      if (!isLast) {
        const sep = document.createElement("span");
        sep.className = "drive-crumb-sep";
        sep.textContent = "›";
        this.crumbEl.appendChild(sep);
      }
    });
  }

  private async loadFolder(folderId: string) {
    this.listEl.innerHTML = `<div class="tpl-empty">Loading…</div>`;
    try {
      const items = await listDriveFolder(this.token, folderId);
      this.renderItems(items);
    } catch (err) {
      this.listEl.innerHTML = `<div class="tpl-empty">${escapeHtml((err as Error).message)}</div>`;
    }
  }

  private renderItems(items: DriveItem[]) {
    this.listEl.innerHTML = "";
    if (!items.length) {
      this.listEl.innerHTML = `<div class="tpl-empty">Empty folder (or no videos in here).</div>`;
      return;
    }
    for (const item of items) {
      const row = document.createElement("div");
      row.className = "tpl-item";
      row.innerHTML = `<div class="name">${item.isFolder ? iconFolder : iconFilm} ${escapeHtml(item.name)}</div>`;
      row.addEventListener("click", () => this.onItemClick(item));
      this.listEl.appendChild(row);
    }
  }

  private async onItemClick(item: DriveItem) {
    if (item.isFolder) {
      this.path.push({ id: item.id, name: item.name });
      this.renderCrumbs();
      this.loadFolder(item.id);
      return;
    }

    this.statusEl.classList.remove("hidden");
    this.statusTextEl.textContent = "Checking file size…";
    let meta;
    try {
      meta = await getDriveFileMeta(this.token, item.id);
    } catch (err) {
      this.statusTextEl.textContent = (err as Error).message;
      return;
    }

    // Small enough to hold safely in memory: fetch it in-page and
    // auto-import in one tap, no manual re-select needed afterward.
    if (meta.size != null && meta.size <= DRIVE_INLINE_MAX_BYTES) {
      this.onDownloadStart();
      this.cancelEl.classList.remove("hidden");
      this.downloadAbort = new AbortController();
      try {
        const result = await downloadDriveFile(
          this.token,
          item.id,
          (received, total) => {
            const mb = (received / (1024 * 1024)).toFixed(1);
            this.statusTextEl.textContent = total
              ? `Downloading ${item.name}… ${mb} / ${(total / (1024 * 1024)).toFixed(1)} MB`
              : `Downloading ${item.name}… ${mb} MB`;
          },
          this.downloadAbort.signal
        );
        this.close(result);
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          this.statusEl.classList.add("hidden");
        } else {
          this.statusTextEl.textContent = (err as Error).message;
        }
      } finally {
        this.cancelEl.classList.add("hidden");
        this.downloadAbort = null;
      }
      return;
    }

    // Large file (or unknown size): a page-driven fetch assembling this
    // into a Blob is what crashed the Safari tab outright before. Hand the
    // URL to Safari's own downloader instead - survives backgrounding and
    // large files, at the cost of a manual re-import step afterward.
    const url = driveMediaUrl(item.id);
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    this.statusTextEl.textContent =
      `"${item.name}" is large (${meta.size ? (meta.size / (1024 * 1024)).toFixed(0) + " MB" : "size unknown"}) - ` +
      `started it in Safari instead to avoid a memory crash. Check the download arrow (or the video ` +
      `player's Share/Save button) in the toolbar, then use "Video" here to import it once saved.`;
    setTimeout(() => this.close(null), 4500);
  }
}

function escapeHtml(s: string): string {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
