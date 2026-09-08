// Point d'entrée de suppression de compte eBay — conformité RGPD/CCPA (WP10).
//
// Hébergé gratuitement sur Cloudflare Workers, toujours actif : il accuse
// réception 24/7 même quand le serveur maison est éteint. Les notifications sont
// mises en file dans Cloudflare KV ; RamTracker les tire (`ramtracker
// account-deletion-drain`) et efface en base quand il tourne.
//
// Variables (wrangler) :
//   EBAY_VERIFICATION_TOKEN   secret — 32-80 car. [A-Za-z0-9_-], identique au portail eBay
//   EBAY_DELETION_ENDPOINT_URL var   — URL publique de CE worker + le chemin ci-dessous
//   PULL_SECRET               secret — jeton partagé avec RamTracker pour /pending et /ack
//   PENDING                   binding KV

const PATH = "/ebay/marketplace-account-deletion";
const TOPIC = "MARKETPLACE_ACCOUNT_DELETION";

async function sha256Hex(input) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function bearerOk(request, env) {
  const header = request.headers.get("Authorization") || "";
  return Boolean(env.PULL_SECRET) && header === `Bearer ${env.PULL_SECRET}`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // -- challenge eBay : prouve la propriété du point d'entrée
    if (request.method === "GET" && url.pathname === PATH) {
      const code = url.searchParams.get("challenge_code");
      if (!code) return new Response("challenge_code manquant", { status: 400 });
      const response = await sha256Hex(
        code + env.EBAY_VERIFICATION_TOKEN + env.EBAY_DELETION_ENDPOINT_URL,
      );
      return Response.json({ challengeResponse: response });
    }

    // -- notification de suppression : on accuse réception tout de suite, on met en file
    if (request.method === "POST" && url.pathname === PATH) {
      let payload;
      try {
        payload = await request.json();
      } catch {
        return new Response(null, { status: 204 });
      }
      const topic = payload?.metadata?.topic;
      const notification = payload?.notification;
      const id = notification?.notificationId;
      const username = notification?.data?.username;
      if (topic === TOPIC && id && username) {
        // La clé = notificationId : eBay réémet la même notification, put écrase.
        await env.PENDING.put(id, "1", {
          metadata: { notificationId: id, username, receivedAt: new Date().toISOString() },
        });
      }
      return new Response(null, { status: 204 });
    }

    // -- RamTracker tire la file en attente
    if (request.method === "GET" && url.pathname === "/pending") {
      if (!bearerOk(request, env)) return new Response("interdit", { status: 403 });
      const list = await env.PENDING.list();
      return Response.json(list.keys.map((k) => k.metadata).filter(Boolean));
    }

    // -- RamTracker acquitte ce qu'il a traité
    if (request.method === "POST" && url.pathname === "/ack") {
      if (!bearerOk(request, env)) return new Response("interdit", { status: 403 });
      let body;
      try {
        body = await request.json();
      } catch {
        return new Response("json invalide", { status: 400 });
      }
      const ids = Array.isArray(body?.notificationIds) ? body.notificationIds : [];
      await Promise.all(ids.map((id) => env.PENDING.delete(id)));
      return new Response(null, { status: 204 });
    }

    return new Response("not found", { status: 404 });
  },
};
