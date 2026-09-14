// Values come from Vite env vars (VITE_* is the only prefix Vite exposes to
// client code) so the real Client ID / API key never land in the git repo.
// Local dev: put them in web/.env.local (gitignored). Production: set the
// same two names in the Vercel project's Environment Variables - Vite bakes
// them in at build time, so a change there needs a redeploy to take effect.
export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? "";
export const GOOGLE_API_KEY = import.meta.env.VITE_GOOGLE_API_KEY ?? "";
