/**
 * MOON Online API Worker
 *
 * Cloudflare Worker that provides a public API endpoint for MOON.
 * It proxies authenticated requests to the MOON local instance via
 * Cloudflare Tunnel, and also provides direct access to MOON's
 * persistent data stored in R2.
 *
 * Usage:
 *   - GET  /api/status          -> MOON status
 *   - POST /api/message         -> Send a message to MOON
 *   - GET  /api/data            -> Get MOON data from R2
 *   - PUT  /api/data            -> Save MOON data to R2
 *   - GET  /api/voice           -> Get voice clones from R2
 *   - PUT  /api/voice           -> Upload voice clone to R2
 */

// CORS headers — allow MOON web HUD, mobile, and external tools
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-API-Key",
  "Access-Control-Max-Age": "86400",
};

// API routes
const ROUTES = {
  // MOON status
  "/api/status": "status",
  // Message to MOON
  "/api/message": "message",
  // R2 data management
  "/api/data": "data",
  // Voice clones
  "/api/voice": "voice",
};

// R2 client configuration
const R2_CONFIG = {
  accountId: "CLOUDFLARE_ACCOUNT_ID",
  bucket: "CLOUDFLARE_BUCKET",
  accessKey: "CLOUDFLARE_ACCESS_KEY",
  secretKey: "CLOUDFLARE_SECRET_KEY",
};

// MOON local instance via Cloudflare Tunnel
// The tunnel exposes the MOON instance at: http://localhost:8777
const MOON_TUNNEL_URL = "http://localhost:8777";

/**
 * Fetch handler for the Cloudflare Worker.
 * Routes requests to the appropriate handler.
 */
