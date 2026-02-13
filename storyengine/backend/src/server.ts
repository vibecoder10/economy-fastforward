import "dotenv/config";
import express from "express";
import cors from "cors";
import { agentRoutes } from "./routes/agents";
import { healthRoutes } from "./routes/health";

const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors({ origin: process.env.FRONTEND_URL || "http://localhost:3000" }));
app.use(express.json({ limit: "10mb" }));

// Routes
app.use("/api/health", healthRoutes);
app.use("/api/agents", agentRoutes);

app.listen(PORT, () => {
  console.log(`StoryEngine backend running on port ${PORT}`);
});
