"use client";

// The home screen = the shared chat engine in its default (un-docked) mode: the
// creative producer + "Start Here" onboarding. All the logic lives in ChatCore so
// the same engine can also run as the in-pipeline co-pilot dock. This wrapper keeps
// the home page's import (`<ChatHome />`) and behavior unchanged.

import { ChatCore } from "./ChatCore";

export function ChatHome() {
  return <ChatCore />;
}
