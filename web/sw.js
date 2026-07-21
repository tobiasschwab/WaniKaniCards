"use strict";

// sw.js – minimaler Service Worker für die PWA-Installierbarkeit (Handy-
// Homescreen) + Offline-Grundgerüst.
//
// Strategie bewusst NETWORK-FIRST für alle statischen Dateien (nicht
// Cache-first/stale-while-revalidate): online bekommt der Nutzer damit IMMER
// den frischen Stand direkt nach einem Deploy - der Cache dient nur als
// Fallback, wenn das Netz weg ist. Das vermeidet die klassische PWA-Falle,
// dass ein vergessener Cache-Versions-Bump die App ewig veraltet ausliefert.
// /api/-Requests werden GAR NICHT angefasst (nie cachen: Sitzungs- und
// Lernstands-Daten, POST/DELETE sowieso nicht cachebar).

const CACHE = "shiori-static-v1";

// Kern-Assets fürs Offline-Grundgerüst - best-effort vorab in den Cache
// (fehlt eines, schlägt die Installation trotzdem nicht fehl).
const PRECACHE = [
  "/",
  "/style.css",
  "/app.js",
  "/i18n.js",
  "/i18n/de.json",
  "/i18n/en.json",
  "/vendor/wanakana.min.js",
  "/manifest.webmanifest",
  "/icon-192.png",
  "/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => Promise.allSettled(PRECACHE.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // nie cachen, direkt ans Netz

  event.respondWith(
    fetch(req)
      .then((resp) => {
        if (resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
        }
        return resp;
      })
      .catch(async () => {
        const cached = await caches.match(req);
        if (cached) return cached;
        // Navigation offline ohne Cache-Treffer: aufs App-Shell zurückfallen.
        if (req.mode === "navigate") {
          const shell = await caches.match("/");
          if (shell) return shell;
        }
        return Response.error();
      })
  );
});
