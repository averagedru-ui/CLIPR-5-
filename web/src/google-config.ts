// Value comes from a Vite env var (VITE_* is the only prefix Vite exposes to
// client code) so the real Client ID never lands in the git repo. Local dev:
// put it in web/.env.local (gitignored). Production: set the same name in
// the Vercel project's Environment Variables - Vite bakes it in at build
// time, so a change there needs a redeploy to take effect.
//
// No API key needed anymore - the custom Drive browser (drive.ts,
// ui/drive-browser.ts) talks to the Drive API with just the OAuth bearer
// token, unlike Google's Picker widget which required a developer key too.
export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "";
