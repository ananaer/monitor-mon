"use client";

import { sdk } from "@farcaster/miniapp-sdk";
import { useEffect } from "react";

import SheepGamePage from "./sheep/SheepGamePage";

function App() {
  useEffect(() => {
    sdk.actions.ready();
  }, []);

  return <SheepGamePage />;
}

export default App;
