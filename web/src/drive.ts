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
const TOKEN_KEY = "clipr_drive_token";           // sessionStorage - short-lived access token
const REFRESH_KEY = "clipr_drive_refresh_token"; // localStorage - persists across app relaunches
const VERIFIER_KEY = "clipr_drive_pkce_verifier";
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

function base64url(bytes: Uint8Array): string {
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function pkcePair(): Promise<{ verifier: string; challenge: string }> {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  const verifier = base64url(bytes);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return { verifier, challenge: base64url(new Uint8Array(digest)) };
}

// Google's popup-based sign-in (Identity Services token client) is unreliable
// on mobile Safari/PWA: WebKit turns the popup into a plain new tab, and the
// token callback depends on that tab talking back to window.opener - which
// silently fails in a standalone PWA, leaving the user stuck on Google's
// sign-in screen with nothing happening back in the app. A full-page
// redirect has no such handoff to break.
//
// Authorization Code + PKCE (not the simpler implicit "response_type=token"
// flow used at first) specifically so Google issues a refresh_token -
// implicit grant never does, which meant re-signing-in every ~1hr no matter
// what. access_type=offline + prompt=consent are both required for Google
// to actually include a refresh_token in the response.
async function redirectToGoogleAuth() {
  sessionStorage.setItem(PENDING_KEY, "1");
  const { verifier, challenge } = await pkcePair();
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  url.searchParams.set("client_id", GOOGLE_CLIENT_ID);
  url.searchParams.set("redirect_uri", redirectUri());
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", SCOPE);
  url.searchParams.set("access_type", "offline");
  url.searchParams.set("prompt", "consent");
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  window.location.href = url.toString();
}

// Google requires the "Web application" client's secret for this exchange
// even with PKCE - there's no secret-free path for this client type - so it
// goes through our own /api/drive-token serverless function instead of
// oauth2.googleapis.com directly, keeping the secret server-side.
async function callTokenEndpoint(body: Record<string, string>): Promise<any> {
  const res = await fetch("/api/drive-token", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error_description || data.error || `token request failed (${res.status})`);
  return data;
}

async function exchangeCodeForTokens(code: string, verifier: string): Promise<void> {
  const data = await callTokenEndpoint({
    grant_type: "authorization_code",
    code,
    code_verifier: verifier,
    redirect_uri: redirectUri(),
  });
  if (data.access_token) cacheToken(data.access_token, data.expires_in ?? 3600);
  if (data.refresh_token) localStorage.setItem(REFRESH_KEY, data.refresh_token);
}

async function refreshAccessToken(refreshToken: string): Promise<string> {
  const data = await callTokenEndpoint({ grant_type: "refresh_token", refresh_token: refreshToken });
  cacheToken(data.access_token, data.expires_in ?? 3600);
  return data.access_token;
}

// Call once at app boot. Exchanges an authorization code left in the URL by
// the redirect above (if any), and reports whether a Drive open was left
// pending (i.e. the Drive browser should reopen automatically now that
// we're back).
export async function handleAuthRedirectReturn(): Promise<{ pendingPick: boolean }> {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  if (code) {
    const verifier = sessionStorage.getItem(VERIFIER_KEY) ?? "";
    sessionStorage.removeItem(VERIFIER_KEY);
    try {
      await exchangeCodeForTokens(code, verifier);
    } catch (err) {
      console.error("Drive sign-in failed:", err);
    }
    history.replaceState(null, "", window.location.pathname);
  }
  const pendingPick = sessionStorage.getItem(PENDING_KEY) === "1";
  sessionStorage.removeItem(PENDING_KEY);
  return { pendingPick };
}

// Returns null (and starts a redirect away from the page) when there's no
// valid token and no usable refresh token yet - callers must treat null as
// "nothing more to do here." Silently mints a fresh access token from the
// stored refresh token when possible, with no redirect/user interaction -
// this is what avoids signing in every session.
export async function getAccessToken(): Promise<string | null> {
  const cached = getCachedToken();
  if (cached) return cached;
  const refreshToken = localStorage.getItem(REFRESH_KEY);
  if (refreshToken) {
    try {
      return await refreshAccessToken(refreshToken);
    } catch {
      localStorage.removeItem(REFRESH_KEY); // stale/revoked - fall through to full re-auth
    }
  }
  await redirectToGoogleAuth();
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
// which does survive backgrounding.
//
// First attempt used the Drive API's `alt=media` with the OAuth
// access_token as a query param - Google's automated-abuse detection
// ("We're sorry... your computer or network may be sending automated
// queries") blocked that outright and consistently, not just as a
// transient rate limit. Using Drive's own classic direct-download
// endpoint instead: this relies on the browser's normal Google session
// cookie (set when the user just signed in via the redirect flow above,
// in this same browser) rather than a token in the URL at all - it's the
// same URL shape Drive's own "get shareable link" feature produces, so it
// isn't flagged as automated the way a bare API call with a bearer token
// in the query string apparently is. Large files may show Drive's own
// "can't scan for viruses" confirmation click-through first - that's
// normal Drive behavior, not an error.
export function driveMediaUrl(fileId: string): string {
  const url = new URL("https://drive.usercontent.google.com/download");
  url.searchParams.set("id", fileId);
  url.searchParams.set("export", "download");
  url.searchParams.set("confirm", "t");
  return url.toString();
}

export interface DriveDownloadResult {
  blob: Blob;
  name: string;
}

export interface DriveFileMeta {
  name: string;
  size: number | null;
}

export async function getDriveFileMeta(token: string, fileId: string): Promise<DriveFileMeta> {
  const res = await fetch(
    `https://www.googleapis.com/drive/v3/files/${fileId}?fields=name,size`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  const data = await res.json();
  return { name: data.name ?? "drive-video.mp4", size: data.size ? Number(data.size) : null };
}

// One-tap in-page fetch when the file is small enough that holding it in
// memory as a Blob is safe - used for the common case (a short/medium
// clip) so most imports don't need the Safari-handoff detour at all.
// Above DRIVE_INLINE_MAX_BYTES the caller should fall back to
// driveMediaUrl() instead: a page-driven fetch assembling a large Blob is
// what crashed the Safari tab outright on a real multi-hundred-MB
// gameplay clip (confirmed, not theoretical).
export const DRIVE_INLINE_MAX_BYTES = 300 * 1024 * 1024; // 300MB

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
