/**
 * Usage Metering Middleware
 *
 * Logs every API call for billing purposes.
 * Every generation call (image, animation, script, thumbnail) gets tracked.
 */

export interface UsageRecord {
  userId: string;
  projectId: string;
  eventType: "image_gen" | "animation_gen" | "script_gen" | "thumbnail_gen";
  model: string;
  cost: number;
  timestamp: Date;
}

// In-memory buffer for batch writes (will be replaced with DB in Module 8)
const usageBuffer: UsageRecord[] = [];

export function recordUsage(record: UsageRecord): void {
  usageBuffer.push(record);
  console.log(
    `[Usage] ${record.eventType} | user=${record.userId} | model=${record.model} | cost=$${record.cost.toFixed(4)}`
  );
}

export function getUsageForUser(userId: string): UsageRecord[] {
  return usageBuffer.filter((r) => r.userId === userId);
}

export function getUsageForProject(projectId: string): UsageRecord[] {
  return usageBuffer.filter((r) => r.projectId === projectId);
}

export function getTotalCostForUser(userId: string): number {
  return getUsageForUser(userId).reduce((sum, r) => sum + r.cost, 0);
}
