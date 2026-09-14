import { GOOGLE_CLIENT_ID, GOOGLE_API_KEY } from "./google-config";

// Minimal ambient surface for the two Google script-tag globals - avoids
// pulling in @types/gapi / @types/google.picker for a handful of calls.
declare const google: any;
declare const gapi: any;

const SCOPE = "https://www.googleapis.com/auth/drive.file";

let gisLoaded: Promise<void> | null = null;
let pickerLoaded: Promise<void> | null = null;
let tokenClient: any = null;
let accessToken: string | null = null;

export function driveConfigured(): boolean {
  return Boolean(GOOGLE_CLIENT_ID && GOOGLE_API_KEY);
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(`failed to load ${src}`));
    document.head.appendChild(s);
  });
}

function ensureGis(): Promise<void> {
  if (!gisLoaded) gisLoaded = loadScript("https://accounts.google.com/gsi/client");
  return gisLoaded;
}

function ensurePicker(): Promise<void> {
  if (!pickerLoaded) {
    pickerLoaded = loadScript("https://apis.google.com/js/api.js").then(
      () => new Promise<void>((resolve) => gapi.load("picker", () => resolve()))
    );
  }
  return pickerLoaded;
}

async function getAccessToken(): Promise<string> {
  await ensureGis();
  if (accessToken) return accessToken;
  return new Promise((resolve, reject) => {
    if (!tokenClient) {
      tokenClient = google.accounts.oauth2.initTokenClient({
        client_id: GOOGLE_CLIENT_ID,
        scope: SCOPE,
        callback: () => {}, // overridden per-request below
      });
    }
    tokenClient.callback = (resp: any) => {
      if (resp.error) { reject(new Error(resp.error)); return; }
      accessToken = resp.access_token;
      resolve(accessToken!);
    };
    tokenClient.requestAccessToken({ prompt: "" });
  });
}

export interface DrivePickResult {
  blob: Blob;
  name: string;
}

// Opens Google's own Drive file browser (not the OS file picker) and
// downloads the chosen video's bytes via the Drive API - sidesteps iOS's
// buggy Files-app Drive integration entirely since nothing routes through
// UIDocumentPickerViewController.
export async function pickFromDrive(onDownloadStart?: () => void): Promise<DrivePickResult | null> {
  if (!driveConfigured()) {
    throw new Error("Drive isn't set up yet (missing Google Client ID / API key)");
  }
  const token = await getAccessToken();
  await ensurePicker();

  const fileId = await new Promise<string | null>((resolve, reject) => {
    const view = new google.picker.DocsView(google.picker.ViewId.DOCS_VIDEOS)
      .setIncludeFolders(true)
      .setSelectFolderEnabled(false);
    const picker = new google.picker.PickerBuilder()
      .addView(view)
      .setOAuthToken(token)
      .setDeveloperKey(GOOGLE_API_KEY)
      .setCallback((data: any) => {
        if (data.action === google.picker.Action.PICKED) {
          resolve(data.docs[0].id);
        } else if (data.action === google.picker.Action.CANCEL) {
          resolve(null);
        }
      })
      .build();
    picker.setVisible(true);
    void reject; // no async error path from the picker itself
  });

  if (!fileId) return null;
  onDownloadStart?.();

  const meta = await fetch(
    `https://www.googleapis.com/drive/v3/files/${fileId}?fields=name`,
    { headers: { Authorization: `Bearer ${token}` } }
  ).then((r) => r.json());

  const res = await fetch(
    `https://www.googleapis.com/drive/v3/files/${fileId}?alt=media`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok) {
    throw new Error(`Drive download failed (${res.status} ${res.statusText})`);
  }
  const blob = await res.blob();
  return { blob, name: meta.name ?? "drive-video.mp4" };
}
