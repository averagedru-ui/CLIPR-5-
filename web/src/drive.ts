import { GOOGLE_CLIENT_ID } from "./google-config";

// drive.readonly (not drive.file): a drive.file-scoped token can only see
// files this app created or that were explicitly opened through Google's
// own Picker widget (Picker gets a special UI-only exemption to browse the
// full Drive for selection - a raw files.list call does NOT get that
// exemption). Since we're hand-rolling our own folder browser instead of
// using Picker, we need real read access. Fine to use outside Google's
// verification review as long as the OAuth consent screen stays in Testing
// mode with only your own account as a test user.
const SCOPE = "https://www.googleapis.com/auth/drive.readonly";
const TOKEN_KEY = "clipr_drive_token";
const PENDING_KEY = "clipr_drive_pending_pick";

export function driveConfigured(): boolean {
  return Boolean(GOOGLE_CLIENT_ID);
}

function redirectUri(): string {
  return window.location.origin + window.location.pathname;
}

function getCachedToken(): string | null {
  try {
    const raw = sessionStorage.getItem(TOKEN_KEY);
    if (!raw) return null;
    const { token, expiresAt } = JSON.parse(raw);
    if (Date.now() > expiresAt - 30_000) return null; // 30s safety margin
    return token;
  } catch {
    return null;
  }
}

function cacheToken(token: string, expiresInSec: number) {
  sessionStorage.setItem(TOKEN_KEY, JSON.stringify({ token, expiresAt: Date.now() + expiresInSec * 1000 }));
}

// Google's popup-based sign-in (Identity Services token client) is unreliable
// on mobile Safari/PWA: WebKit turns the popup into a plain new tab, and the
// token callback depends on that tab talking back to window.opener - which
// silently fails in a standalone PWA, leaving the user stuck on Google's
// sign-in screen with nothing happening back in the app. A full-page
// redirect has no such handoff to break.
function redirectToGoogleAuth() {
  sessionStorage.setItem(PENDING_KEY, "1");
  const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  url.searchParams.set("client_id", GOOGLE_CLIENT_ID);
  url.searchParams.set("redirect_uri", redirectUri());
  url.searchParams.set("response_type", "token");
  url.searchParams.set("scope", SCOPE);
  url.searchParams.set("include_granted_scopes", "true");
  url.searchParams.set("prompt", "consent");
  window.location.href = url.toString();
}

// Call once at app boot. Captures an access_token left in the URL fragment
// by the redirect above, and reports whether a Drive open was left pending
// (i.e. the Drive browser should reopen automatically now that we're back).
export function handleAuthRedirectReturn(): { pendingPick: boolean } {
  const hash = window.location.hash;
  if (hash.includes("access_token")) {
    const params = new URLSearchParams(hash.slice(1));
    const token = params.get("access_token");
    const expiresIn = Number(params.get("expires_in") ?? "3600");
    if (token) cacheToken(token, expiresIn);
    history.replaceState(null, "", window.location.pathname + window.location.search);
  }
  const pendingPick = sessionStorage.getItem(PENDING_KEY) === "1";
  sessionStorage.removeItem(PENDING_KEY);
  return { pendingPick };
}

// Returns null (and starts a redirect away from the page) when there's no
// valid token yet - callers must treat null as "nothing more to do here."
export function getAccessToken(): string | null {
  const cached = getCachedToken();
  if (cached) return cached;
  redirectToGoogleAuth();
  return null;
}

export interface DriveItem {
  id: string;
  name: string;
  isFolder: boolean;
}

const FOLDER_MIME = "application/vnd.google-apps.folder";

// Our own minimal Drive browser (see ui/drive-browser.ts) instead of
// Google's Picker widget - Picker's folder navigation turned out to be
// unreliable in ways not fixable from configuration (folders not opening on
// tap, a flat "Recent" listing instead of real My Drive, videos missing
// from folders that clearly contain them). Plain files.list gives full
// control over exactly this.
export async function listDriveFolder(token: string, folderId: string): Promise<DriveItem[]> {
  const q = encodeURIComponent(`'${folderId}' in parents and trashed = false`);
  const fields = encodeURIComponent("files(id,name,mimeType)");
  const res = await fetch(
    `https://www.googleapis.com/drive/v3/files?q=${q}&fields=${fields}&orderBy=folder,name&pageSize=1000`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) throw new Error(`Drive listing failed (${res.status} ${res.statusText})`);
  const data = await res.json();
  const items: DriveItem[] = (data.files ?? [])
    .filter((f: any) => f.mimeType === FOLDER_MIME || String(f.mimeType).startsWith("video/"))
    .map((f: any) => ({ id: f.id, name: f.name, isFolder: f.mimeType === FOLDER_MIME }));
  return items;
}

// A page-driven fetch() is paused/killed by iOS the moment Safari is
// backgrounded - there is no workaround for that at the JS level, and
// holding a large gameplay clip fully in memory as a Blob while it
// downloads is slow and risky on a phone besides. Handing the URL to
// Safari itself instead lets its OWN download/media handling take over,
// which does survive backgrounding - either its native download manager
// (the arrow-down icon in the toolbar) or, if it opens as a playable video
// instead, the native player's own Share/Save option. Either way the user
// re-imports the resulting local file via the normal "Video" button
// afterward. access_token as a query param (rather than the usual
// Authorization header) is what makes a plain browser navigation able to
// authenticate at all; it's short-lived (~1hr) and this stays a
// personal/private-repo project, so the trade-off is fine here.
export function driveMediaUrl(token: string, fileId: string): string {
  const url = new URL(`https://www.googleapis.com/drive/v3/files/${fileId}`);
  url.searchParams.set("alt", "media");
  url.searchParams.set("access_token", token);
  return url.toString();
}

export interface DriveDownloadResult {
  blob: Blob;
  name: string;
}

// Kept for small files where holding the whole thing in memory briefly is
// fine - not currently used by the Drive browser UI (see driveMediaUrl),
// but useful if a "small clip, just grab it inline" path is wanted later.
export async function downloadDriveFile(
  token: string,
  fileId: string,
  onProgress?: (receivedBytes: number, totalBytes: number | null) => void,
  signal?: AbortSignal
): Promise<DriveDownloadResult> {
  const meta = await fetch(
    `https://www.googleapis.com/drive/v3/files/${fileId}?fields=name`,
    { headers: { Authorization: `Bearer ${token}` }, signal }
  ).then((r) => r.json());

  const res = await fetch(
    `https://www.googleapis.com/drive/v3/files/${fileId}?alt=media`,
    { headers: { Authorization: `Bearer ${token}` }, signal }
  );
  if (!res.ok) throw new Error(`Drive download failed (${res.status} ${res.statusText})`);

  const totalBytes = Number(res.headers.get("Content-Length")) || null;
  // Manual streaming read instead of res.blob() - the app previously just
  // showed a static "Downloading..." with no way to tell a real stall from
  // a large file over slow mobile signal actually working. This reports
  // real progress instead of silence.
  if (!res.body) {
    const blob = await res.blob();
    return { blob, name: meta.name ?? "drive-video.mp4" };
  }
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.byteLength;
    onProgress?.(received, totalBytes);
  }
  const blob = new Blob(chunks as BlobPart[]);
  return { blob, name: meta.name ?? "drive-video.mp4" };
}
