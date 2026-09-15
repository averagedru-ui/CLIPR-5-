import { listDriveFolder, driveMediaUrl, type DriveItem } from "../drive";

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
  private path: Crumb[] = [{ id: "root", name: "My Drive" }];
  private resolveClose: (() => void) | null = null;

  constructor(private token: string) {
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
        </div>
      </div>
    `;
    this.crumbEl = this.backdrop.querySelector("[data-crumbs]")!;
    this.listEl = this.backdrop.querySelector("[data-list]")!;
    this.statusEl = this.backdrop.querySelector("[data-status]")!;
    this.statusTextEl = this.backdrop.querySelector("[data-status-text]")!;
    this.backdrop.querySelector("[data-close]")!.addEventListener("click", () => this.close());
    this.backdrop.addEventListener("click", (e) => { if (e.target === this.backdrop) this.close(); });
  }

  // Resolves once the modal is dismissed (either the user closed it, or a
  // download was started and the modal closed itself).
  open(): Promise<void> {
    document.body.appendChild(this.backdrop);
    this.renderCrumbs();
    this.loadFolder(this.path[this.path.length - 1].id);
    return new Promise((resolve) => { this.resolveClose = resolve; });
  }

  private close() {
    this.backdrop.remove();
    this.resolveClose?.();
    this.resolveClose = null;
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
      row.innerHTML = `<div><div class="name">${item.isFolder ? "\u{1F4C1}" : "\u{1F3AC}"} ${escapeHtml(item.name)}</div></div>`;
      row.addEventListener("click", () => this.onItemClick(item));
      this.listEl.appendChild(row);
    }
  }

  private onItemClick(item: DriveItem) {
    if (item.isFolder) {
      this.path.push({ id: item.id, name: item.name });
      this.renderCrumbs();
      this.loadFolder(item.id);
      return;
    }
    // Hand off to Safari's own download/media handling instead of fetching
    // the bytes ourselves - see driveMediaUrl() for why. A plain tab
    // navigation (not fetch) is what lets the OS take over and survive the
    // app being backgrounded.
    const url = driveMediaUrl(item.id);
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();

    this.statusEl.classList.remove("hidden");
    this.statusTextEl.textContent =
      `Started "${item.name}" in Safari - check the download arrow (or the video player's Share/Save button) ` +
      `in the toolbar. Once it's saved, come back and use the "Video" button to import it.`;
    setTimeout(() => this.close(), 3500);
  }
}

function escapeHtml(s: string): string {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
