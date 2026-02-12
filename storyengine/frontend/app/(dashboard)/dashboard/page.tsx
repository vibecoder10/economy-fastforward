import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import Link from "next/link";

export default async function DashboardPage() {
  const session = await getServerSession(authOptions);
  const userId = (session?.user as { id: string })?.id;

  const projects = userId
    ? await prisma.project.findMany({
        where: { userId },
        orderBy: { updatedAt: "desc" },
        take: 10,
      })
    : [];

  return (
    <div className="max-w-5xl">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">Dashboard</h1>
          <p className="text-text-secondary mt-1">
            Welcome back, {session?.user?.name || session?.user?.email}
          </p>
        </div>
        <Link
          href="/new"
          className="px-6 py-2.5 bg-accent hover:bg-accent-hover text-background font-semibold rounded-lg transition-colors"
        >
          New Project
        </Link>
      </div>

      {projects.length === 0 ? (
        <div className="border border-border border-dashed rounded-xl p-12 text-center">
          <h3 className="text-lg font-medium text-text-primary mb-2">
            No projects yet
          </h3>
          <p className="text-text-secondary mb-6">
            Create your first project to start producing visual narratives.
          </p>
          <Link
            href="/new"
            className="inline-flex px-6 py-2.5 bg-accent hover:bg-accent-hover text-background font-semibold rounded-lg transition-colors"
          >
            Create First Project
          </Link>
        </div>
      ) : (
        <div className="grid gap-4">
          {projects.map((project) => (
            <Link
              key={project.id}
              href={`/project/${project.id}`}
              className="block p-5 bg-surface border border-border rounded-xl hover:border-border-hover transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-semibold text-text-primary">
                    {project.title}
                  </h3>
                  <p className="text-sm text-text-secondary mt-1">
                    Status:{" "}
                    <span className="capitalize">{project.status.replace("_", " ")}</span>
                  </p>
                </div>
                <span className="text-xs text-text-tertiary">
                  {new Date(project.updatedAt).toLocaleDateString()}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
