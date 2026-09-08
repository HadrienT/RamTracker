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
//   EBAY_CLIENT_ID            secret — clé applicative eBay, pour récupérer la clé publique
//   EBAY_CLIENT_SECRET        secret — cert applicatif eBay associé
//   ENFORCE_SIGNATURE         var    — "false" pour n'auditer que (défaut : rejette en 412)
//   PENDING                   binding KV

const PATH = "/ebay/marketplace-account-deletion";
const TOPIC = "MARKETPLACE_ACCOUNT_DELETION";

const OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token";
const OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope";
const PUBLIC_KEY_URL = "https://api.ebay.com/commerce/notification/v1/public_key/";

async function sha256Hex(input) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function bearerOk(request, env) {
  const header = request.headers.get("Authorization") || "";
  return Boolean(env.PULL_SECRET) && header === `Bearer ${env.PULL_SECRET}`;
}

// -- vérification du header x-ebay-signature -------------------------------------
//
// eBay signe le corps de la notification en ECDSA/SHA1 sur la courbe P-256. Le
// header est un JSON base64 `{ alg, kid, signature, digest }` ; `signature` est
// encodée en DER alors que WebCrypto attend du P1363 (r||s concaténés). La clé
// publique se récupère via l'API getPublicKey, protégée par un jeton applicatif.

let cachedToken = null; // { value, expiresAt }
const publicKeys = new Map(); // kid -> CryptoKey

function base64ToBytes(value) {
  const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function applicationToken(env) {
  const now = Date.now();
  if (cachedToken && cachedToken.expiresAt - now > 60_000) return cachedToken.value;
  const basic = btoa(`${env.EBAY_CLIENT_ID}:${env.EBAY_CLIENT_SECRET}`);
  const resp = await fetch(OAUTH_URL, {
    method: "POST",
    headers: {
      Authorization: `Basic ${basic}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: `grant_type=client_credentials&scope=${encodeURIComponent(OAUTH_SCOPE)}`,
  });
  if (!resp.ok) throw new Error(`OAuth eBay ${resp.status}`);
  const body = await resp.json();
  cachedToken = {
    value: body.access_token,
    expiresAt: now + (body.expires_in ?? 7200) * 1000,
  };
  return cachedToken.value;
}

async function publicKeyFor(kid, env) {
  const cached = publicKeys.get(kid);
  if (cached) return cached;
  const token = await applicationToken(env);
  const resp = await fetch(PUBLIC_KEY_URL + encodeURIComponent(kid), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) throw new Error(`getPublicKey ${resp.status}`);
  const body = await resp.json();
  const spki = body.key
    .replace("-----BEGIN PUBLIC KEY-----", "")
    .replace("-----END PUBLIC KEY-----", "")
    .replace(/\s+/g, "");
  const key = await crypto.subtle.importKey(
    "spki",
    base64ToBytes(spki),
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["verify"],
  );
  publicKeys.set(kid, key);
  return key;
}

// DER `30 len 02 rlen <r> 02 slen <s>` -> P1363 `<r><s>` de 2*size octets.
function derToP1363(der, size = 32) {
  let offset = 0;
  if (der[offset] !== 0x30) throw new Error("DER : séquence attendue");
  offset += 1;
  offset += der[offset] & 0x80 ? der[offset] - 0x80 + 1 : 1; // saute la longueur
  const readInteger = () => {
    if (der[offset] !== 0x02) throw new Error("DER : entier attendu");
    offset += 1;
    const length = der[offset];
    offset += 1;
    let value = der.slice(offset, offset + length);
    offset += length;
    while (value.length > 0 && value[0] === 0x00) value = value.slice(1);
    if (value.length > size) throw new Error("DER : entier hors borne");
    const padded = new Uint8Array(size);
    padded.set(value, size - value.length);
    return padded;
  };
  const r = readInteger();
  const s = readInteger();
  const out = new Uint8Array(size * 2);
  out.set(r, 0);
  out.set(s, size);
  return out;
}

// Renvoie "ok" (signature valide), "bad" (absente ou invalide) ou "unavailable"
// (impossible de vérifier : clé publique injoignable, jeton refusé…).
async function verifySignature(rawBody, signatureHeader, env) {
  if (!signatureHeader) return "bad";
  if (!env.EBAY_CLIENT_ID || !env.EBAY_CLIENT_SECRET) return "unavailable";
  let meta;
  try {
    meta = JSON.parse(new TextDecoder().decode(base64ToBytes(signatureHeader)));
  } catch {
    return "bad";
  }
  const hash = (meta.digest || "SHA1").toUpperCase() === "SHA1" ? "SHA-1" : "SHA-256";
  let key;
  let p1363;
  try {
    key = await publicKeyFor(meta.kid, env);
    p1363 = derToP1363(base64ToBytes(meta.signature));
  } catch (err) {
    console.log(`signature : vérification indisponible (${err.message})`);
    return "unavailable";
  }
  const algorithm = { name: "ECDSA", hash };
  // eBay signe la forme JSON compacte de la charge utile. Le corps transmis l'est
  // déjà en pratique ; on retente sur une resérialisation compacte par sécurité.
  const candidates = [rawBody];
  try {
    candidates.push(JSON.stringify(JSON.parse(rawBody)));
  } catch {
    /* corps non-JSON : la seule tentative pertinente est le corps brut */
  }
  for (const candidate of candidates) {
    const bytes = new TextEncoder().encode(candidate);
    if (await crypto.subtle.verify(algorithm, key, p1363, bytes)) return "ok";
  }
  return "bad";
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
      const rawBody = await request.text();
      const enforce = env.ENFORCE_SIGNATURE !== "false";
      let verdict = "unavailable";
      try {
        verdict = await verifySignature(rawBody, request.headers.get("x-ebay-signature"), env);
      } catch (err) {
        console.log(`signature : erreur inattendue (${err.message})`);
      }
      if (verdict === "bad" && enforce) {
        console.log("signature : notification rejetée (412)");
        return new Response(null, { status: 412 });
      }

      let payload;
      try {
        payload = JSON.parse(rawBody);
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
          metadata: {
            notificationId: id,
            username,
            receivedAt: new Date().toISOString(),
            verified: verdict === "ok",
          },
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
