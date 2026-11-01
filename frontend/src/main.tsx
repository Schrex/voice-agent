import { createClient } from "@supabase/supabase-js";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { supabaseAuth } from "./auth";
import "./styles.css";

// Only the project URL and the public anon key reach the browser; the service key never does.
const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App auth={supabaseAuth(supabase)} />
  </StrictMode>,
);