export default {
  async fetch(request, env, ctx) {
    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: CORS_HEADERS,
      });
    }

    const url = new URL(request.url);
    const path = url.pathname;

    // Route the request
    for (const [pattern, handlerName] of Object.entries(ROUTES)) {
      if (path.startsWith(pattern)) {
        return await this[handlerName](request, env, ctx, url);
      }
    }

    // Default: return status
    return this.status(request, env, ctx, url);
  },

  /**
   * GET /api/status
   */
  async status(request, env, ctx, url) {
    return new Response(
      JSON.stringify({
        service: "MOON-Online",
        version: "1.0.0",
        status: "online",
        timestamp: new Date().toISOString(),
        endpoints: {
          message: "POST /api/message",
          data: "GET/PUT /api/data",
          voice: "PUT /api/voice",
        },
      }),
      {
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      }
    );
  },

  /**
   * POST /api/message
   * Send a message to MOON for processing.
   * Expected body: { "text": "...", "context": "..." }
   */
  async message(request, env, ctx, url) {
    const body = await request.json().catch(() => ({}));

    // Forward to MOON local instance via tunnel
    try {
      const resp = await fetch(`${MOON_TUNNEL_URL}/api/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...body,
          source: "cloudflare-worker",
          timestamp: new Date().toISOString(),
        }),
      });

      return new Response(await resp.text(), {
        status: resp.status,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    } catch (e) {
      return new Response(
        JSON.stringify({
          error: "MOON local instance unavailable",
          message: "Ensure MOON is running and Cloudflare Tunnel is active",
          details: e.message,
        }),
        {
          status: 503,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        }
      );
    }
  },

  /**
   * GET /api/data — Retrieve data from R2
   */
  async data(request, env, ctx, url) {
    const { accountId, bucket, accessKey, secretKey } = R2_CONFIG;
    const key = url.searchParams.get("key");
    if (!key) {
      return new Response(
        JSON.stringify({ error: "Missing 'key' query parameter" }),
        {
          status: 400,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        }
      );
    }

    try {
      const client = new R2({
        accountId,
        bucket,
        accessKey,
        secretKey,
      });

      const object = await client.get(key);
      if (!object) {
        return new Response(
          JSON.stringify({ error: "Object not found" }),
          {
            status: 404,
            headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
          }
        );
      }

      return new Response(object.body, {
        headers: {
          ...CORS_HEADERS,
          "Content-Type": object.httpMetadata?.contentType || "application/octet-stream",
        },
      });
    } catch (e) {
      return new Response(
        JSON.stringify({ error: "Failed to retrieve data", details: e.message }),
        {
          status: 500,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        }
      );
    }
  },

  /**
   * PUT /api/data — Save data to R2
   */
  async dataPut(request, env, ctx, url) {
    const { accountId, bucket, accessKey, secretKey } = R2_CONFIG;
    const key = url.searchParams.get("key");
    if (!key) {
      return new Response(
        JSON.stringify({ error: "Missing 'key' query parameter" }),
        {
          status: 400,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        }
      );
    }

    try {
      const body = request.body;
      if (!body) {
        return new Response(
          JSON.stringify({ error: "Empty request body" }),
          {
            status: 400,
            headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
          }
        );
      }

      const client = new R2({
        accountId,
        bucket,
        accessKey,
        secretKey,
      });

      await client.put(key, body, {
        httpMetadata: {
          contentType: request.headers.get("Content-Type") || "application/octet-stream",
        },
      });

      return new Response(
        JSON.stringify({
          status: "saved",
          key,
          timestamp: new Date().toISOString(),
        }),
        {
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        }
      );
    } catch (e) {
      return new Response(
        JSON.stringify({ error: "Failed to save data", details: e.message }),
        {
          status: 500,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        }
      );
    }
  },

  /**
   * PUT /api/voice — Upload voice clone to R2
   */
  async voicePut(request, env, ctx, url) {
    const { accountId, bucket, accessKey, secretKey } = R2_CONFIG;
    const voiceId = url.searchParams.get("id");
    if (!voiceId) {
      return new Response(
        JSON.stringify({ error: "Missing 'id' query parameter" }),
        {
          status: 400,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        }
      );
    }

    try {
      const body = request.body;
      if (!body) {
        return new Response(
          JSON.stringify({ error: "Empty request body" }),
          {
            status: 400,
            headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
          }
        );
      }

      const client = new R2({
        accountId,
        bucket,
        accessKey,
        secretKey,
      });

      const key = `voice/${voiceId}.wav`;
      await client.put(key, body, {
        httpMetadata: { contentType: "audio/wav" },
      });

      return new Response(
        JSON.stringify({
          status: "saved",
          key,
          timestamp: new Date().toISOString(),
        }),
        {
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        }
      );
    } catch (e) {
      return new Response(
        JSON.stringify({ error: "Failed to save voice", details: e.message }),
        {
          status: 500,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        }
      );
    }
  },
};

/**
 * R2 Storage client for Cloudflare R2 (S3-compatible).
 * Usage:
 *   const client = new R2({ accountId, bucket, accessKey, secretKey });
 *   await client.put("path/to/file", body, { httpMetadata: { contentType: "..." } });
 *   const object = await client.get("path/to/file");
 */
class R2 {
  constructor(config) {
    this.accountId = config.accountId;
    this.bucket = config.bucket;
    this.accessKey = config.accessKey;
    this.secretKey = config.secretKey;
    this.endpoint = `https://${config.accountId}.r2.cloudflarestorage.com`;
  }

  /**
   * Upload a body to R2
   */
  async put(key, body, options = {}) {
    const response = await fetch(`${this.endpoint}/${this.bucket}/${key}`, {
      method: "PUT",
      headers: {
        "Content-Type": options.httpMetadata?.contentType || "application/octet-stream",
        "X-Amz-Account-Id": this.accountId,
        "X-Amz-Date": new Date().toISOString(),
      },
      body,
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`R2 PUT failed: ${error}`);
    }
  }

  /**
   * Download an object from R2
   */
  async get(key) {
    const response = await fetch(`${this.endpoint}/${this.bucket}/${key}`, {
      method: "GET",
      headers: {
        "X-Amz-Account-Id": this.accountId,
      },
    });

    if (!response.ok) {
      if (response.status === 404) {
        return null;
      }
      const error = await response.text();
      throw new Error(`R2 GET failed: ${error}`);
    }

    return {
      body: response.body,
      httpMetadata: {
        contentType: response.headers.get("Content-Type"),
      },
    };
  }

  /**
   * Delete an object from R2
   */
  async delete(key) {
    const response = await fetch(`${this.endpoint}/${this.bucket}/${key}`, {
      method: "DELETE",
      headers: {
        "X-Amz-Account-Id": this.accountId,
      },
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`R2 DELETE failed: ${error}`);
    }
  }
}
