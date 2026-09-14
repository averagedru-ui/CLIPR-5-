// Public by design - an OAuth Client ID + API key are meant to live in
// client-side code (Google restricts them by authorized origin on their
// end, not by keeping them secret). Fill these in from Google Cloud
// Console -> APIs & Services -> Credentials after enabling the Drive API
// and Picker API for a project with the OAuth consent screen in Testing
// mode (your own account added as a test user).
export const GOOGLE_CLIENT_ID = "";
export const GOOGLE_API_KEY = "";
