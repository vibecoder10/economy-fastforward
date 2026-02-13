import { Router } from "express";

export const agentRoutes = Router();

/**
 * POST /api/agents/beat-sheet
 * Generate a beat sheet from project inputs.
 * Will be implemented in Module 3.
 */
agentRoutes.post("/beat-sheet", async (req, res) => {
  res.status(501).json({ error: "Beat Sheet Agent not yet implemented (Module 3)" });
});

/**
 * POST /api/agents/script
 * Generate a script scene from beat sheet.
 * Will be implemented in Module 3.
 */
agentRoutes.post("/script", async (req, res) => {
  res.status(501).json({ error: "Script Writer Agent not yet implemented (Module 3)" });
});

/**
 * POST /api/agents/image-prompts
 * Generate image prompts from script scene.
 * Will be implemented in Module 4.
 */
agentRoutes.post("/image-prompts", async (req, res) => {
  res.status(501).json({ error: "Image Prompt Agent not yet implemented (Module 4)" });
});

/**
 * POST /api/agents/animation
 * Generate animation from image.
 * Will be implemented in Module 7.
 */
agentRoutes.post("/animation", async (req, res) => {
  res.status(501).json({ error: "Animation Controller not yet implemented (Module 7)" });
});
