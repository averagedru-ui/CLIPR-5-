// Vercel Edge Function. Only reason this exists at all: Google's OAuth
// token endpoint requires the "Web application" client's secret even when
// the authorization-code request used PKCE - there is no secret-free path
// for this client type, confirmed before building this (not a guess).
// Keeps GOOGLE_CLIENT_SECRET server-side (plain env var, NOT VITE_-prefixed
// so Vite never bundles it into client JS) instead of exposing it in the
// PWA's public bundle the way the Client ID/API key are allowed to be.
//
// Same-origin call from the app (fetch("/api/drive-token")), so no CORS
// handling needed.
export const config = { runtime: "edge" };

const TOKEN_URL = "https://oauth2.googleapis.com/token";

export default async function handler(req: Request): Promise<Response> {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const clientId = process.env.VITE_GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    return new Response(
      JSON.stringify({ error: "server misconfigured: missing client id/secret" }),
      { status: 500, headers: { "content-type": "application/json" } }
    );
  }

  let body: any;
  try {
    body = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "invalid JSON body" }), {
      status: 400,
      headers: { "content-type": "application/json" },
    });
  }

  const params = new URLSearchParams({ client_id: clientId, client_secret: clientSecret });

  if (body.grant_type === "authorization_code") {
    params.set("grant_type", "authorization_code");
    params.set("code", body.code ?? "");
    params.set("code_verifier", body.code_verifier ?? "");
    params.set("redirect_uri", body.redirect_uri ?? "");
  } else if (body.grant_type === "refresh_token") {
    params.set("grant_type", "refresh_token");
    params.set("refresh_token", body.refresh_token ?? "");
  } else {
    return new Response(JSON.stringify({ error: "unsupported grant_type" }), {
      status: 400,
      headers: { "content-type": "application/json" },
    });
  }

  const googleRes = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: params,
  });
  const data = await googleRes.text();
  return new Response(data, {
    status: googleRes.status,
    headers: { "content-type": "application/json" },
  });
}
