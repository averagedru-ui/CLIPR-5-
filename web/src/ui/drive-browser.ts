import { listDriveFolder, downloadDriveFile, type DriveItem, type DriveDownloadResult } from "../drive";

interface Crumb {
  id: string;
  name: string;
}

export class DriveBrowser {
  private backdrop: HTMLDivElement;
  private crumbEl: HTMLDivElement;
  private listEl: HTMLDivElement;
  private statusEl: HTMLDivElement;
  private path: Crumb[] = [{ id: "root", name: "My Drive" }];
  private resolvePick: ((r: DriveDownloadResult | null) => void) | null = null;

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
        <div class="drive-status hidden" data-status></div>
      </div>
    `;
    this.crumbEl = this.backdrop.querySelector("[data-crumbs]")!;
    this.listEl = this.backdrop.querySelector("[data-list]")!;
    this.statusEl = this.backdrop.querySelector("[data-status]")!;
    this.backdrop.querySelector("[data-close]")!.addEventListener("click", () => this.close(null));
    this.backdrop.addEventListener("click", (e) => { if (e.target === this.backdrop) this.close(null); });
  }

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
      row.innerHTML = `<div><div class="name">${item.isFolder ? "\u{1F4C1}" : "\u{1F3AC}"} ${escapeHtml(item.name)}</div></div>`;
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
    this.onDownloadStart();
    this.statusEl.classList.remove("hidden");
    this.statusEl.textContent = `Downloading ${item.name}…`;
    try {
      const result = await downloadDriveFile(this.token, item.id);
      this.close(result);
    } catch (err) {
      this.statusEl.textContent = (err as Error).message;
    }
  }
}

function escapeHtml(s: string): string {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
