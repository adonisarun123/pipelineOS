import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// M-1: installable PWA with offline read cache + write queue (prod only)
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js");
    window.addEventListener("online", () => {
      navigator.serviceWorker.controller?.postMessage("flush");
    });
  });
}
