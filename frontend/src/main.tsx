import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { OverlayStackProvider } from "./components/ui/overlay-stack";
import "./styles.css";

createRoot(document.getElementById("app") as HTMLElement).render(
  <React.StrictMode>
    <OverlayStackProvider>
      <App />
    </OverlayStackProvider>
  </React.StrictMode>
);
